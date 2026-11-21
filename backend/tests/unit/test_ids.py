from vwkanban.ids import uuid7


def test_uuid7_version_and_variant():
    u = uuid7()
    assert u.version == 7
    assert u.variant == "specified in RFC 4122"


def test_uuid7_is_time_ordered_and_unique():
    ids = [uuid7() for _ in range(2000)]
    assert len(set(ids)) == len(ids)
    # Same-ms ids are random within the ms, so compare only the timestamp prefix.
    stamps = [u.int >> 80 for u in ids]
    assert stamps == sorted(stamps)
