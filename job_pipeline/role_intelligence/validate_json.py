#!/usr/bin/env python3
"""Validate Candidate Cockpit JSON artifacts against bundled JSON Schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate a JSON file against a Candidate Cockpit schema")
    ap.add_argument("--schema", required=True)
    ap.add_argument("--input", required=True)
    args = ap.parse_args()

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        for err in errors:
            loc = ".".join(map(str, err.path)) or "<root>"
            print(f"ERROR {loc}: {err.message}")
        raise SystemExit(1)
    print(f"OK: {args.input}")


if __name__ == "__main__":
    main()
