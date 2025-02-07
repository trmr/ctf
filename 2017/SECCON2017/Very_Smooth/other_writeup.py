from Crypto.PublicKey import RSA
from primefac import williams_pp1, modinv


def main():
    pub = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDVRqqCXPYd6Xdl9GT7/kiJrYvy
8lohddAsi28qwMXCe2cDWuwZKzdB3R9NEnUxsHqwEuuGJBwJwIFJnmnvWurHjcYj
DUddp+4X8C9jtvCaLTgd+baSjo2eB0f+uiSL/9/4nN+vR3FliRm2mByeFCjppTQl
yioxCqbXYIMxGO4NcQIDAQAB
-----END PUBLIC KEY-----
"""
    pub = RSA.importKey(pub)
    print(pub.e, pub.n)
    p = long(williams_pp1(pub.n))
    q = pub.n / p
    print(p,q)
    assert pub.n == p * q
    priv = RSA.construct((pub.n, pub.e, modinv(pub.e, (p - 1) * (q - 1))))
    print(priv.exportKey('PEM'))


main()