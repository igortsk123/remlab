from kdb.canonical import derived_id, jcs_bytes, jcs_sha256


def test_jcs_key_order_independent():
    a = {"b": 1, "a": [2, {"y": None, "x": "ü"}]}
    b = {"a": [2, {"x": "ü", "y": None}], "b": 1}
    assert jcs_bytes(a) == jcs_bytes(b)
    assert jcs_sha256(a) == jcs_sha256(b)


def test_derived_id_stable_and_prefixed():
    p = {"source_assertion_uid": "X::1"}
    i1 = derived_id("ATOM", p)
    i2 = derived_id("ATOM", dict(p))
    assert i1 == i2
    assert i1.startswith("ATOM_") and len(i1) == 5 + 64


def test_derived_id_sensitive_to_payload():
    assert derived_id("A", {"k": 1}) != derived_id("A", {"k": 2})
