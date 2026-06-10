"""Config loader with profile support."""
from __future__ import annotations
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class LLMConfig:
    endpoint: str = "http://127.0.0.1:11434"
    api_style: str = "openai_compatible"
    model: str = "qwen3.6-27b"
    api_key: str = ""
    prompt_path: str = ""
    concurrency: int = 1
    timeout_sec: int = 180
    max_retries: int = 3
    retry_backoff_sec: list[int] = field(default_factory=lambda: [5, 20, 60])
    temperature: float = 0.0
    top_p: float = 0.85
    top_k: int | None = 20
    repeat_penalty: float | None = 1.08
    max_tokens: int = 4096
    no_thinking: bool = True
    enable_thinking: bool = False


@dataclass
class ChunkingConfig:
    target_chars: int = 2200
    max_chars: int = 5000
    min_chars: int = 800
    overlap_chars: int = 280
    paragraph_aware: bool = True
    hard_max_chars: int = 6500


@dataclass
class QualityConfig:
    min_evidence_hit_rate_pass: float = 0.85
    suspicious_empty_entity_min_chars: int = 2500
    max_failed_chunks_per_article: int = 2
    allow_empty_recovery: bool = False
    bio_exact_match_required: bool = True
    evidence_exact_match_required: bool = True


@dataclass
class VectorConfig:
    endpoints: list[str] = field(default_factory=list)
    preferred_dimension: int = 1024
    batch_size: int = 16
    timeout_sec: int = 60
    max_retries: int = 3


@dataclass
class PipelineConfig:
    stage: int = 7
    version: str = "v1"
    one_pass_default: bool = True
    two_pass_enabled: bool = False
    save_raw: bool = True
    save_bad_samples: bool = True


@dataclass
class Config:
    input_root: Path = Path(r"D:\DDownload\_llm_release_v2\articles")
    output_root: Path = Path(r"D:\downstream_results\stage7_rewrite")
    llm: LLMConfig = field(default_factory=LLMConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    vector: VectorConfig = field(default_factory=VectorConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    profiles: dict[str, dict] = field(default_factory=dict)


def runtime_path(value: str | os.PathLike) -> Path:
    """Resolve Windows drive paths to WSL mount paths when running under WSL.

    Stage7 configs are shared with Windows operators and commonly use
    ``D:\\...`` paths.  Inside WSL, ``Path('D:\\...')`` is a relative Linux path
    and doctor/preflight falsely reports missing inputs.  Convert drive-rooted
    paths to ``/mnt/<drive>/...`` only when not running on native Windows.
    """
    s = str(value)
    m = re.match(r"^([A-Za-z]):[\\/]*(.*)$", s)
    if os.name != "nt" and m:
        drive = m.group(1).lower()
        rest = m.group(2).replace("\\", "/")
        return Path(f"/mnt/{drive}/{rest}")
    return Path(s)


def load_profiles(profiles_path: Path | None = None) -> dict[str, dict]:
    """Load LLM profiles from YAML."""
    if profiles_path is None:
        here = Path(__file__).parent.parent
        profiles_path = here / "config" / "profiles.yaml"
    if not profiles_path.exists():
        return {}
    with open(profiles_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("profiles", {})


def load_config(config_path: Path | None = None) -> Config:
    if config_path is None:
        env_path = os.environ.get("STAGE7_CONFIG")
        if env_path:
            config_path = Path(env_path)
        else:
            here = Path(__file__).parent.parent
            config_path = here / "config" / "default.yaml"

    raw: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    llm_raw = raw.get("llm", {})
    chunk_raw = raw.get("chunking", {})
    quality_raw = raw.get("quality", {})
    vector_raw = raw.get("vector", {})
    pipeline_raw = raw.get("pipeline", {})

    here = Path(__file__).parent.parent
    profiles = load_profiles(here / "config" / "profiles.yaml")

    return Config(
        input_root=runtime_path(raw.get("input_root", r"D:\DDownload\_llm_release_v2\articles")),
        output_root=runtime_path(raw.get("output_root", r"D:\downstream_results\stage7_rewrite")),
        llm=LLMConfig(
            endpoint=llm_raw.get("endpoint", "http://127.0.0.1:11434"),
            api_style=llm_raw.get("api_style", "openai_compatible"),
            model=llm_raw.get("model", "qwen3.6-27b"),
            prompt_path=llm_raw.get("prompt_path", ""),
            concurrency=llm_raw.get("concurrency", 1),
            timeout_sec=llm_raw.get("timeout_sec", 180),
            max_retries=llm_raw.get("max_retries", 3),
            retry_backoff_sec=llm_raw.get("retry_backoff_sec", [5, 20, 60]),
            temperature=llm_raw.get("temperature", 0.0),
            top_p=llm_raw.get("top_p", 0.85),
            top_k=llm_raw.get("top_k", 20),
            repeat_penalty=llm_raw.get("repeat_penalty", 1.08),
            max_tokens=llm_raw.get("max_tokens", 4096),
            no_thinking=llm_raw.get("no_thinking", True),
            enable_thinking=llm_raw.get("thinking", False),
        ),
        chunking=ChunkingConfig(
            target_chars=chunk_raw.get("target_chars", 2200),
            max_chars=chunk_raw.get("max_chars", 5000),
            min_chars=chunk_raw.get("min_chars", 800),
            overlap_chars=chunk_raw.get("overlap_chars", 280),
            paragraph_aware=chunk_raw.get("paragraph_aware", True),
            hard_max_chars=chunk_raw.get("hard_max_chars", 6500),
        ),
        quality=QualityConfig(
            min_evidence_hit_rate_pass=quality_raw.get("min_evidence_hit_rate_pass", 0.85),
            suspicious_empty_entity_min_chars=quality_raw.get("suspicious_empty_entity_min_chars", 2500),
            max_failed_chunks_per_article=quality_raw.get("max_failed_chunks_per_article", 2),
            allow_empty_recovery=quality_raw.get("allow_empty_recovery", False),
            bio_exact_match_required=quality_raw.get("bio_exact_match_required", True),
            evidence_exact_match_required=quality_raw.get("evidence_exact_match_required", True),
        ),
        vector=VectorConfig(
            endpoints=vector_raw.get("endpoints", []),
            preferred_dimension=vector_raw.get("preferred_dimension", 1024),
            batch_size=vector_raw.get("batch_size", 16),
            timeout_sec=vector_raw.get("timeout_sec", 60),
            max_retries=vector_raw.get("max_retries", 3),
        ),
        pipeline=PipelineConfig(
            stage=pipeline_raw.get("stage", 7),
            version=pipeline_raw.get("version", "v1"),
            one_pass_default=pipeline_raw.get("facts_first", True),
            two_pass_enabled=pipeline_raw.get("relations_second", False),
            save_raw=pipeline_raw.get("save_raw", True),
            save_bad_samples=pipeline_raw.get("save_bad_samples", True),
        ),
        profiles=profiles,
    )
