"""Domain logic for Role Intelligence source bundle preparation and provenance tagging."""

from __future__ import annotations

import copy
from typing import Any


def tag_text(text: str, prefix: str) -> str:
    """Tag non-empty source lines with stable, human-readable IDs (e.g., [J001], [R001])."""
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
    """Validate and enrich job and resume payloads with stable line-tag provenance."""
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
