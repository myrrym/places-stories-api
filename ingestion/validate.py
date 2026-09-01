"""Validation of the contributed place files.

Deliberately dependency-light: PyYAML and jsonschema, nothing else. This is
the contribution gate, and someone adding a place should be able to check
their work without installing a database driver.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "places"
SCHEMA_FILE = ROOT / "data" / "schema" / "place.schema.json"


class ValidationFailure(Exception):
    """Raised with every problem found, not just the first."""


def _validator() -> Draft202012Validator:
    with SCHEMA_FILE.open(encoding="utf-8") as fh:
        return Draft202012Validator(json.load(fh))


def read_records(data_dir: Path = DATA_DIR) -> list[dict]:
    """Parse and validate every place file. Raises on the first bad dataset."""
    validator = _validator()
    records: list[dict] = []
    errors: list[str] = []
    seen: dict[str, Path] = {}

    for path in sorted(data_dir.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            record = yaml.safe_load(fh)

        if not isinstance(record, dict):
            errors.append(f"{path.name}: not a YAML mapping")
            continue

        for error in sorted(validator.iter_errors(record), key=str):
            location = "/".join(str(p) for p in error.absolute_path) or "<root>"
            errors.append(f"{path.name}: {location}: {error.message}")

        place_id = record.get("id")
        if place_id and path.stem != place_id:
            errors.append(f"{path.name}: id {place_id!r} does not match filename")
        if place_id in seen:
            errors.append(f"{path.name}: duplicate id {place_id!r} (also {seen[place_id].name})")
        elif place_id:
            seen[place_id] = path

        records.append(record)

    if errors:
        raise ValidationFailure("\n".join(errors))
    return records
