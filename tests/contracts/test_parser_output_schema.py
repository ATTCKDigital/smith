"""Validate every parser fixture output against contracts/parser-output.schema.json.

Uses `jsonschema` if available; otherwise a minimal stdlib-only validator
covering the subset of Draft-07 actually used by the schema (required,
type, enum, items, additionalProperties for objects, integer minimum,
string minLength, oneOf is NOT used in this schema, so the homegrown
validator suffices).

    python3 -m unittest tests.contracts.test_parser_output_schema
"""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SCHEMA_PATH = os.path.join(
    REPO,
    "specs",
    "19-manifest-system",
    "contracts",
    "parser-output.schema.json",
)
PY_PARSER = os.path.join(REPO, "scripts", "parsers", "parse-python.py")
JS_PARSER = os.path.join(REPO, "scripts", "parsers", "parse-js.js")
PY_FIXTURES = os.path.join(REPO, "tests", "parsers", "fixtures", "python")
JS_FIXTURES = os.path.join(REPO, "tests", "parsers", "fixtures", "js")


def _load_schema() -> dict:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# --- Minimal validator -----------------------------------------------------
class SchemaError(AssertionError):
    pass


def _type_ok(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_type_ok(value, e) for e in expected)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return True


def validate(value: Any, schema: dict, where: str = "$") -> None:
    if "type" in schema:
        if not _type_ok(value, schema["type"]):
            raise SchemaError(
                f"{where}: expected type {schema['type']!r}, got {type(value).__name__}"
            )

    if "enum" in schema:
        if value not in schema["enum"]:
            raise SchemaError(f"{where}: value {value!r} not in enum {schema['enum']}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise SchemaError(
                f"{where}: string length {len(value)} < minLength {schema['minLength']}"
            )

    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaError(f"{where}: {value} < minimum {schema['minimum']}")

    if isinstance(value, list):
        items = schema.get("items")
        if items is not None:
            for i, item in enumerate(value):
                validate(item, items, f"{where}[{i}]")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise SchemaError(f"{where}: missing required key {key!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    raise SchemaError(f"{where}: unexpected key {k!r}")
        for k, v in value.items():
            if k in props:
                validate(v, props[k], f"{where}.{k}")


def _try_jsonschema_validate(value: Any, schema: dict) -> None:
    try:
        import jsonschema  # type: ignore

        jsonschema.validate(value, schema)
    except ImportError:
        validate(value, schema)


def _parse_python(path: str) -> dict:
    r = subprocess.run(
        ["python3", PY_PARSER, path], capture_output=True, text=True, timeout=10
    )
    if r.returncode != 0:
        raise AssertionError(f"py parser exit {r.returncode}: {r.stderr}")
    return json.loads(r.stdout)


def _parse_js(path: str) -> dict:
    r = subprocess.run(
        ["node", JS_PARSER, path], capture_output=True, text=True, timeout=10
    )
    if r.returncode != 0:
        raise AssertionError(f"js parser exit {r.returncode}: {r.stderr}")
    return json.loads(r.stdout)


class ParserOutputSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load_schema()

    def test_all_python_fixtures_conform(self):
        names = [n for n in os.listdir(PY_FIXTURES) if n.endswith(".py")]
        self.assertGreater(len(names), 0)
        for name in names:
            with self.subTest(fixture=name):
                out = _parse_python(os.path.join(PY_FIXTURES, name))
                _try_jsonschema_validate(out, self.schema)

    def test_all_js_fixtures_conform(self):
        names = [
            n
            for n in os.listdir(JS_FIXTURES)
            if n.endswith((".js", ".jsx", ".ts", ".tsx"))
        ]
        self.assertGreater(len(names), 0)
        for name in names:
            with self.subTest(fixture=name):
                out = _parse_js(os.path.join(JS_FIXTURES, name))
                _try_jsonschema_validate(out, self.schema)

    def test_minimal_validator_detects_bad_shapes(self):
        """Sanity: the homegrown validator catches at least obvious violations."""
        with self.assertRaises(SchemaError):
            validate({"path": "x"}, self.schema)  # missing required keys


if __name__ == "__main__":
    unittest.main(verbosity=2)
