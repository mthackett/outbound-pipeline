#!/usr/bin/env python3
"""Create copy/paste prompt payloads for the two-stage Candidate Cockpit workflow.

This helper is deliberately model-provider agnostic. It does not call an LLM.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a prompt payload from Candidate Cockpit source JSON")
    ap.add_argument("--stage", choices=["strategy", "compose", "all-in-one"], required=True)
    ap.add_argument("--source", required=True, help="Tagged source bundle JSON")
    ap.add_argument("--strategy", help="Strategy JSON, required for compose")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    source = json.loads(Path(args.source).read_text(encoding="utf-8"))

    if args.stage == "strategy":
        prompt = read(PACKAGE_DIR / "prompts" / "value_match_strategy_prompt.md")
        body = f"{prompt}\n\n# SOURCE_BUNDLE\n{json.dumps(source, indent=2, ensure_ascii=False)}\n"
    elif args.stage == "compose":
        if not args.strategy:
            ap.error("--strategy is required for --stage compose")
        strategy = json.loads(Path(args.strategy).read_text(encoding="utf-8"))
        prompt = read(PACKAGE_DIR / "prompts" / "cockpit_composition_prompt.md")
        body = (
            f"{prompt}\n\n# SOURCE_BUNDLE\n{json.dumps(source, indent=2, ensure_ascii=False)}"
            f"\n\n# VALUE_MATCH_STRATEGY\n{json.dumps(strategy, indent=2, ensure_ascii=False)}\n"
        )
    else:
        prompt = read(PACKAGE_DIR / "prompts" / "all_in_one_prompt.md")
        body = f"{prompt}\n\n# SOURCE_BUNDLE\n{json.dumps(source, indent=2, ensure_ascii=False)}\n"

    Path(args.output).write_text(body, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
