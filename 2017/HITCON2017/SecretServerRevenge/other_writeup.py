from pwn import *
import base64, random, string
from Crypto.Hash import MD5, SHA256

def pad(msg):
  pad_length = 16-len(msg)%16
  return msg+chr(pad_length)*pad_length

def unpad(msg):
  return msg[:-ord(msg[-1])]

def xor_str(s1, s2):
  '''XOR between two strings. The longer one is truncated.'''
  return ''.join(chr(ord(x) ^ ord(y)) for x, y in zip(s1, s2))

def blockify(text, blocklen):
  '''Splits the text as a list of blocklen-long strings'''
  return [text[i:i+blocklen] for i in xrange(0, len(text), blocklen)]

def flipiv(oldplain, newplain, iv):
  '''Modifies an IV to produce the desired new plaintext in the following block'''
  flipmask = xor_str(oldplain, newplain)
  return xor_str(iv, flipmask)

def solve_proof(p):
  instructions = p.recvline().strip()
  suffix = instructions[12:28]
  print suffix
  digest = instructions[-64:]
  print digest
  prefix = ''.join(random.choice(string.ascii_letters+string.digits) for _ in xrange(4))
  newdigest = SHA256.new(prefix + suffix).hexdigest()
  while newdigest != digest:
    prefix = ''.join(random.choice(string.ascii_letters+string.digits) for _ in xrange(4))
    newdigest = SHA256.new(prefix + suffix).hexdigest()
  print 'POW:', prefix
  p.sendline(prefix)


HOST = '127.0.0.1'
PORT = 1234
welcomeplain = pad('Welcome!!')

