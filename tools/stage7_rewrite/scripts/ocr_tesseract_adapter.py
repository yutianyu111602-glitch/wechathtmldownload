#!/usr/bin/env python3
"""Tesseract OCR adapter for the Stage7 OCR command contract.

This is a conservative local fallback for staging canaries. It exits non-zero
when the OCR text is too weak, so `run_ocr_direct.py` records the article as
`no_text` rather than promoting low-quality noise as successful OCR.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


MIN_MEANINGFUL_CHARS = 15


def normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def meaningful_char_count(text: str) -> int:
    return len(re.findall(r"[0-9A-Za-z\u4e00-\u9fff]", text))


def looks_useful(text: str) -> bool:
    normalized = normalize_text(text)
    if meaningful_char_count(normalized) < MIN_MEANINGFUL_CHARS:
        return False
    tokens = re.findall(r"[0-9A-Za-z\u4e00-\u9fff]{2,}", normalized)
    return len(tokens) >= 2


def recovered_from_text(text: str) -> dict[str, object]:
    lines = [line.strip() for line in normalize_text(text).split("\n") if line.strip()]
    date_texts = [line for line in lines if re.search(r"\d{4}[-./年]\d{1,2}|\d{1,2}[-./月]\d{1,2}", line)]
    lineup = [line for line in lines if re.search(r"\b(DJ|LIVE|B2B|LINEUP|VJ|ACT)\b|演出|阵容", line, re.I)]
    venue = ""
    for line in lines:
        if re.search(r"club|venue|room|space|live|house|bar|俱乐部|场地|现场", line, re.I):
            venue = line
            break
    return {"venue_name_candidate": venue, "date_texts": date_texts[:5], "lineup_lines": lineup[:10]}


def run_tesseract(image_path: Path, timeout: int = 30) -> tuple[int, str, str]:
    command = ["tesseract", str(image_path), "stdout", "-l", "eng", "--psm", "6"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def payload(image_path: Path, text: str, warnings: list[str]) -> dict[str, object]:
    normalized = normalize_text(text)
    lines = [line for line in normalized.split("\n") if line.strip()]
    return {
        "backend": "tesseract-eng-local",
        "plain_text": normalized,
        "blocks": [{"text": line, "score": 0.0} for line in lines],
        "imageHeavy": len(normalized) < 100,
        "candidates": [{"local_path": str(image_path)}],
        "recovered": recovered_from_text(normalized),
        "warnings": warnings,
        "quality": {
            "meaningful_chars": meaningful_char_count(normalized),
            "accepted": looks_useful(normalized),
            "min_meaningful_chars": MIN_MEANINGFUL_CHARS,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(json.dumps({"backend": "error", "plain_text": "", "blocks": [], "warnings": ["Usage: ocr_tesseract_adapter.py <image_path>"]}, ensure_ascii=False))
        return 1
    image_path = Path(args[0])
    if not image_path.exists():
        print(json.dumps({"backend": "error", "plain_text": "", "blocks": [], "warnings": [f"File not found: {image_path}"]}, ensure_ascii=False))
        return 1
    try:
        code, stdout, stderr = run_tesseract(image_path)
    except Exception as exc:
        print(json.dumps({"backend": "error", "plain_text": "", "blocks": [], "warnings": [str(exc)]}, ensure_ascii=False))
        return 1
    warnings = []
    if code != 0:
        warnings.append((stderr or f"tesseract exited {code}")[:500])
        print(json.dumps(payload(image_path, stdout, warnings), ensure_ascii=False))
        return code or 1
    report = payload(image_path, stdout, warnings)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["quality"]["accepted"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
