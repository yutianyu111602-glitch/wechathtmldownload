#!/usr/bin/env python3
"""GPU OCR command — CnOCR (Chinese) + EasyOCR (English) with auto-detection.

Compatible with WECHAT_OCR_COMMAND contract.

Strategy:
  CnOCR (RapidOCR/ONNX) → Chinese + Mixed text (80% CN accuracy, 10-11s)
  EasyOCR               → English-only text (faster, 3-4s)

Usage:
  python scripts/ocr_gpu.py /path/to/poster.jpg [--cn|--en|--mix]

Output (JSON to stdout):
  {"backend": "cnocr|cpu" | "easyocr-gpu-en", "plain_text": "...", "blocks": [...]}
"""
import json, os, re, sys, time
import torch

_cnocr = None
_easyocr_en = None
_easyocr_mix = None


def _get_cnocr():
    global _cnocr
    if _cnocr is None:
        from cnocr import CnOcr
        t0 = time.perf_counter()
        _cnocr = CnOcr(rec_model_name='ch_PP-OCRv3')
        dt = time.perf_counter() - t0
        print(f"[ocr_gpu] CnOCR init: {dt:.1f}s", file=sys.stderr)
    return _cnocr


def _get_easyocr(lang='en'):
    global _easyocr_en, _easyocr_mix
    import easyocr
    if lang == 'mix':
        if _easyocr_mix is None:
            t0 = time.perf_counter()
            _easyocr_mix = easyocr.Reader(['ch_sim', 'en'], gpu=torch.cuda.is_available())
            dt = time.perf_counter() - t0
            print(f"[ocr_gpu] EasyOCR-mix init: {dt:.1f}s", file=sys.stderr)
        return _easyocr_mix
    else:
        if _easyocr_en is None:
            t0 = time.perf_counter()
            _easyocr_en = easyocr.Reader(['en'], gpu=torch.cuda.is_available())
            dt = time.perf_counter() - t0
            print(f"[ocr_gpu] EasyOCR-en init: {dt:.1f}s", file=sys.stderr)
        return _easyocr_en


def _safe_score(val) -> float:
    """Ensure score is valid JSON number (no NaN/Inf)."""
    import math
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return 0.0
        return round(v, 4)
    except (ValueError, TypeError):
        return 0.0


def ocr_image(image_path: str, lang: str | None = None) -> dict:
    """Run OCR, return WECHAT_OCR_COMMAND contract dict."""
    if not os.path.exists(image_path):
        return {"backend": "error", "plain_text": "", "blocks": [], "warnings": [f"File not found: {image_path}"]}

    # Auto-detect language
    if lang is None:
        lang = _detect_language(image_path)

    if lang == 'en':
        # English → EasyOCR (fast, 3-4s)
        return _ocr_easyocr(image_path, 'en')
    else:
        # Chinese / mixed → CnOCR (high quality, 10-11s)
        return _ocr_cnocr(image_path, lang)


def _detect_language(image_path: str) -> str:
    """Quick pre-scan with EasyOCR-mix."""
    reader = _get_easyocr('mix')
    result = reader.readtext(image_path, detail=0)
    text = ''.join(result)
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
    total = max(len(text.strip()), 1)
    ratio = cjk / total
    if ratio > 0.5:
        return 'ch_sim'
    elif ratio < 0.05:
        return 'en'
    return 'mix'


def _ocr_cnocr(image_path: str, lang: str) -> dict:
    """CnOCR for Chinese/mixed."""
    ocr = _get_cnocr()
    result = ocr.ocr(image_path)
    blocks = []
    for r in result:
        blocks.append({
            "text": r['text'].strip(),
            "score": _safe_score(r.get('score', 1.0)),
        })
    plain_text = '\n'.join(b['text'] for b in blocks if b['text'])
    return {
        "backend": "cnocr-onnx-cpu",
        "plain_text": plain_text,
        "blocks": blocks,
        "imageHeavy": False,
        "candidates": [],
        "recovered": _extract_recovered(plain_text),
        "warnings": [],
    }


def _ocr_easyocr(image_path: str, lang: str) -> dict:
    """EasyOCR for English."""
    reader = _get_easyocr(lang)
    result = reader.readtext(image_path, detail=1)
    blocks = []
    for detection in result:
        bbox, text, confidence = detection
        blocks.append({
            "text": text.strip(),
            "score": _safe_score(confidence),
            "box": [[int(p[0]), int(p[1])] for p in bbox],
        })
    plain_text = '\n'.join(b['text'] for b in blocks if b['text'])
    return {
        "backend": f"easyocr-gpu-{lang}",
        "plain_text": plain_text,
        "blocks": blocks,
        "imageHeavy": False,
        "candidates": [],
        "recovered": _extract_recovered(plain_text),
        "warnings": [],
    }


def _extract_recovered(text: str) -> dict:
    """Extract venue/lineup/date from OCR text."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    venue = ""
    for line in lines:
        if re.search(r'club|venue|room|space|live|house|bar|俱乐部|场地|现场|Live', line, re.I):
            venue = line
            break
    date_texts = [l for l in lines if re.search(r'\d{4}[-./年]\d{1,2}[-./月]\d{1,2}', l)]
    lineup = [l for l in lines if re.search(r'DJ|LIVE|ACT|VJ|B2B|演出|阵容|Lineup|Support', l, re.I)]
    return {
        "venue_name_candidate": venue,
        "date_texts": date_texts[:5],
        "lineup_lines": lineup[:10],
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"backend": "error", "plain_text": "", "blocks": [], "warnings": ["Usage: ocr_gpu.py <image_path>"]}))
        sys.exit(1)

    image_path = sys.argv[1]
    lang = None
    for arg in sys.argv[2:]:
        if arg in ('--cn', '--chinese'): lang = 'ch_sim'
        elif arg in ('--en', '--english'): lang = 'en'
        elif arg in ('--mix'): lang = 'mix'

    result = ocr_image(image_path, lang)
    print(json.dumps(result, ensure_ascii=False))
    print(f"[ocr_gpu] {os.path.basename(image_path)}: backend={result['backend']} lines={len(result['blocks'])}", file=sys.stderr)


if __name__ == "__main__":
    main()
