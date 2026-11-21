"""Fractional-index keys (plan §0 "Ordering"). Only the server computes them (apply_op).

Format (the well-known base-62 "a0" scheme): an integer part whose length is set by its
head character (`a`..`z` = 2..27 chars, `A`..`Z` = 27..2 chars, for negatives), then an
optional fraction that never ends in "0". Keys compare byte-wise, which is why every
`position` column uses `COLLATE "C"`. The board seed keys `a0`, `a1`, `a2` are valid keys.
"""

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
INTEGER_ZERO = "a0"
SMALLEST_INTEGER = "A" + "0" * 26


class InvalidKeyError(ValueError):
    """An invalid key, or neighbours given in the wrong order."""


def _integer_length(head: str) -> int:
    if "a" <= head <= "z":
        return ord(head) - ord("a") + 2
    if "A" <= head <= "Z":
        return ord("Z") - ord(head) + 2
    raise InvalidKeyError(f"invalid key head: {head!r}")


def _integer_part(key: str) -> str:
    n = _integer_length(key[0])
    if n > len(key):
        raise InvalidKeyError(f"invalid key: {key!r}")
    return key[:n]


def validate(key: str) -> None:
    if not key or key == SMALLEST_INTEGER:
        raise InvalidKeyError(f"invalid key: {key!r}")
    i = _integer_part(key)
    if any(c not in DIGITS for c in key[1:]):
        raise InvalidKeyError(f"invalid key: {key!r}")
    if key[len(i) :].endswith("0"):
        raise InvalidKeyError(f"invalid key: {key!r}")


def _midpoint(a: str, b: str | None) -> str:
    """A fraction strictly between fractions `a` and `b` (None = no upper bound)."""
    if b is not None and a >= b:
        raise InvalidKeyError(f"{a!r} >= {b!r}")
    if a.endswith("0") or (b is not None and b.endswith("0")):
        raise InvalidKeyError("trailing zero")
    if b:
        n = 0
        while (a[n] if n < len(a) else "0") == b[n]:
            n += 1
        if n > 0:
            return b[:n] + _midpoint(a[n:], b[n:])
    digit_a = DIGITS.index(a[0]) if a else 0
    digit_b = DIGITS.index(b[0]) if b is not None else len(DIGITS)
    if digit_b - digit_a > 1:
        return DIGITS[(digit_a + digit_b + 1) // 2]
    if b is not None and len(b) > 1:
        return b[:1]
    return DIGITS[digit_a] + _midpoint(a[1:], None)


def _increment(x: str) -> str | None:
    head, digs = x[0], list(x[1:])
    for i in range(len(digs) - 1, -1, -1):
        d = DIGITS.index(digs[i]) + 1
        if d < len(DIGITS):
            digs[i] = DIGITS[d]
            return head + "".join(digs)
        digs[i] = "0"
    if head == "Z":
        return INTEGER_ZERO
    if head == "z":
        return None
    h = chr(ord(head) + 1)
    if h > "a":
        digs.append("0")
    else:
        digs.pop()
    return h + "".join(digs)


def _decrement(x: str) -> str | None:
    head, digs = x[0], list(x[1:])
    for i in range(len(digs) - 1, -1, -1):
        d = DIGITS.index(digs[i]) - 1
        if d >= 0:
            digs[i] = DIGITS[d]
            return head + "".join(digs)
        digs[i] = DIGITS[-1]
    if head == "a":
        return "Z" + DIGITS[-1]
    if head == "A":
        return None
    h = chr(ord(head) - 1)
    if h < "Z":
        digs.append(DIGITS[-1])
    else:
        digs.pop()
    return h + "".join(digs)


def key_between(a: str | None, b: str | None) -> str:
    """A key strictly between `a` and `b`; None means open-ended on that side."""
    if a is not None:
        validate(a)
    if b is not None:
        validate(b)
    if a is not None and b is not None and a >= b:
        raise InvalidKeyError(f"{a!r} >= {b!r}")
    if a is None:
        if b is None:
            return INTEGER_ZERO
        ib = _integer_part(b)
        fb = b[len(ib) :]
        if ib == SMALLEST_INTEGER:
            return ib + _midpoint("", fb)
        if ib < b:
            return ib
        res = _decrement(ib)
        if res is None:
            raise InvalidKeyError("cannot go below the smallest key")
        return res
    ia = _integer_part(a)
    fa = a[len(ia) :]
    if b is None:
        i = _increment(ia)
        return ia + _midpoint(fa, None) if i is None else i
    ib = _integer_part(b)
    fb = b[len(ib) :]
    if ia == ib:
        return ia + _midpoint(fa, fb)
    i = _increment(ia)
    if i is None:
        raise InvalidKeyError("cannot go above the largest key")
    if i < b:
        return i
    return ia + _midpoint(fa, None)
