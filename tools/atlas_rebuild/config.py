"""Central config + paths for the ATLAS DB rebuild pipeline.

Every stage imports from here. Override anything via env vars (noted inline).
Design notes:
  - Raw source lives on D: (16T mechanical cold-storage drive) and is READ-ONLY.
    Stage1 stages selected posters to the SSD work dir so Stage2 never thrashes D:.
  - Extraction backends (local vLLM / MiMo v2.5 / DeepSeek / DashScope router) are
    OpenAI-compatible, so one client class drives all three (see backends.py).
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- Raw source (read-only) -------------------------------------------------
ARCHIVE_ROOT = os.environ.get("ATLAS_ARCHIVE_ROOT", r"D:\DDownload\_archive_mptext")
QUEUE_JSONL = os.environ.get("ATLAS_QUEUE_JSONL", r"D:\DDownload\_queues\download_ready_queue.jsonl")

# ---- Work dir (fast SSD; gitignored) ---------------------------------------
WORK_DIR = os.environ.get("ATLAS_WORK_DIR", os.path.join(HERE, "_work"))
STAGING_DIR = os.path.join(WORK_DIR, "staging")       # SSD copies of selected posters
REVIEW_DIR = os.path.join(WORK_DIR, "review_queue")   # low-confidence + merge candidates
DB_INGEST = os.path.join(WORK_DIR, "ingest_index.sqlite")
DB_CLEAN = os.path.join(WORK_DIR, "clean.sqlite")
DB_EXTRACT = os.path.join(WORK_DIR, "extractions.sqlite")
DB_RESOLVED = os.path.join(WORK_DIR, "entities_resolved.sqlite")
DB_SERVING_CANDIDATE = os.path.join(WORK_DIR, "atlas_serving_candidate.sqlite")

# ---- Stage1 poster selection ------------------------------------------------
# WeChat articles bundle logos / spacers / emoji alongside the real poster.
# assets_local.json carries file_size, so we filter by bytes (no image decode).
POSTER_MIN_BYTES = int(os.environ.get("ATLAS_POSTER_MIN_BYTES", "15000"))
# Canary 1-vs-3 poster test (2026-06-16): 1 poster ≈ same quality (15.0 vs 14.4
# fields), −22% tokens. Default 2 = main poster + one backup for split-info cases;
# set ATLAS_POSTER_MAX_COUNT=1 for max API savings.
POSTER_MAX_COUNT = int(os.environ.get("ATLAS_POSTER_MAX_COUNT", "2"))
POSTER_REVIEW_SCORE = float(os.environ.get("ATLAS_POSTER_REVIEW_SCORE", "35"))
POSTER_REVIEW_GAP = float(os.environ.get("ATLAS_POSTER_REVIEW_GAP", "8"))
CLEAN_TEXT_MAX_CHARS = int(os.environ.get("ATLAS_CLEAN_TEXT_MAX", "8000"))

# ---- Stage2 routing ---------------------------------------------------------
LOW_CONF_THRESHOLD = float(os.environ.get("ATLAS_LOW_CONF", "0.6"))
# If a body already looks like a complete event in text, skip the vision tier.
TEXT_COMPLETE_MIN_CHARS = int(os.environ.get("ATLAS_TEXT_COMPLETE_MIN", "400"))

# Remote provider guardrails. Without an explicit timeout a single upstream
# vision request can hang for many minutes and block the whole serial Stage2.
PROVIDER_TIMEOUT_SEC = float(os.environ.get("ATLAS_PROVIDER_TIMEOUT_SEC", "90"))
PROVIDER_MAX_RETRIES = int(os.environ.get("ATLAS_PROVIDER_MAX_RETRIES", "1"))
DASHSCOPE_WAIT_TIMEOUT_SEC = int(os.environ.get("ATLAS_DASHSCOPE_WAIT_TIMEOUT_SEC", "0"))

# ---- Extraction backends ----------------------------------------------------
# local-vllm : 4090 runs `vllm serve <VL model>` exposing an OpenAI server.
# mimo       : MiMo v2.5 multimodal API (remote).
# deepseek   : DeepSeek text model (no vision) for text-only articles + adjudication.
# ocr_deepseek : local RapidOCR for posters, followed by text-only DeepSeek extraction.
# stepfun    : StepFun Step 3.7 Flash vision canary; not a bulk default.
# router_no_glm : legacy verified route: qwen-vl-ocr -> qwen-turbo ->
#                 qwen3-vl-flash -> mimo-v2.5. Kept for reproducibility.
# vl_direct_router : no-OCR route for the 14w plan: qwen3-vl-flash ->
#                    mimo-v2.5, both reading poster images directly.
# mock       : offline schema-valid stub — exercises the whole chain with no GPU/API.
BACKENDS = {
    "mock": {"kind": "mock", "vision": True},
    "local-vllm": {
        "kind": "openai", "vision": True, "guided": "vllm",
        "base_url": os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8000/v1"),
        "model": os.environ.get("VLLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"),
        "api_key": os.environ.get("VLLM_API_KEY", "EMPTY"),
    },
    "mimo": {
        # MiMo multimodal vision API (poster reading). The live vision model is
        # `mimo-v2.5` on the *vision* endpoint/key — verified working 2026-06-15.
        "kind": "openai", "vision": True, "guided": "json_object",
        "base_url": os.environ.get("MIMO_VISION_BASE_URL") or os.environ.get("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
        "model": os.environ.get("MIMO_VISION_MODEL", "mimo-v2.5"),
        "api_key": os.environ.get("MIMO_VISION_API_KEY") or os.environ.get("ATLAS_MIMO_API_KEY") or os.environ.get("MIMO_API_KEY", ""),
    },
    "router_no_glm": {
        "kind": "router_no_glm", "vision": True,
        "dashscope_base_url": os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "dashscope_api_key": os.environ.get("ATLAS_DASHSCOPE_API_KEY") or os.environ.get("DASHSCOPE_API_KEY", ""),
        "qwen_ocr_model": os.environ.get("ATLAS_QWEN_OCR_MODEL", "qwen-vl-ocr-latest"),
        "qwen_text_model": os.environ.get("ATLAS_QWEN_TEXT_MODEL", "qwen-turbo"),
        "qwen_vl_model": os.environ.get("ATLAS_QWEN_VL_MODEL", "qwen3-vl-flash"),
        "mimo_base_url": os.environ.get("MIMO_VISION_BASE_URL") or os.environ.get("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
        "mimo_api_key": os.environ.get("MIMO_VISION_API_KEY") or os.environ.get("ATLAS_MIMO_API_KEY") or os.environ.get("MIMO_API_KEY", ""),
        "mimo_model": os.environ.get("MIMO_VISION_MODEL", "mimo-v2.5"),
        "qwen_ocr_accept_conf": float(os.environ.get("ATLAS_QWEN_OCR_ACCEPT_CONF", "0.75")),
        "qwen3_accept_conf": float(os.environ.get("ATLAS_QWEN3_ACCEPT_CONF", "0.70")),
    },
    "vl_direct_router": {
        "kind": "vl_direct_router", "vision": True,
        "dashscope_base_url": os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "dashscope_api_key": os.environ.get("ATLAS_DASHSCOPE_API_KEY") or os.environ.get("DASHSCOPE_API_KEY", ""),
        "qwen_vl_model": os.environ.get("ATLAS_QWEN_VL_MODEL", "qwen3-vl-flash"),
        "mimo_base_url": os.environ.get("MIMO_VISION_BASE_URL") or os.environ.get("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
        "mimo_api_key": os.environ.get("MIMO_VISION_API_KEY") or os.environ.get("ATLAS_MIMO_API_KEY") or os.environ.get("MIMO_API_KEY", ""),
        "mimo_model": os.environ.get("MIMO_VISION_MODEL", "mimo-v2.5"),
        "qwen3_accept_conf": float(os.environ.get("ATLAS_DIRECT_VL_ACCEPT_CONF", os.environ.get("ATLAS_QWEN3_ACCEPT_CONF", "0.70"))),
    },
    "deepseek": {
        "kind": "openai", "vision": False, "guided": "json_object",
        "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
    },
    "ocr_deepseek": {
        "kind": "ocr_deepseek", "vision": True, "guided": "json_object",
        "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
    },
    "stepfun": {
        "kind": "openai", "vision": True, "guided": "plain_json",
        "base_url": os.environ.get("STEPFUN_VISION_BASE_URL") or os.environ.get("STEPFUN_BASE_URL", "https://api.stepfun.ai/v1"),
        "model": os.environ.get("STEPFUN_VISION_MODEL") or os.environ.get("STEPFUN_MODEL", "step-3.7-flash"),
        "api_key": os.environ.get("STEPFUN_VISION_API_KEY") or os.environ.get("STEPFUN_API_KEY") or os.environ.get("STEP_API_KEY", ""),
        "extra_body": {"reasoning_effort": os.environ.get("ATLAS_STEPFUN_REASONING_EFFORT", "low")},
    },
}
# Escalation target when local confidence < LOW_CONF_THRESHOLD (set --escalate).
ESCALATE_BACKEND = os.environ.get("ATLAS_ESCALATE_BACKEND", "mimo")


def ensure_dirs():
    for d in (WORK_DIR, STAGING_DIR, REVIEW_DIR):
        os.makedirs(d, exist_ok=True)
