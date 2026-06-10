#!/usr/bin/env python3
"""Audit local Rust Club image evidence for address clues.

Report-only. This script uses existing local image artifacts only. It does not
fetch media, call map providers, read secrets, write coordinates, mutate data,
deploy, upload, or scan broad disks.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DETAIL = (
    REPO_ROOT
    / "services"
    / "weekly_activity_cloudrun"
    / "data"
    / "current_release"
    / "by-id"
    / "rust_clubu3a74c857fda5f80128.json"
)
DEFAULT_IMAGE_DIR = (
    REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "rust_club_image_probe_20260531"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_rust_club_local_image_evidence_s38_20260531"
)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
STREET_MARKER_RE = re.compile(r"[\u8def\u8857\u9053\u53f7\u680b\u5c42\u697c\u5df7]")
ADMIN_MARKER_RE = re.compile(r"[\u7701\u5e02\u533a\u53bf\u9547\u6751]")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def flatten_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(flatten_text(item))
        return out
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(flatten_text(item))
        return out
    text = str(value).strip()
    return [text] if text else []


def looks_like_street_address(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 6:
        return False
    return bool(STREET_MARKER_RE.search(compact) and ADMIN_MARKER_RE.search(compact))


def is_actionable_qr_url(url: str) -> bool:
    value = url.strip().lower()
    if not value:
        return False
    if "weixin.qq.com/r/mp/" in value:
        return False
    map_markers = ("map.qq.com", "apis.map.qq.com", "amap.com", "uri.amap.com", "map.baidu.com")
    address_markers = ("%e5%9c%b0%e5%9d%80", "address", "addr=", "loc=", "location=")
    return any(marker in value for marker in map_markers) or any(marker in value for marker in address_markers)


def local_image_files(image_dir: Path) -> list[Path]:
    if not image_dir.exists():
        return []
    return sorted(path for path in image_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)


def decode_qr_urls(image_path: Path) -> list[str]:
    if "rust_2" not in image_path.name and "qr" not in image_path.name.lower():
        return []
    try:
        import cv2  # type: ignore
    except Exception:
        return []

    img = cv2.imread(str(image_path))
    if img is None:
        return []

    detector = cv2.QRCodeDetector()
    h, w = img.shape[:2]
    crops = [img]
    if w >= 200 and h >= 200:
        crops.append(img[int(h * 0.82) : h, int(w * 0.72) : w])
        crops.append(img[int(h * 0.78) : h, int(w * 0.68) : w])

    found: list[str] = []
    for crop in crops:
        variants = [crop]
        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            variants.append(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
            _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            variants.append(cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR))
            adaptive = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5
            )
            variants.append(cv2.cvtColor(adaptive, cv2.COLOR_GRAY2BGR))
        except Exception:
            pass

        for scale in (1, 2, 4, 6):
            for variant in variants:
                if scale > 1 and variant.shape[0] > 500:
                    continue
                try:
                    interp = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_LINEAR
                    resized = cv2.resize(variant, None, fx=scale, fy=scale, interpolation=interp)
                    data, _points, _straight = detector.detectAndDecode(resized)
                except Exception:
                    continue
                if data and data not in found:
                    found.append(data)
    return found


def ocr_text(image_path: Path) -> str:
    if "rust_2" not in image_path.name and "qr" not in image_path.name.lower():
        return ""
    try:
        from PIL import Image
        import pytesseract  # type: ignore
    except Exception:
        return ""
    try:
        return pytesseract.image_to_string(Image.open(image_path), lang="chi_sim+eng").strip()
    except Exception:
        return ""


def build_audit(detail_path: Path, image_dir: Path, *, run_ocr: bool = True) -> dict[str, Any]:
    detail = read_json(detail_path)
    item = detail.get("item") if isinstance(detail.get("item"), dict) else detail

    local_texts = flatten_text(
        [
            item.get("title"),
            item.get("title_original"),
            item.get("title_display"),
            item.get("description_text"),
            item.get("description_original_lines"),
            item.get("evidence"),
            item.get("address"),
            item.get("address_full"),
        ]
    )
    image_observations = []
    qr_urls: list[str] = []
    ocr_texts: list[str] = []
    for image_path in local_image_files(image_dir):
        urls = decode_qr_urls(image_path)
        qr_urls.extend(url for url in urls if url not in qr_urls)
        text = ocr_text(image_path) if run_ocr else ""
        if text:
            ocr_texts.append(text)
        image_observations.append(
            {
                "path": str(image_path),
                "qr_urls": urls,
                "ocr_text": text,
            }
        )

    street_candidates = [
        text
        for text in [*local_texts, *ocr_texts, *qr_urls]
        if looks_like_street_address(text) or is_actionable_qr_url(text)
    ]
    actionable_qr_urls = [url for url in qr_urls if is_actionable_qr_url(url)]
    non_actionable_qr_urls = [url for url in qr_urls if not is_actionable_qr_url(url)]

    safe_to_promote = bool(street_candidates and actionable_qr_urls)
    blockers = []
    if not street_candidates:
        blockers.append(
            {
                "code": "local_image_text_no_street_address",
                "detail": "local text/OCR/QR evidence has no street-level address candidate",
            }
        )
    if non_actionable_qr_urls and not actionable_qr_urls:
        blockers.append(
            {
                "code": "qr_url_not_address_or_map",
                "detail": "decoded QR URL is not a map/address URL",
            }
        )

    return {
        "schema_version": "rust_club_local_image_evidence_audit.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": (
            "rust_club_local_image_evidence_has_address_candidate"
            if safe_to_promote
            else "rust_club_local_image_evidence_no_address"
        ),
        "safe_to_promote_address_candidate": safe_to_promote,
        "candidate": {
            "event_id": item.get("id", ""),
            "venue_id": item.get("venue_id", ""),
            "venue_name": item.get("venue_name", ""),
            "city": item.get("city_name") or item.get("city") or "",
        },
        "image_dir": str(image_dir),
        "image_count": len(image_observations),
        "qr_urls": qr_urls,
        "actionable_qr_urls": actionable_qr_urls,
        "street_address_candidates": street_candidates,
        "blockers": blockers,
        "image_observations": image_observations,
        "boundary": {
            "remote_media_fetch": False,
            "provider_call": False,
            "secret_read": False,
            "address_or_coordinate_write": False,
            "deploy_or_upload": False,
            "db_graph_vector_mutation": False,
            "broad_disk_scan": False,
        },
    }


def write_markdown(audit: dict[str, Any], path: Path) -> None:
    lines = [
        "# Rust Club Local Image Evidence Audit",
        "",
        f"- Decision: `{audit['decision']}`",
        f"- Safe to promote address candidate: `{str(audit['safe_to_promote_address_candidate']).lower()}`",
        f"- Image count: `{audit['image_count']}`",
        f"- QR URLs: `{len(audit['qr_urls'])}`",
        f"- Street/address candidates: `{len(audit['street_address_candidates'])}`",
        "",
        "## QR URLs",
        "",
    ]
    if audit["qr_urls"]:
        lines.extend(f"- `{url}`" for url in audit["qr_urls"])
    else:
        lines.append("- none")
    lines.extend(["", "## Blockers", ""])
    if audit["blockers"]:
        lines.extend(f"- `{row['code']}`: {row['detail']}" for row in audit["blockers"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Local image evidence audit only. No remote media fetch, provider call, secret read, address/coordinate write, deploy/upload, DB/graph/vector mutation, or broad disk scan.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detail", type=Path, default=DEFAULT_DETAIL)
    parser.add_argument("--image-dir", type=Path, default=DEFAULT_IMAGE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--no-ocr", action="store_true")
    args = parser.parse_args()

    detail_path = repo_path(args.detail)
    image_dir = repo_path(args.image_dir)
    out_dir = repo_path(args.out_dir)
    audit = build_audit(detail_path, image_dir, run_ocr=not args.no_ocr)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "rust_club_local_image_evidence_audit.json"
    md_path = out_dir / "rust_club_local_image_evidence_audit.md"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(audit, md_path)
    print(
        json.dumps(
            {
                "decision": audit["decision"],
                "safe_to_promote_address_candidate": audit["safe_to_promote_address_candidate"],
                "image_count": audit["image_count"],
                "qr_urls": len(audit["qr_urls"]),
                "street_address_candidates": len(audit["street_address_candidates"]),
                "json": str(json_path.relative_to(REPO_ROOT)),
                "markdown": str(md_path.relative_to(REPO_ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