# retry until we guess the token correctly among the candidates
while 1:
  try:
    p = remote(HOST, PORT)
    #solve_proof(p)

    # get welcome
    #welcome = p.recvline(keepends=False)[13:]    # remove prompt
    welcome = p.recvline(keepends=False)
    print 'Welcome:', welcome
    welcome_dec = base64.b64decode(welcome)
    welcomeblocks = blockify(welcome_dec, 16)

    # get command-not-found
    p.sendline(welcome)
    notfound = p.recvline(keepends=False)
    print 'Command not found:', notfound

    # get encrypted token
    payload = flipiv(welcomeplain, 'get-token'.ljust(16, '\x01'), welcomeblocks[0])
    payload += welcomeblocks[1]
    p.sendline(base64.b64encode(payload))
    token = p.recvline(keepends=False)
    print 'Token:', token
    token_dec = base64.b64decode(token)
    tokenblocks = blockify(token_dec, 16)
    tokenlen = len(token_dec) - 16
    print 'Token blocks: ', tokenblocks
    print 'Token length: ', tokenlen

    # get encrypted md5 for the token, cut at every possible index, from 8 to the end
    print ''
    print 'Collecting encrypted md5 hashes...'
    tokenmd5s = []
    for i in range(56):
      # replace first 7 characters with 'get-md5'
      payload = flipiv('token: '.ljust(16, '\x00'), 'get-md5'.ljust(16, '\x00'), tokenblocks[0])
      payload += ''.join(tokenblocks[1:])
      # add a block where we control the last byte, to unpad at the correct length ('token: ' + i characters)
      payload += flipiv(welcomeplain, 'A'*15 + chr(16 + 16 + tokenlen - 7 - 1 - i), welcomeblocks[0])
      payload += welcomeblocks[1]
      p.sendline(base64.b64encode(payload))
      md5_enc = p.recvline(keepends=False)
      print i, md5_enc
      tokenmd5s.append(md5_enc)

    # get the ciphertexts of the md5 hashes of a fixed message for every unpadding length from 32 to 255
    # these will be used as oracles to guess the amount that was unpadded
    # we can reuse some of the ciphertexts we obtained before
    print ''
    print 'Collecting md5 oracles...'
    oraclemd5s = {}    # key = md5ciphertext, value = unpadding amount

    # we will craft a message longer than 256 bytes to check the unpadding up to 256 characters
    for unpad in range(32, 209):
      # 1 block
      payload = flipiv('token: '.ljust(16, '\x00'), 'get-md5'.ljust(16, '\x00'), tokenblocks[0])
      # 1 + 4 = 5 blocks
      payload += ''.join(tokenblocks[1:])
      # 5 + 11 = 16 blocks
      payload += 'A' * 16 * 11    # padding to reach 256 characters
      # 16 + 1 = 17 blocks
      payload += flipiv(welcomeplain, chr(unpad).rjust(16, '\x00'), welcomeblocks[0])    # replace last byte
      # 17 + 1 = 18 blocks
      payload += welcomeblocks[1]

      p.sendline(base64.b64encode(payload))
      md5_enc = p.recvline(keepends=False)
      print unpad, md5_enc
      oraclemd5s[md5_enc] = unpad

    # we can reuse the ciphertexts when the additional crafted message is unpadded away
    for unpad in range(209, 256):
      md5_enc = tokenmd5s[8 + 1 + 255 - unpad]
      print unpad, md5_enc
      oraclemd5s[md5_enc] = unpad


    # send token md5 hashes without padding block, compare unpadding to known ciphertexts
    print ''
    print 'Revealing last byte for each md5 hash...'
    candidates = ['']
    for index in range(56):
      # send the same crafted message as before, but replace last block with the md5 ciphertext
      payload = flipiv('token: '.ljust(16, '\x00'), 'get-md5'.ljust(16, '\x00'), tokenblocks[0])
      payload += ''.join(tokenblocks[1:])
      payload += 'A' * 16 * 11
      payload += base64.b64decode(tokenmd5s[index])[:-16]    # send whole md5 ciphertext without padding
      p.sendline(base64.b64encode(payload))

      print index
      res = p.recvline(keepends=False)
      print "received:", res

      # if the ciphertext is in oraclemd5s, we know the last byte of the md5 hash
      if res in oraclemd5s:
        lastbyte = oraclemd5s[res]
        print 'Found byte:', hex(lastbyte)
        newcandidates = []
        for x in candidates:
          for c in range(256):
            if MD5.new(x + chr(c)).digest()[-1] == chr(lastbyte):
              newcandidates.append(x + chr(c))
        candidates = newcandidates

      # if the ciphertext is the one for 'command not found', the plaintext was completely unpadded
      # the last byte is 0 (plain = plain[:-0] -> '')
      elif res == notfound:
        print 'Command not found -> 0'
        lastbyte = 0
        newcandidates = []
        for x in candidates:
          for c in range(256):
            if MD5.new(x + chr(c)).digest()[-1] == chr(lastbyte):
              newcandidates.append(x + chr(c))
        candidates = newcandidates

      # if we haven't seen the ciphertext before, the unpadding included the last 2 blocks
      else:
        print 'Not found. [1-32]'

        # flip most significant bit of last byte to move it in a good range
        newpayload = payload[:-17] + xor_str(payload[-17], '\x80') + payload[-16:]
        p.sendline(base64.b64encode(newpayload))
        res = p.recvline(keepends=False)

        # check, same as before
        if res in oraclemd5s:
          lastbyte = oraclemd5s[res] ^ 0x80
          print 'Found byte:', hex(lastbyte)
          newcandidates = []
          for x in candidates:
            for c in range(256):
              if MD5.new(x + chr(c)).digest()[-1] == chr(lastbyte):
                newcandidates.append(x + chr(c))
          candidates = newcandidates
        elif res == notfound:
          print 'Command not found -> 0'
          lastbyte = 0 ^ 0x80
          newcandidates = []
          for x in candidates:
            for c in range(256):
              if MD5.new(x + chr(c)).digest()[-1] == chr(lastbyte):
                newcandidates.append(x + chr(c))
          candidates = newcandidates
        else:
          raise AssertionError("Something went wrong, couldn't identify byte.")

    print ''
    print 'Candidates:'
    print candidates
    print 'No. of candidates:', len(candidates)

    # if there's more than one candidate, we can remove some of them
    if len(candidates) > 0:
      print ''
      print 'Reducing number of candidates...'
      # get characters no. 8, 24, 40, at the end of each token block
      for block in range(3):
        index = 8 + block * 16
        # send same crafted message as before, but with one of the token blocks at the end (to find its last byte)
        payload = flipiv('token: '.ljust(16, '\x00'), 'get-md5'.ljust(16, '\x00'), tokenblocks[0])
        payload += ''.join(tokenblocks[1:])
        payload += 'A' * 16 * 11
        payload += tokenblocks[block]
        payload += tokenblocks[block + 1]
        p.sendline(base64.b64encode(payload))

        print 'Byte at:', index
        res = p.recvline(keepends=False)
        print "received:", res

        # same checks as before
        if res in oraclemd5s:
          lastbyte = oraclemd5s[res]
          print 'Found byte:', hex(lastbyte)
          candidates = filter(lambda x: x[index] == chr(lastbyte), candidates)
          print 'Candidates:'
          print candidates
        elif res == notfound:
          print 'Command not found -> 0'
          lastbyte = 0
          candidates = filter(lambda x: x[index] == chr(lastbyte), candidates)
          print 'Candidates:'
          print candidates
        else:
          print 'Not found. [1-32]'
          # flip most significant bit of last byte to move it in a good range
          newpayload = payload[:-17] + xor_str(payload[-17], '\x80') + payload[-16:]
          p.sendline(base64.b64encode(newpayload))
          res = p.recvline(keepends=False)

          if res in oraclemd5s:
            lastbyte = oraclemd5s[res] ^ 0x80
            print 'Found byte:', hex(lastbyte)
            candidates = filter(lambda x: x[index] == chr(lastbyte), candidates)
            print 'Candidates:'
            print candidates
          elif res == notfound:
            print 'Command not found -> 0'
            lastbyte = 0 ^ 0x80
            candidates = filter(lambda x: x[index] == chr(lastbyte), candidates)
            print 'Candidates:'
            print candidates
          else:
            raise AssertionError("Something went wrong, couldn't identify byte.")

    print ''
    print 'Candidates left:', len(candidates)

    # if we didn't narrow down the candidates to a single one, we will just send the first one
    token = candidates[0]

    # send token and get flag
    payload = flipiv(welcomeplain, pad('check-token'), welcomeblocks[0])
    payload += welcomeblocks[1]
    p.sendline(base64.b64encode(payload))

    print ''
    print p.recvline(keepends=False)    # 'Give me the token!'
    print 'Sending token...'
    p.sendline(base64.b64encode(token))
    flag = p.recvline(keepends=False)
    print 'Flag:'
    print flag

    with open('flag', 'w') as f:
      f.write(flag)

    exit(0)

  # if the token was not correct, try again
  except EOFError:
    print 'Failed! Trying again...'
    print ''
    p.close()
    continue