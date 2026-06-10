#!/usr/bin/env python3
"""
LDR-style deep research on the weekly/Atlas upgrade plan.
Architecture: decompose -> search (SearXNG) -> synthesize (DeepSeek v4 Pro) -> iterate.

Reads the plan document, decomposes key claims into research questions,
validates against web search results, and produces a structured critique.

Usage:
  python deep_research_plan.py --plan <plan.md> [--rounds 2]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEEPSEEK_BASE = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-pro"
SEARXNG_BASE = os.environ.get("SEARXNG_URL", "http://127.0.0.1:18080")
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


# ── DeepSeek API ───────────────────────────────────────────────────

def deepseek_chat(messages: list[dict], *, max_tokens: int = 4096, temperature: float = 0.0) -> dict:
    """Call DeepSeek v4 Pro, return parsed JSON response."""
    if not API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set")

    body = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "thinking": {"type": "disabled"},
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "stream": False,
    }).encode("utf-8")

    req = Request(
        f"{DEEPSEEK_BASE}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    resp = urlopen(req, timeout=120)
    payload = json.loads(resp.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    return json.loads(content)


# ── SearXNG Search ─────────────────────────────────────────────────

def searxng_search(query: str, max_results: int = 8) -> list[dict]:
    """Search SearXNG and return results."""
    params = urlencode({"q": query, "format": "json", "engines": "bing", "language": "en"})
    url = f"{SEARXNG_BASE}/search?{params}"
    req = Request(url, headers={"User-Agent": "ldr-deep-research/1.0"})
    try:
        resp = urlopen(req, timeout=15)
        data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results", [])[:max_results]
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": (r.get("content") or r.get("snippet", ""))[:300]}
            for r in results
        ]
    except Exception as exc:
        print(f"  [WARN] SearXNG error: {exc}", file=sys.stderr)
        return []


# ── Research Loop ──────────────────────────────────────────────────

RESEARCH_QUESTIONS = [
    {
        "id": "R1",
        "field": "field_evidence_refs",
        "question": "What are best practices for LLM-extracted field-level evidence references and provenance tracking? How do production systems like Wikipedia citation templates or fact-checking pipelines implement per-field source attribution?",
        "search_queries": [
            "LLM field-level evidence references provenance JSON schema",
            "fact checking pipeline per-field source attribution design",
            "structured data extraction evidence provenance tracking",
        ],
    },
    {
        "id": "R2",
        "field": "ocr_llm_provenance",
        "question": "For image-heavy document extraction, what are the established patterns for OCR-to-LLM provenance gates? How do production systems ensure OCR text survives into LLM input without loss?",
        "search_queries": [
            "OCR LLM provenance gate image-heavy documents",
            "RAG document extraction OCR text LLM input pipeline",
        ],
    },
    {
        "id": "R3",
        "field": "confidence_scoring",
        "question": "What confidence scoring decomposition approaches are used in multi-source data integration? How do systems combine source_support, ocr_support, llm_consistency, and external_kb_support into a single confidence metric?",
        "search_queries": [
            "multi-source data fusion confidence decomposition weighted scoring",
            "knowledge base entity resolution confidence scoring model",
        ],
    },
    {
        "id": "R4",
        "field": "bio_policy",
        "question": "In NLP pipelines for event extraction, how is artist/speaker bio handled? What are the established conservative policies for distinguishing event-specific intro from long-term profile bio?",
        "search_queries": [
            "event extraction LLM speaker bio provenance policy",
            "conservative entity profile bio NLP pipeline design",
        ],
    },
    {
        "id": "R5",
        "field": "entity_resolution",
        "question": "For fuzzy entity resolution with knowledge graph cross-reference, what display policies (show/hint/hide) are used in production systems? How do Wikidata, Google Knowledge Graph, or similar systems handle uncertain entity matches?",
        "search_queries": [
            "entity resolution display policy show hint hide fuzzy match",
            "knowledge graph entity linking confidence tier display",
        ],
    },
    {
        "id": "R6",
        "field": "description_policy",
        "question": "For event description extraction from social media posts, what are the best practices for distinguishing original-source lines from LLM-generated summaries? How to prevent marketing-rewrite in description fields?",
        "search_queries": [
            "event description extraction original source lines LLM policy",
            "NLP information extraction prevent hallucination description generation",
        ],
    },
]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def load_plan(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def research_round(questions: list[dict], round_idx: int, prior_findings: str = "") -> list[dict]:
    """One research round: search each question, synthesize findings."""
    findings = []
    for q in questions:
        print(f"\n{'='*60}")
        print(f"[R{round_idx}] Researching: {q['field']}")
        print(f"Q: {q['question'][:120]}...")

        all_results = []
        for sq in q["search_queries"]:
            print(f"  Search: {sq[:80]}...")
            results = searxng_search(sq)
            all_results.extend(results)
            time.sleep(0.3)

        if not all_results:
            print("  [WARN] No search results, synthesizing from prior knowledge only")
            all_results = [{"title": "no_results", "url": "", "snippet": "Search engine unavailable"}]

        search_context = "\n\n".join(
            f"[{i+1}] {r['title']}\n{r['snippet']}\n{r['url']}"
            for i, r in enumerate(all_results[:6])
        )

        prior_context = f"\n\n## Prior Round Findings\n{prior_findings}" if prior_findings else ""

        system_prompt = (
            "You are a research analyst critiquing a software architecture plan for a WeChat mini-program "
            "event extraction pipeline that uses OCR, LLM (DeepSeek), and a knowledge graph (Atlas) for "
            "Chinese underground electronic music events."
            "\n\n"
            "Output valid JSON with these fields: "
            '"field", "research_question", "key_findings" (list of 3-5 bullet points), '
            '"gaps_in_plan" (what the plan missed), '
            '"recommendations" (3-5 specific actionable improvements), '
            '"confidence" (0.0-1.0 how well the question was answered), '
            '"sources_used" (list of URLs).'
        )

        user_prompt = (
            f"Research Question: {q['question']}\n\n"
            f"Web Search Results:\n{search_context}\n"
            f"{prior_context}\n\n"
            "Based on the search results and your knowledge, analyze what the plan document "
            "gets right and what it misses. Be specific and actionable."
        )

        try:
            result = deepseek_chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ], max_tokens=4096)

            finding = {
                "field": q["field"],
                "research_question": q["question"],
                "key_findings": result.get("key_findings", []),
                "gaps_in_plan": result.get("gaps_in_plan", []),
                "recommendations": result.get("recommendations", []),
                "confidence": result.get("confidence", 0.5),
                "sources_used": result.get("sources_used", []),
                "round": round_idx,
            }
        except Exception as exc:
            print(f"  [ERROR] DeepSeek call failed: {exc}", file=sys.stderr)
            finding = {
                "field": q["field"],
                "research_question": q["question"],
                "key_findings": [f"DeepSeek API error: {exc}"],
                "gaps_in_plan": [],
                "recommendations": [],
                "confidence": 0.0,
                "sources_used": [],
                "round": round_idx,
            }

        findings.append(finding)
        print(f"  Confidence: {finding['confidence']:.2f} | Findings: {len(finding.get('key_findings', []))} | Gaps: {len(finding.get('gaps_in_plan', []))}")

    return findings


def synthesize_critique(plan_text: str, all_findings: list[dict]) -> dict:
    """Final synthesis: produce a structured critique of the plan."""
    findings_text = json.dumps(all_findings, ensure_ascii=False, indent=2)

    system_prompt = (
        "You are a senior software architect reviewing a comprehensive upgrade plan for "
        "a WeChat mini-program event extraction pipeline. Output valid JSON."
    )

    user_prompt = (
        "You have a plan document and deep research findings. Produce a structured critique "
        "in JSON format with these fields:\n\n"
        "1. overall_assessment: 2-3 sentences on plan quality\n"
        "2. strengths: list of 5-8 things the plan does well\n"
        "3. critical_gaps: list of 5-8 missing pieces or weaknesses\n"
        "4. priority_improvements: ranked list of 5 improvements with urgency (P0/P1/P2) and effort (S/M/L)\n"
        "5. external_references: techniques/tools/papers the plan should reference\n"
        "6. risk_reassessment: any risks the plan underestimated or missed\n"
        "7. next_actions: concrete next 3 actions to improve the plan before implementation\n\n"
        f"## Research Findings\n{findings_text[:8000]}\n\n"
        f"## Plan Document (first 6000 chars)\n{plan_text[:6000]}"
    )

    try:
        critique = deepseek_chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], max_tokens=8192, temperature=0.0)
    except Exception as exc:
        return {"error": str(exc), "overall_assessment": "DeepSeek API failed"}

    critique["researched_at"] = datetime.now(timezone.utc).isoformat()
    critique["model"] = DEEPSEEK_MODEL
    critique["research_questions"] = len(RESEARCH_QUESTIONS)
    critique["total_findings"] = len(all_findings)
    return critique


def main():
    parser = argparse.ArgumentParser(description="LDR-style deep research on plan document")
    parser.add_argument("--plan", required=True, help="Path to plan markdown file")
    parser.add_argument("--rounds", type=int, default=1, help="Research rounds (1-3)")
    parser.add_argument("--output", help="Output JSON path")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: DEEPSEEK_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    plan_text = load_plan(args.plan)
    print(f"Loaded plan: {len(plan_text)} chars")
    print(f"Research questions: {len(RESEARCH_QUESTIONS)}")
    print(f"Rounds: {args.rounds}")
    print(f"Model: {DEEPSEEK_MODEL}")
    print(f"SearXNG: {SEARXNG_BASE}")

    all_findings = []
    prior = ""
    for r in range(args.rounds):
        print(f"\n{'#'*60}")
        print(f"### ROUND {r+1}/{args.rounds}")
        print(f"{'#'*60}")
        round_findings = research_round(RESEARCH_QUESTIONS, r + 1, prior_findings=prior)
        all_findings.extend(round_findings)
        prior = json.dumps(round_findings, ensure_ascii=False, indent=2)[:4000]

    print(f"\n{'='*60}")
    print("SYNTHESIZING FINAL CRITIQUE...")
    print(f"{'='*60}")

    critique = synthesize_critique(plan_text, all_findings)

    output_path = args.output or "reports/deep_research_plan_critique.json"
    out_dir = Path(output_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps({
        "schema_version": "deep_research_plan_critique.v1",
        "plan_file": args.plan,
        "all_findings": all_findings,
        "critique": critique,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nDone. Output: {output_path}")
    print(f"\n=== CRITIQUE SUMMARY ===")
    if "overall_assessment" in critique:
        print(f"Assessment: {critique['overall_assessment']}")
    if "critical_gaps" in critique:
        print(f"Critical gaps: {len(critique['critical_gaps'])}")
    if "priority_improvements" in critique:
        for imp in critique["priority_improvements"][:5]:
            print(f"  [{imp.get('urgency','?')}] {imp.get('title','?')} (effort: {imp.get('effort','?')})")


if __name__ == "__main__":
    main()
