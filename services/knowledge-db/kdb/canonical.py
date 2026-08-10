"""JCS (RFC 8785) канонизация, SHA-256 и DERIVED_ID.

Инвариант спеки (derived_id_policy): identity payload содержит только
identity-определяющую семантику/стабильные upstream-ID — никаких таймстампов,
свободного текста-обоснований и порядка обработки.
"""
from __future__ import annotations

import hashlib

import rfc8785


def jcs_bytes(obj: object) -> bytes:
    return rfc8785.dumps(obj)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jcs_sha256(obj: object) -> str:
    return sha256_hex(jcs_bytes(obj))


def derived_id(prefix: str, identity_payload: dict) -> str:
    return f"{prefix}_{jcs_sha256(identity_payload)}"
