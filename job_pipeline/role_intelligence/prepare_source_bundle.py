#!/usr/bin/env python3
"""Prepare JAT + resume input for Candidate Cockpit prompts.

Adds stable line tags to the job description and resume text so model outputs can
carry lightweight provenance such as J014 and R027.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def tag_text(text: str, prefix: str) -> str:
    """Tag non-empty source lines with stable, human-readable IDs."""
    tagged: list[str] = []
    i = 0
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        i += 1
        tagged.append(f"[{prefix}{i:03d}] {line}")
    return "\n".join(tagged)


def prepare_source_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(bundle)
    job = out.setdefault("job", {})
    resume = out.setdefault("resume", {})

    if not str(job.get("description", "")).strip():
        raise ValueError("job.description is required")
    if not str(resume.get("text", "")).strip():
        raise ValueError("resume.text is required")

    job["tagged_description"] = tag_text(job["description"], "J")
    resume["tagged_text"] = tag_text(resume["text"], "R")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Add provenance line tags to a Candidate Cockpit source bundle")
    ap.add_argument("--input", required=True, help="Input source bundle JSON")
    ap.add_argument("--output", required=True, help="Output tagged source bundle JSON")
    args = ap.parse_args()

    bundle = prepare_source_bundle(load_json(args.input))
    Path(args.output).write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
