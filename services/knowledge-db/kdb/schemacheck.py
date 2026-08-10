"""Валидация артефактов по JSON Schema Draft 2020-12 + реестр схем."""
from __future__ import annotations

from pathlib import Path

from jsonschema import Draft202012Validator

from .io import load_json_strict

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"


def validate_artifact(obj: object, schema_name: str) -> list[str]:
    """Возвращает список ошибок (пустой = валидно)."""
    schema = load_json_strict(SCHEMAS_DIR / f"{schema_name}.schema.json")
    Draft202012Validator.check_schema(schema)
    v = Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in v.iter_errors(obj)]


def validate_file(path: Path, schema_name: str) -> list[str]:
    return validate_artifact(load_json_strict(path), schema_name)
