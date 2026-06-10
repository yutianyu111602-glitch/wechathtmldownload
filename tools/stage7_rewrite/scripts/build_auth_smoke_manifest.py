#!/usr/bin/env python3
"""Build a one-row manifest for DeepSeek auth smoke tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-input-chars", type=int, default=1000)
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    selected = None
    with source.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            try:
                input_chars = int(row.get("input_chars") or 0)
            except Exception:
                input_chars = 0
            if input_chars >= args.min_input_chars:
                selected = row
                break

    if selected is None:
        raise SystemExit("no smoke candidate found")

    output.write_text(json.dumps(selected, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "article_uid": selected.get("article_uid"),
        "source_account": selected.get("source_account"),
        "title": selected.get("title"),
        "input_chars": selected.get("input_chars"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
