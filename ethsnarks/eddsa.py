import math
import bitstring
from collections import namedtuple
from hashlib import sha512
from .field import FQ, SNARK_SCALAR_FIELD
from .jubjub import Point, JUBJUB_L, JUBJUB_Q, JUBJUB_E
from .pedersen import pedersen_hash_zcash_bytes, pedersen_hash_zcash_bits

"""
Implements Pure-EdDSA and Hash-EdDSA

The signer has two secret values:

    * k = Secret key
    * r = Per-(message,key) nonce

The signer provides a signature consiting of two values:

    * R = Point, image of `r*B`
    * s = Image of `r + (k*t)`

The signer provides the verifier with their public key:

    * A = k*B

Both the verifier and the signer calculate the common reference string:

    * t = H(R, A, M)

The nonce `r` is secret, and protects the value `s` from revealing the
signers secret key.

For Hash-EdDSA, the message `M` is compressed before H(R,A,M)

For further information see: https://ed2519.cr.yp.to/eddsa-20150704.pdf
"""


P13N_EDDSA_VERIFY_M = 'EdDSA_Verify.M'
P13N_EDDSA_VERIFY_RAM = 'EdDSA_Verify.RAM'


class Signature(object):
    __slots__ = ('R', 'S')
    def __init__(self, R, S):
        R = R if isinstance(R, Point) else Point(*R)
        S = S if isinstance(S, FQ) else FQ(S)
        assert S.n < JUBJUB_Q and S.n > 0
        self.R = R
        self.S = S

    def __iter__(self):
        return iter([self.R, self.S])


class SignedMessage(namedtuple('_SignedMessage', ('A', 'sig', 'msg'))):
    pass


class _SignatureScheme(object):
    @classmethod
    def to_bytes(cls, M):
        if isinstance(M, Point):
            return M.x.n.to_bytes(32, 'little')
        elif isinstance(M, FQ):
            return M.n.to_bytes(32, 'little')
        elif isinstance(M, bitstring.BitArray):
            return M.tobytes()
        elif not isinstance(M, bytes):
            raise TypeError("Bad type for M: " + str(type(M)))
        return M

    @classmethod
    def to_bits(cls, M):
        if isinstance(M, Point):
            return M.x.bits()
        elif isinstance(M, FQ):
            return M.bits()
        elif isinstance(M, bytes):
            return bitstring.BitArray(M).bin.zfill(8)
        elif isinstance(M, bitstring.BitArray):
            return M.bin
        raise TypeError("Bad type for M: " + str(type(M)))

    @classmethod
    def prehash_message(cls, M):
        """
        Identity function for message

        Can be used to truncate the message before hashing it
        as part of the public parameters.
        """
        return M

    @classmethod
    def hash_public(cls, R, A, M):
        """
        Identity function for public parameters:

            R, A, M

        Is used to multiply the resulting point
        """
        raise NotImplementedError()

    @classmethod
    def hash_secret(cls, k, *args):
        """
        Hash the key and message to create `r`, the blinding factor for this signature.

        If the same `r` value is used more than once, the key for the signature is revealed.

        From: https://eprint.iacr.org/2015/677.pdf (EdDSA for more curves)

        Page 3:

            (Implementation detail: To save time in the computation of `rB`, the signer
            can replace `r` with `r mod L` before computing `rB`.)
        """
        assert isinstance(k, FQ)
        data = b''.join(cls.to_bytes(_) for _ in (k,) + args)
        return int.from_bytes(sha512(data).digest(), 'little') % JUBJUB_L

    @classmethod
    def B(cls):
        return Point.generator()

    @classmethod
    def random_keypair(cls, B=None):
        B = B or cls.B()
        k = FQ.random(JUBJUB_L)
        A = B * k
        return k, A

    @classmethod
    def sign(cls, M, k, B=None):
        raise NotImplementedError()

    @classmethod
    def verify(cls, A, sig, M, B=None):
        raise NotImplementedError()


class PureEdDSA(_SignatureScheme):
    @classmethod
    def hash_public(cls, *args, p13n=P13N_EDDSA_VERIFY_RAM):
        """
        Hash used for the public parameters.

            hash_RAM = H(R,A,M)

        @param R Signature point
        @param A Signers public key
        @param M Hashed message (Point)
        @param p13n Personalisation string
        @returns Point
        """
        bits = ''.join([cls.to_bits(_) for _ in args])
        return pedersen_hash_zcash_bits(p13n, bits).x.n

    @classmethod
    def sign(cls, msg, key, B=None):
        if not isinstance(key, FQ):
            raise TypeError("Invalid type for parameter k")
        # Strict parsing ensures key is in the prime-order group
        if key.n >= JUBJUB_L or key.n <= 0:
            raise RuntimeError("Strict parsing of k failed")

        M = cls.prehash_message(msg)
        B = B or cls.B()
        A = B * key
        r = cls.hash_secret(key, M)       # r = H(k,M) mod L
        R = B * r                         # rB
        t = cls.hash_public(R, A, M)      # Bind the message to the nonce, public key and message
        S = (r + (key.n*t)) % JUBJUB_E    # S -> r + H(R,A,M)*k
        return SignedMessage(A, Signature(R, S), msg)

    @classmethod
    def verify(cls, A, sig, msg, B=None):
        if not isinstance(A, Point):
            A = Point(*A)

        if not isinstance(sig, Signature):
            sig = Signature(*sig)

        R, S = sig
        M = cls.prehash_message(msg)
        B = B or cls.B()
        lhs = B * S
        rhs = R + (A * cls.hash_public(R, A, M))
        return lhs == rhs


class EdDSA(PureEdDSA):
    @classmethod
    def prehash_message(cls, M, p13n=P13N_EDDSA_VERIFY_M):
        return pedersen_hash_zcash_bytes(p13n, M)


def eddsa_random_keypair():
    return EdDSA.random_keypair()


def pureeddsa_verify(*args, **kwa):
    return PureEdDSA.verify(*args, **kwa)


def pureeddsa_sign(*args, **kwa):
    return PureEdDSA.sign(*args, **kwa)


def eddsa_verify(*args, **kwa):
    return EdDSA.verify(*args, **kwa)


def eddsa_sign(*args, **kwa):
    return EdDSA.sign(*args, **kwa)
