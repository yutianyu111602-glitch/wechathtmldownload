"""LLM worker: process a single article through chunk → extract → validate → save."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Optional

from .config import Config
from .llm_client import LlmClient
from .chunker import chunk_article
from .json_repair import parse_and_repair_json
from .validators import validate_extract, check_evidence_quotes
from .schema_normalize import normalize_extract_schema, is_legal_empty
from .sqlite_state import SQLiteState
from .paths import article_output_dir
from .atomic_io import atomic_write_json, atomic_write_text
from .logging_setup import setup_logging


def _first_text(meta: dict, *keys: str) -> str:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _clean_prompt_account(source_account: str) -> str:
    value = str(source_account or "").strip()
    if "__" in value:
        suffix = value.split("__", 1)[1].strip()
        if suffix:
            return suffix
    return value


def _build_prompt_header(source_account: str, meta: dict) -> str:
    title = _first_text(meta, "title")
    account = _first_text(meta, "account_name", "account", "nickname", "source_account")
    publish_time = _first_text(meta, "publishTime", "publish_time_text", "publish_time_iso")
    url = _first_text(meta, "url", "source_url")
    if account:
        account = _clean_prompt_account(account)
    else:
        account = _clean_prompt_account(source_account)
    return (
        f"文章标题: {title}\n"
        f"公众号: {account}\n"
        f"发布时间: {publish_time}\n"
        f"URL: {url}\n"
    )


class LlmWorker:
    def __init__(self, config: Config, state: SQLiteState, logger=None, allow_empty_recovery: bool = False):
        self.config = config
        self.state = state
        self.logger = logger or setup_logging(config.output_root / "logs", "llm_worker")
        self.llm = LlmClient(config.llm, self.logger)
        configured_prompt_path = getattr(config.llm, "prompt_path", "")
        if configured_prompt_path:
            prompt_path = Path(configured_prompt_path)
            if not prompt_path.is_absolute():
                prompt_path = Path(__file__).parent.parent / prompt_path
            self.prompt_path = prompt_path
        else:
            self.prompt_path = Path(__file__).parent.parent / "config" / "prompt.extract.v4.zh.txt"
        self.system_prompt = self._load_prompt()
        self.allow_empty_recovery = allow_empty_recovery

    def _load_prompt(self) -> str:
        if self.prompt_path.exists():
            with open(self.prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        self.logger.error("Prompt file not found: %s", self.prompt_path)
        return ""

    def process_article(self, record: dict, mode: str = "canary") -> dict:
        """Process one article. Returns result summary."""
        article_uid = record["article_uid"]
        source_account = record["source_account"]
        article_id = record["article_id"]
        llm_input_path = record.get("llm_input_path", "")
        meta_path = record.get("meta_path", "")

        self.logger.info("Processing %s / %s", source_account, article_id)

        # Update state to running
        self.state.upsert_article({
            "article_uid": article_uid,
            "source_account": source_account,
            "article_id": article_id,
            "status": "running",
            "mode": mode,
            "started_at": __import__("datetime").datetime.now().isoformat(),
            "llm_input_path": llm_input_path,
            "output_dir": str(article_output_dir(self.config.output_root, source_account, article_id)),
        })

        out_dir = article_output_dir(self.config.output_root, source_account, article_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Read input
        try:
            with open(llm_input_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            self.logger.error("Failed to read %s: %s", llm_input_path, e)
            self._fail(article_uid, source_account, article_id, "input_read_error", str(e), mode)
            return self._result(article_uid, "failed_final", error_type="input_read_error")

        # Read meta
        meta = {}
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

        article_prompt_header = _build_prompt_header(source_account, meta)
        article_evidence_text = f"{article_prompt_header}\n---\n{text}"

        # Chunk
        chunk_plan = chunk_article(
            article_uid, text,
            target_chars=self.config.chunking.target_chars,
            max_chars=self.config.chunking.max_chars,
            min_chars=self.config.chunking.min_chars,
        )

        # Save chunk plan
        atomic_write_json(out_dir / "chunks.plan.json", {
            "article_uid": article_uid,
            "chunk_count": chunk_plan.chunk_count,
            "strategy": chunk_plan.strategy,
            "chunks": [{"chunk_id": c.chunk_id, "chunk_index": c.chunk_index, "chars": c.chars, "text_sha1": c.text_sha1} for c in chunk_plan.chunks],
        })

        if chunk_plan.chunk_count == 0:
            self.logger.warning("Empty text for %s", article_uid)
            self._fail(article_uid, source_account, article_id, "empty_text", "No text to process", mode)
            return self._result(article_uid, "failed_final", error_type="empty_text")

        # Process chunks
        chunk_results = []
        all_entities = []
        all_events = []
        all_relations = []
        all_claims = []
        all_topics = []
        all_keywords = []
        failed_chunks = 0
        parse_repaired_count = 0
        schema_normalized_count = 0
        schema_invalid_count = 0
        sanitize_totals: dict[str, int] = {}

        for chunk in chunk_plan.chunks:
            # Build user prompt with meta context
            user_content = f"{article_prompt_header}\n---\nchunk_id: {chunk.chunk_id}\n\n{chunk.text}"

            # Call LLM
            llm_result = self.llm.chat_completion(self.system_prompt, user_content)

            if not llm_result["ok"]:
                self.logger.warning("LLM failed for chunk %s: %s", chunk.chunk_id, llm_result.get("error_type"))
                failed_chunks += 1
                chunk_results.append({
                    "chunk_id": chunk.chunk_id,
                    "status": "llm_failed",
                    "error_type": llm_result.get("error_type"),
                    "error_message": llm_result.get("error_message"),
                })
                continue

            raw_text = llm_result["content"]
            # Save raw
            raw_path = out_dir / f"chunk.{chunk.chunk_index:03d}.raw.txt"
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(raw_text)

            # Parse + repair (with LLM repair callback)
            repair_result = parse_and_repair_json(raw_text, repair_prompt_callback=self._llm_repair)

            chunk_results.append({
                "chunk_id": chunk.chunk_id,
                "status": "parsed" if repair_result.ok else "parse_failed",
                "parse_attempts": repair_result.parse_attempts,
                "used_repair": repair_result.used_repair,
                "error_type": repair_result.error_type,
            })

            if not repair_result.ok:
                self.logger.warning("Parse failed for chunk %s: %s", chunk.chunk_id, repair_result.error_message)
                # Save bad sample
                bad_path = out_dir / f"chunk.{chunk.chunk_index:03d}.error.json"
                import json as _json
                with open(bad_path, "w", encoding="utf-8") as f:
                    _json.dump({
                        "chunk_id": chunk.chunk_id,
                        "error_type": repair_result.error_type,
                        "error_message": repair_result.error_message,
                        "parse_attempts": repair_result.parse_attempts,
                        "raw_path": str(raw_path),
                    }, f, ensure_ascii=False, indent=2)
                failed_chunks += 1
                continue

            parsed = repair_result.value
            if not isinstance(parsed, dict):
                self.logger.warning("Parsed value is not dict for chunk %s", chunk.chunk_id)
                failed_chunks += 1
                continue

            if repair_result.used_repair:
                parse_repaired_count += 1

            # Normalize schema: fill missing empty container fields
            normalized, norm_stats = normalize_extract_schema(parsed)
            if norm_stats["normalized"]:
                schema_normalized_count += 1
                self.logger.info("Schema normalized for chunk %s: missing=%s", chunk.chunk_id, norm_stats["missing_fields"])

            # Sanitize: limit output size and truncate long text
            from .sanitize import sanitize_extract_limits
            sanitized, sanitize_stats = sanitize_extract_limits(normalized, source_text=user_content)
            if any(v > 0 for v in sanitize_stats.values()):
                self.logger.info("Sanitized chunk %s: %s", chunk.chunk_id, {k: v for k, v in sanitize_stats.items() if v > 0})
                if chunk_results:
                    chunk_results[-1]["sanitize_stats"] = {k: v for k, v in sanitize_stats.items() if v > 0}
                for key, value in sanitize_stats.items():
                    if isinstance(value, int) and value > 0:
                        sanitize_totals[key] = sanitize_totals.get(key, 0) + value

            # Validate schema on sanitized data
            val = validate_extract(sanitized, source_text=user_content)
            if not val["ok"]:
                schema_invalid_count += 1
                self.logger.warning("Schema invalid for chunk %s: %s", chunk.chunk_id, val["errors"])
                if chunk_results:
                    chunk_results[-1]["status"] = "schema_invalid"
                    chunk_results[-1]["validation_errors"] = val["errors"]
                failed_chunks += 1
                continue

            data = val["data"]
            # Merge
            all_entities.extend(data.get("entities", []))
            all_events.extend(data.get("events", []))
            all_relations.extend(data.get("relations", []))
            all_claims.extend(data.get("claims", []))
            for t in data.get("topics", []):
                if t not in all_topics:
                    all_topics.append(t)
            for k in data.get("keywords", []):
                if k not in all_keywords:
                    all_keywords.append(k)

        # Article-level sanitize: dedupe + limit after multi-chunk aggregation
        combined_text = article_evidence_text
        article_raw = {
            "entities": all_entities,
            "events": all_events,
            "relations": all_relations,
            "claims": all_claims,
            "topics": [],
            "keywords": [],
        }
        from .sanitize import sanitize_article_level
        article_sanitized, article_sanitize_stats = sanitize_article_level(article_raw, source_text=combined_text)
        all_entities = article_sanitized.get("entities", [])
        all_events = article_sanitized.get("events", [])
        all_relations = article_sanitized.get("relations", [])
        all_claims = article_sanitized.get("claims", [])
        article_topics = article_sanitized.get("topics", [])
        article_keywords = article_sanitized.get("keywords", [])
        # Track article-level sanitize stats
        article_entities_truncated = article_sanitize_stats.get("article_entities_truncated_count", 0)
        article_events_truncated = article_sanitize_stats.get("article_events_truncated_count", 0)
        article_relations_truncated = article_sanitize_stats.get("article_relations_truncated_count", 0)
        article_claims_truncated = article_sanitize_stats.get("article_claims_truncated_count", 0)
        entities_deduped = article_sanitize_stats.get("entities_deduped_count", 0)

        all_failed = failed_chunks == chunk_plan.chunk_count
        empty_recovery_blocked = False
        empty_recovery_used = False

        if all_failed:
            self.logger.error("All chunks failed for %s", article_uid)
            if self.allow_empty_recovery:
                self.logger.warning("Allowing empty recovery for %s (allow_empty_recovery=true)", article_uid)
                empty_recovery_used = True
            else:
                empty_recovery_blocked = True
                self.logger.warning("Empty recovery BLOCKED for %s (allow_empty_recovery=false) -> failed_final", article_uid)
                self._fail(article_uid, source_account, article_id, "all_chunks_failed", f"All {failed_chunks} chunks failed parsing", mode)
                return self._result(article_uid, "failed_final", error_type="all_chunks_failed",
                                    empty_recovery_blocked=True)

        if failed_chunks > self.config.quality.max_failed_chunks_per_article and not all_failed:
            self.logger.error("Too many failed chunks (%d) for %s", failed_chunks, article_uid)
            self._fail(article_uid, source_account, article_id, "too_many_failed_chunks", f"{failed_chunks} chunks failed", mode)
            return self._result(article_uid, "failed_retryable", error_type="too_many_failed_chunks")

        evidence_pruned_count = sanitize_totals.get("evidence_non_exact_dropped_count", 0)
        title_pseudoquote_pruned_count = sanitize_totals.get("title_pseudoquote_dropped_count", 0)
        has_warnings = (
            failed_chunks > 0
            or empty_recovery_used
            or parse_repaired_count > 0
            or schema_normalized_count > 0
            or evidence_pruned_count > 0
            or title_pseudoquote_pruned_count > 0
        )
        quality_verdict = "WARN" if has_warnings else "PASS"
        if empty_recovery_used:
            quality_verdict = "FAIL_RETRYABLE"
            status = "done_with_warnings"
        elif has_warnings:
            status = "done_with_warnings"
        else:
            status = "done"

        # Build article-level result
        result = {
            "schema_version": "article_extract.v1",
            "article_uid": article_uid,
            "source_account": source_account,
            "article_id": article_id,
            "title": _first_text(meta, "title"),
            "publish_time": _first_text(meta, "publishTime", "publish_time_text", "publish_time_iso"),
            "url": _first_text(meta, "url", "source_url"),
            "language": "zh",
            "summary": "",  # Will be filled from first chunk if available
            "topics": article_topics,
            "keywords": article_keywords,
            "entities": all_entities,
            "events": all_events,
            "relations": all_relations,
            "claims": all_claims,
            "quality": {
                "json_valid": True,
                "schema_valid": True,
                "entity_count": len(all_entities),
                "event_count": len(all_events),
                "relation_count": len(all_relations),
                "claim_count": len(all_claims),
                "topic_count": len(article_topics),
                "keyword_count": len(article_keywords),
                "warnings": [],
                "verdict": quality_verdict,
                "failed_chunks": failed_chunks,
                "parse_failed_recovered_empty": empty_recovery_used,
                "empty_recovery_blocked": empty_recovery_blocked,
                "empty_recovery_used": empty_recovery_used,
                "all_chunks_failed": all_failed,
                "context_exceeded_count": sum(1 for c in chunk_results if c.get("error_type") == "context_exceeded"),
                "repair_used": sum(1 for c in chunk_results if c.get("used_repair")),
                "retry_used": sum(1 for c in chunk_results if c.get("parse_attempts", 0) > 1),
                "parse_repaired_count": parse_repaired_count,
                "schema_normalized_count": schema_normalized_count,
                "schema_invalid_count": schema_invalid_count,
                "sanitize_stats": sanitize_totals,
                "evidence_non_exact_dropped_count": evidence_pruned_count,
                "title_pseudoquote_dropped_count": title_pseudoquote_pruned_count,
                "items_dropped_after_evidence_prune_count": sanitize_totals.get("items_dropped_after_evidence_prune_count", 0),
                "entities_deduped_count": entities_deduped,
                "article_entities_truncated_count": article_entities_truncated,
                "article_events_truncated_count": article_events_truncated,
                "article_relations_truncated_count": article_relations_truncated,
                "article_claims_truncated_count": article_claims_truncated,
            },
            "chunk_results": chunk_results,
        }

        # Evidence gate
        evidence_check = check_evidence_quotes(article_evidence_text, result)
        result["quality"]["evidence_hit_rate"] = evidence_check["evidence_hit_rate"]
        result["quality"]["evidence_warnings"] = evidence_check["warnings"]

        # Save extract
        atomic_write_json(out_dir / "extract.article.v1.json", result)

        # Save status
        atomic_write_json(out_dir / "status.json", {
            "article_uid": article_uid,
            "status": status,
            "mode": mode,
            "chunk_count": chunk_plan.chunk_count,
            "failed_chunks": failed_chunks,
            "entity_count": len(all_entities),
            "event_count": len(all_events),
            "relation_count": len(all_relations),
            "claim_count": len(all_claims),
            "evidence_hit_rate": evidence_check["evidence_hit_rate"],
            "quality_verdict": quality_verdict,
            "finished_at": __import__("datetime").datetime.now().isoformat(),
        })

        # Update DB
        self.state.upsert_article({
            "article_uid": article_uid,
            "source_account": source_account,
            "article_id": article_id,
            "status": status,
            "mode": mode,
            "finished_at": __import__("datetime").datetime.now().isoformat(),
            "output_dir": str(out_dir),
            "json_valid": 1,
            "schema_valid": 1,
            "entity_count": len(all_entities),
            "event_count": len(all_events),
            "relation_count": len(all_relations),
            "claim_count": len(all_claims),
            "quality_verdict": quality_verdict,
        })

        self.logger.info("Done %s (status=%s, verdict=%s): entities=%d events=%d relations=%d claims=%d",
                         article_uid, status, quality_verdict, len(all_entities), len(all_events), len(all_relations), len(all_claims))

        return self._result(article_uid, status, entity_count=len(all_entities), event_count=len(all_events),
                           relation_count=len(all_relations), claim_count=len(all_claims),
                            evidence_hit_rate=evidence_check["evidence_hit_rate"],
                            quality_verdict=quality_verdict)

    def _llm_repair(self, bad_json_text: str) -> str:
        """Use LLM to repair broken JSON. Called as last resort by parse_and_repair_json."""
        repair_prompt_path = Path(__file__).parent.parent / "prompts" / "stage7_repair_json_v1.zh.txt"
        if repair_prompt_path.exists():
            repair_system = repair_prompt_path.read_text(encoding="utf-8")
        else:
            repair_system = (
                "你是 JSON 修复器。只允许修复语法错误。禁止新增事实。"
                "只输出修复后的 JSON 对象。不要输出解释。"
            )
        user_content = bad_json_text[:8000]  # Truncate very long bad JSON
        result = self.llm.chat_completion(repair_system, user_content)
        if result.get("ok"):
            return result["content"]
        raise ValueError(f"LLM repair failed: {result.get('error_type')}")

    def _fail(self, article_uid: str, source_account: str, article_id: str, error_type: str, error_message: str, mode: str) -> None:
        self.state.upsert_article({
            "article_uid": article_uid,
            "source_account": source_account,
            "article_id": article_id,
            "status": "failed_retryable",
            "mode": mode,
            "last_error_type": error_type,
            "last_error_message": error_message,
            "finished_at": __import__("datetime").datetime.now().isoformat(),
        })

    def _result(self, article_uid: str, status: str, error_type: str = "", entity_count: int = 0,
                event_count: int = 0, relation_count: int = 0, claim_count: int = 0,
                evidence_hit_rate: float = 0.0, quality_verdict: str = "",
                empty_recovery_blocked: bool = False) -> dict:
        return {
            "article_uid": article_uid,
            "status": status,
            "error_type": error_type,
            "json_valid": status in ("done", "done_with_warnings"),
            "schema_valid": status in ("done", "done_with_warnings"),
            "entity_count": entity_count,
            "event_count": event_count,
            "relation_count": relation_count,
            "claim_count": claim_count,
            "evidence_hit_rate": evidence_hit_rate,
            "quality_verdict": quality_verdict,
            "empty_recovery_blocked": empty_recovery_blocked,
        }

    def close(self) -> None:
        self.llm.close()
