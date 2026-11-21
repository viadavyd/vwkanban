import random

import pytest

from vwkanban.sync.fracindex import InvalidKeyError, key_between, validate


def between(a, b):
    k = key_between(a, b)
    validate(k)
    if a is not None:
        assert a < k, (a, b, k)
    if b is not None:
        assert k < b, (a, b, k)
    return k


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (None, None, "a0"),
        (None, "a0", "Zz"),
        ("a0", None, "a1"),
        ("a0", "a1", "a0V"),
        ("a1", "a2", "a1V"),
        ("a0V", "a1", "a0l"),
        ("Zz", "a0", "ZzV"),
        ("a0", "a0V", "a0G"),
        ("az", None, "b00"),
        ("Zy", None, "Zz"),
    ],
)
def test_known_values(a, b, expected):
    assert between(a, b) == expected


def test_edges():
    k = None
    for _ in range(100):  # keep prepending
        k = between(None, k)
    k = None
    for _ in range(100):  # keep appending
        k = between(k, None)
    a, b = "a0", "a1"
    for _ in range(50):  # keep splitting the same gap
        b = between(a, b)


@pytest.mark.parametrize("bad", ["", "a", "a00", "a10", "A" + "0" * 26, "a0!", "?0"])
def test_invalid_keys(bad):
    with pytest.raises(InvalidKeyError):
        key_between(bad, None)


def test_wrong_order():
    with pytest.raises(InvalidKeyError):
        key_between("a1", "a0")
    with pytest.raises(InvalidKeyError):
        key_between("a1", "a1")


def _random_inserts(n: int, seed: int) -> None:
    rnd = random.Random(seed)
    keys: list[str] = []  # kept in list order; must stay sorted byte-wise
    for _ in range(n):
        i = rnd.randint(0, len(keys))
        a = keys[i - 1] if i > 0 else None
        b = keys[i] if i < len(keys) else None
        keys.insert(i, between(a, b))
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
    # Byte-wise order == Python str order for these ASCII keys (COLLATE "C").
    assert keys == sorted(keys, key=lambda k: k.encode())


def test_1000_random_inserts_stay_ordered():
    _random_inserts(1_000, seed=1)


def test_10k_random_inserts_property():
    _random_inserts(10_000, seed=2)
