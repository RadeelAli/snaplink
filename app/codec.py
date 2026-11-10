"""Base62 encoding for short codes.

IDs are obfuscated with a multiplicative bijection modulo 62**N before encoding, so
sequential database IDs don't produce guessable, sequential short codes.
"""

from __future__ import annotations

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)
_INDEX = {ch: i for i, ch in enumerate(ALPHABET)}

# Must be coprime with 62 (i.e. odd and not divisible by 31) for the mapping to be a bijection.
_MULTIPLIER = 1_580_030_173
_SPACE = BASE**8  # supports ~2.1e14 IDs before codes grow beyond 8 chars
_INVERSE = pow(_MULTIPLIER, -1, _SPACE)


def encode(n: int) -> str:
    if n < 0:
        raise ValueError("cannot encode negative numbers")
    if n == 0:
        return ALPHABET[0]
    out: list[str] = []
    while n:
        n, rem = divmod(n, BASE)
        out.append(ALPHABET[rem])
    return "".join(reversed(out))


def decode(s: str) -> int:
    if not s:
        raise ValueError("cannot decode empty string")
    n = 0
    for ch in s:
        try:
            n = n * BASE + _INDEX[ch]
        except KeyError:
            raise ValueError(f"invalid character {ch!r}") from None
    return n


def obfuscate(n: int) -> int:
    if not 0 <= n < _SPACE:
        raise ValueError("id out of range")
    return (n * _MULTIPLIER) % _SPACE


def deobfuscate(n: int) -> int:
    return (n * _INVERSE) % _SPACE


def id_to_code(n: int, min_length: int = 6) -> str:
    return encode(obfuscate(n)).rjust(min_length, ALPHABET[0])


def is_valid_code(s: str) -> bool:
    return bool(s) and all(ch in _INDEX for ch in s)
