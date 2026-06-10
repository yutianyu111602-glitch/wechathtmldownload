"""Manifest builder — read audit results and prepare processing manifest."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from .paths import ensure_output_dirs
from .paths import article_output_dir
from .atomic_io import atomic_write_json
from .logging_setup import setup_logging


def _length_bucket(record: dict) -> str:
    chars = int(record.get("input_chars") or 0)
    if chars < 2_000:
        return "short"
    if chars < 8_000:
        return "medium"
    return "long"


def select_balanced_pending(pending: list[dict], limit: int) -> list[dict]:
    """Select pending records with account and length balance.

    This is a small max-flow over account quotas and length-bucket quotas. It
    prevents sorted audit manifests from producing canaries dominated by one
    account or one length class. If exact quotas are infeasible, it fills the
    remainder with the least imbalanced original-order records.
    """
    if limit <= 0 or not pending:
        return []

    bucket_order = ["short", "medium", "long"]
    pools: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    account_capacity: dict[str, int] = {}
    bucket_capacity: dict[str, int] = {}
    for idx, rec in enumerate(pending):
        account = str(rec.get("source_account") or "")
        bucket = _length_bucket(rec)
        pools.setdefault((account, bucket), []).append((idx, rec))
        account_capacity[account] = account_capacity.get(account, 0) + 1
        bucket_capacity[bucket] = bucket_capacity.get(bucket, 0) + 1

    accounts = sorted(account_capacity)
    buckets = [b for b in bucket_order if bucket_capacity.get(b, 0) > 0]

    def balanced_quotas(keys: list[str], total: int, capacities: dict[str, int]) -> dict[str, int]:
        quotas = {k: 0 for k in keys}
        for _ in range(total):
            eligible = [k for k in keys if quotas[k] < capacities.get(k, 0)]
            if not eligible:
                break
            chosen = min(eligible, key=lambda k: (quotas[k], keys.index(k)))
            quotas[chosen] += 1
        return quotas

    account_quota = balanced_quotas(accounts, min(limit, len(pending)), account_capacity)
    bucket_quota = balanced_quotas(buckets, min(limit, len(pending)), bucket_capacity)

    source = "__source__"
    sink = "__sink__"
    residual: dict[str, dict[str, int]] = {}

    def add_edge(u: str, v: str, cap: int) -> None:
        residual.setdefault(u, {})[v] = residual.setdefault(u, {}).get(v, 0) + cap
        residual.setdefault(v, {})[u] = residual.setdefault(v, {}).get(u, 0)

    for account, cap in account_quota.items():
        if cap > 0:
            add_edge(source, f"a:{account}", cap)
    for (account, bucket), rows in pools.items():
        add_edge(f"a:{account}", f"b:{bucket}", len(rows))
    for bucket, cap in bucket_quota.items():
        if cap > 0:
            add_edge(f"b:{bucket}", sink, cap)

    while True:
        queue = [source]
        parent: dict[str, str | None] = {source: None}
        for u in queue:
            for v, cap in residual.get(u, {}).items():
                if cap > 0 and v not in parent:
                    parent[v] = u
                    queue.append(v)
                    if v == sink:
                        break
            if sink in parent:
                break
        if sink not in parent:
            break
        v = sink
        path_cap = 10**9
        while parent[v] is not None:
            u = parent[v]
            path_cap = min(path_cap, residual[u][v])
            v = u
        v = sink
        while parent[v] is not None:
            u = parent[v]
            residual[u][v] -= path_cap
            residual[v][u] += path_cap
            v = u

    selected_pairs: list[tuple[int, dict]] = []
    for (account, bucket), rows in pools.items():
        flow = residual.get(f"b:{bucket}", {}).get(f"a:{account}", 0)
        if flow <= 0:
            continue
        selected_pairs.extend(rows[:flow])

    selected_ids = {id(rec) for _, rec in selected_pairs}
    account_counts: dict[str, int] = {}
    bucket_counts: dict[str, int] = {}
    for _, rec in selected_pairs:
        account = str(rec.get("source_account") or "")
        bucket = _length_bucket(rec)
        account_counts[account] = account_counts.get(account, 0) + 1
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    # Fill any infeasible-quota remainder without breaking ordering more than necessary.
    remaining = [(idx, rec) for idx, rec in enumerate(pending) if id(rec) not in selected_ids]
    while remaining and len(selected_pairs) < limit:
        def score(item: tuple[int, dict]) -> tuple[int, int, int, int]:
            idx, rec = item
            account = str(rec.get("source_account") or "")
            bucket = _length_bucket(rec)
            projected_accounts = {a: account_counts.get(a, 0) for a in accounts}
            projected_buckets = {b: bucket_counts.get(b, 0) for b in buckets}
            projected_accounts[account] = projected_accounts.get(account, 0) + 1
            projected_buckets[bucket] = projected_buckets.get(bucket, 0) + 1
            account_imbalance = max(projected_accounts.values()) - min(projected_accounts.values())
            bucket_imbalance = max(projected_buckets.values()) - min(projected_buckets.values())
            return (account_imbalance, bucket_imbalance, account_counts.get(account, 0) + bucket_counts.get(bucket, 0), idx)

        best = min(remaining, key=score)
        remaining.remove(best)
        _, rec = best
        selected_pairs.append(best)
        account = str(rec.get("source_account") or "")
        bucket = _length_bucket(rec)
        account_counts[account] = account_counts.get(account, 0) + 1
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    selected_pairs.sort(key=lambda item: item[0])
    return [rec for _, rec in selected_pairs[:limit]]


def build_manifest(output_root: Path, limit: int | None = None, mode: str = "canary") -> dict[str, Any]:
    """Build or rebuild the processing manifest from audit results."""
    logger = setup_logging(output_root / "logs", "manifest")
    ensure_output_dirs(output_root)

    manifest_path = output_root / "manifests" / "article_manifest.v1.jsonl"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}. Run audit first.")

    records: list[dict] = []
    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    logger.info("Loaded %d articles from manifest", len(records))

    # Filter: only articles with llm_input
    valid = [r for r in records if r.get("llm_input_path")]
    logger.info("Valid articles (have llm_input): %d", len(valid))

    # Filter: skip obviously bad
    good = []
    for r in valid:
        existing_extract = article_output_dir(
            output_root,
            str(r.get("source_account") or ""),
            str(r.get("article_id") or ""),
        ) / "extract.article.v1.json"
        if existing_extract.exists():
            r["status"] = "done"
            r["existing_extract_path"] = str(existing_extract)
            good.append(r)
            continue
        if r.get("oversized"):
            r["status"] = "skipped"
            r["skip_reason"] = "oversized"
            good.append(r)
            continue
        if not r.get("encoding_ok", True):
            r["status"] = "skipped"
            r["skip_reason"] = "encoding_error"
            good.append(r)
            continue
        if r.get("status") == "done":
            good.append(r)
            continue
        # Reset to pending if not already done/skipped/failed_final
        if r.get("status") not in ("done", "skipped", "failed_final"):
            r["status"] = "pending"
        good.append(r)

    # Apply limit using account + length balancing. Global audit order may be
    # account-sorted, so pending[:limit] can poison canary/ramp coverage.
    if limit is not None:
        pending = [r for r in good if r.get("status") == "pending"]
        selected = select_balanced_pending(pending, limit)
        selected_ids = {id(r) for r in selected}
        for r in selected:
            r["status"] = "pending"
        for r in pending:
            if id(r) not in selected_ids:
                r["status"] = "pending_deferred"
        final = selected + [r for r in good if id(r) not in selected_ids and r.get("status") != "pending_deferred"]
    else:
        final = good

    # Write processing manifest
    proc_manifest = output_root / "manifests" / f"processing_manifest.{mode}.jsonl"
    with open(proc_manifest, "w", encoding="utf-8") as f:
        for r in final:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    stats = {
        "mode": mode,
        "total": len(final),
        "pending": sum(1 for r in final if r.get("status") == "pending"),
        "done": sum(1 for r in final if r.get("status") == "done"),
        "skipped": sum(1 for r in final if r.get("status") in ("skipped", "pending_deferred")),
        "failed_final": sum(1 for r in final if r.get("status") == "failed_final"),
        "processing_manifest": str(proc_manifest),
    }

    atomic_write_json(output_root / "manifests" / f"manifest_stats.{mode}.json", stats)
    logger.info("Manifest built: %s", stats)
    return stats
