"""Pluggable extraction backends.

Most real backends are OpenAI-compatible, so one class drives local vLLM,
MiMo v2.5, and DeepSeek — only base_url / model / api_key differ.
`ocr_deepseek` runs poster OCR locally and sends text only to DeepSeek.
`router_no_glm` keeps the earlier OCR-first route for reproducibility.
`vl_direct_router` is the no-OCR route for the 14w plan:
qwen3-vl-flash -> mimo-v2.5, both reading poster images directly.
`MockBackend` runs the whole chain offline (no GPU/API).

Interface:  extract(system_prompt, user_text, image_paths, schema) -> dict
The returned dict is raw model JSON ({events, entities}); the caller validates
it against schema.ArticleExtraction.
"""
from __future__ import annotations
import base64
import io
import json
import mimetypes
import os
import re
from typing import List

import config


def get_backend(name: str):
    spec = config.BACKENDS.get(name)
    if spec is None:
        raise SystemExit(f"unknown backend {name!r}; choices: {list(config.BACKENDS)}")
    if spec["kind"] == "mock":
        return MockBackend(name, spec)
    if spec["kind"] == "router_no_glm":
        return RouterNoGlmBackend(name, spec)
    if spec["kind"] == "vl_direct_router":
        return DirectVlRouterBackend(name, spec)
    if spec["kind"] == "ocr_deepseek":
        return LocalOcrDeepSeekBackend(name, spec)
    return OpenAICompatibleBackend(name, spec)


def _img_data_url(path: str, max_side: int = 1800) -> str:
    try:
        from PIL import Image

        with Image.open(path) as im:
            im.seek(0)
            im = im.convert("RGB")
            scale = min(1.0, max_side / max(im.size))
            if scale < 1.0:
                im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=88, optimize=True)
        b64 = base64.b64encode(out.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _loads_json_liberal(text: str) -> dict:
    text = _strip_json(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some providers emit bare Windows/path backslashes inside strings.
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)
        return json.loads(repaired)


def _usage_tuple(resp) -> tuple[int, int]:
    u = getattr(resp, "usage", None)
    if not u:
        return (0, 0)
    return (getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0)


def _max_conf(raw: dict) -> float:
    if not isinstance(raw, dict):
        return 0.0
    events = raw.get("events") or []
    if not events:
        return 1.0
    vals = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        try:
            vals.append(float(ev.get("confidence") or 0.0))
        except (TypeError, ValueError):
            vals.append(0.0)
    return max(vals or [0.0])


def _missing_event_date(raw: dict) -> bool:
    if not isinstance(raw, dict):
        return True
    events = raw.get("events") or []
    return any(isinstance(ev, dict) and not ev.get("date_start") for ev in events)


class MockBackend:
    """Deterministic, schema-valid stub. Lets you validate Stage0->1->2 plumbing,
    routing, dedup and DB writes without a GPU or any API key."""

    def __init__(self, name, spec):
        self.name = name
        self.vision = spec.get("vision", True)
        self.last_usage = (0, 0)

    def extract(self, system_prompt, user_text, image_paths, schema) -> dict:
        first_line = next((ln.strip() for ln in user_text.splitlines() if ln.strip()), "")
        title = first_line[:80] or "(untitled)"
        has_img = bool(image_paths)
        # Minimal stub valid against the rich schema (all other fields default).
        return {
            "events": [{
                "title": title,
                "poster_asset_id": "image-0" if has_img else None,
                "confidence": 0.5,
                "evidence": "poster" if has_img else "text",
            }],
            "entities": {"djs": [], "venues": [], "orgs": [], "series": []},
        }


class OpenAICompatibleBackend:
    def __init__(self, name, spec):
        from openai import OpenAI  # imported lazily so `mock` runs with no openai config
        self.name = name
        self.vision = spec.get("vision", False)
        self.model = spec["model"]
        self.guided = spec.get("guided", "json_object")
        self.extra_body = spec.get("extra_body") or None
        self.last_usage = (0, 0)   # (prompt_tokens, completion_tokens) of last call
        if not spec.get("base_url"):
            raise SystemExit(f"backend {name!r}: base_url not configured (set env, see config.py)")
        self.client = OpenAI(
            base_url=spec["base_url"],
            api_key=spec.get("api_key") or "EMPTY",
            timeout=config.PROVIDER_TIMEOUT_SEC,
            max_retries=config.PROVIDER_MAX_RETRIES,
        )

    def _messages(self, system_prompt, user_text, image_paths):
        content: List[dict] = [{"type": "text", "text": user_text}]
        if self.vision:
            for p in image_paths:
                content.append({"type": "image_url", "image_url": {"url": _img_data_url(p)}})
        elif image_paths:
            content[0]["text"] += "\n\n(注：本后端不读图，仅凭正文抽取。)"
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]

    def _request_kwargs(self, schema):
        kw = {"model": self.model, "temperature": 0, "max_tokens": 4096}
        if self.guided == "vllm":
            kw["extra_body"] = {"guided_json": schema}          # vLLM strict structured output
        elif self.guided == "json_schema":
            kw["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "ArticleExtraction", "schema": schema}}
        elif self.guided == "plain_json":
            pass
        else:
            kw["response_format"] = {"type": "json_object"}     # MiMo / DeepSeek
        if self.extra_body:
            kw["extra_body"] = self.extra_body
        return kw

    def extract(self, system_prompt, user_text, image_paths, schema) -> dict:
        msgs = self._messages(system_prompt, user_text, image_paths)
        kw = self._request_kwargs(schema)
        for attempt in (1, 2):
            resp = self.client.chat.completions.create(messages=msgs, **kw)
            u = getattr(resp, "usage", None)
            if u:
                self.last_usage = (u.prompt_tokens or 0, u.completion_tokens or 0)
            raw = resp.choices[0].message.content or ""
            try:
                return _loads_json_liberal(raw)
            except json.JSONDecodeError:
                if attempt == 2:
                    raise
                kw["max_tokens"] = 8192   # rare giant posters truncate at 4096
                msgs = msgs + [
                    {"role": "assistant", "content": raw[:500]},
                    {"role": "user", "content": "只输出符合 schema 的合法 JSON，不要任何其他文字。"},
                ]
        raise RuntimeError("unreachable")


class LocalOcrDeepSeekBackend:
    """Read posters locally, then send only extracted text to DeepSeek."""

    def __init__(self, name, spec, *, ocr_engine=None, text_backend=None):
        self.name = name
        self.vision = True
        self.last_usage = (0, 0)
        self._ocr_engine = ocr_engine
        text_spec = dict(spec)
        text_spec["vision"] = False
        self._text_backend = text_backend or OpenAICompatibleBackend(name, text_spec)

    def _engine(self):
        if self._ocr_engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise RuntimeError(
                    "ocr_deepseek requires rapidocr_onnxruntime in the active Python environment"
                ) from exc
            self._ocr_engine = RapidOCR()
        return self._ocr_engine

    @staticmethod
    def _result_text(result) -> str:
        rows = result[0] if isinstance(result, tuple) else result
        lines = []
        for row in rows or []:
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            try:
                score = float(row[2])
            except (TypeError, ValueError):
                score = 0.0
            text = str(row[1] or "").strip()
            if text and score >= 0.35:
                lines.append(text)
        return "\n".join(lines)

    @staticmethod
    def _has_text_event_signal(user_text: str) -> bool:
        return bool(
            re.search(
                r"20\d{2}|\d{1,2}[./月-]\d{1,2}|周[一二三四五六日天]|星期|[0-2]?\d[:：][0-5]\d",
                user_text or "",
            )
        )

    def extract(self, system_prompt, user_text, image_paths, schema) -> dict:
        ocr_sections = []
        for index, path in enumerate(image_paths):
            text = self._result_text(self._engine()(str(path)))
            if text:
                ocr_sections.append(f"[poster image-{index}]\n{text}")
        if image_paths and not ocr_sections and not self._has_text_event_signal(user_text):
            raise RuntimeError("local poster OCR returned no usable text; refusing text-only fallback")
        prompt = user_text
        if ocr_sections:
            prompt += "\n\nLOCAL_POSTER_OCR:\n" + "\n\n".join(ocr_sections)
        elif image_paths:
            prompt += "\n\nLOCAL_POSTER_OCR: (no usable text; extract only explicit facts from title/body)"
        raw = self._text_backend.extract(system_prompt, prompt, [], schema)
        self.last_usage = self._text_backend.last_usage
        return raw


class RouterNoGlmBackend:
    """Cheapest verified API route for bulk poster extraction.

    Order:
      1. DashScope qwen-vl-ocr-latest reads poster text.
      2. DashScope qwen-turbo structures clean_text + OCR text.
      3. DashScope qwen3-vl-flash handles low-confidence/invalid cases.
      4. MiMo v2.5 is final fallback only.
    """

    def __init__(self, name, spec):
        from openai import OpenAI

        self.name = name
        self.vision = True
        self.last_usage = (0, 0)
        self.qwen_ocr_model = spec.get("qwen_ocr_model", "")
        self.qwen_text_model = spec.get("qwen_text_model", "")
        self.qwen_vl_model = spec["qwen_vl_model"]
        self.mimo_model = spec["mimo_model"]
        self.qwen_ocr_accept_conf = spec.get("qwen_ocr_accept_conf", 0.75)
        self.qwen3_accept_conf = spec.get("qwen3_accept_conf", 0.70)
        if not spec.get("dashscope_api_key"):
            raise SystemExit(f"backend {name!r}: missing DASHSCOPE_API_KEY or ATLAS_DASHSCOPE_API_KEY")
        if not spec.get("mimo_api_key"):
            raise SystemExit(f"backend {name!r}: missing MIMO_API_KEY or ATLAS_MIMO_API_KEY")
        dashscope_headers = {}
        if config.DASHSCOPE_WAIT_TIMEOUT_SEC > 0:
            dashscope_headers["X-DashScope-Wait-Timeout"] = str(config.DASHSCOPE_WAIT_TIMEOUT_SEC)
        self.dashscope = OpenAI(
            base_url=spec["dashscope_base_url"],
            api_key=spec["dashscope_api_key"],
            timeout=config.PROVIDER_TIMEOUT_SEC,
            max_retries=config.PROVIDER_MAX_RETRIES,
            default_headers=dashscope_headers or None,
        )
        self.mimo = OpenAI(
            base_url=spec["mimo_base_url"],
            api_key=spec["mimo_api_key"],
            timeout=config.PROVIDER_TIMEOUT_SEC,
            max_retries=config.PROVIDER_MAX_RETRIES,
        )

    def _image_content(self, image_paths):
        content: List[dict] = []
        for i, path in enumerate(image_paths):
            content.append({"type": "text", "text": f"poster_image_index: image-{i}"})
            content.append({"type": "image_url", "image_url": {"url": _img_data_url(path)}})
        return content

    def _json_kwargs(self, model, max_tokens=4096):
        return {
            "model": model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

    def _json_completion(self, client, model, messages) -> tuple[dict, tuple[int, int]]:
        usage = (0, 0)
        raw = ""
        for attempt, max_tokens in enumerate((4096, 8192), start=1):
            request_messages = messages
            if attempt == 2:
                request_messages = messages + [
                    {"role": "assistant", "content": raw[:500]},
                    {"role": "user", "content": "上一条输出不是合法 JSON 或被截断。请重新输出完整合法 JSON，只输出 JSON，不要 Markdown 或解释。"},
                ]
            resp = client.chat.completions.create(
                messages=request_messages,
                **self._json_kwargs(model, max_tokens=max_tokens),
            )
            u = _usage_tuple(resp)
            usage = (usage[0] + u[0], usage[1] + u[1])
            raw = resp.choices[0].message.content or ""
            try:
                return (_loads_json_liberal(raw), usage)
            except json.JSONDecodeError:
                if attempt == 2:
                    raise
        raise AssertionError("unreachable json retry loop")

    def _ocr_text(self, user_text, image_paths) -> tuple[str, tuple[int, int]]:
        content = self._image_content(image_paths)
        content.append({
            "type": "text",
            "text": "请只提取图片中的所有可见文字，保持原始换行和顺序；不要解释，不要总结，不要补充不存在的内容。",
        })
        resp = self.dashscope.chat.completions.create(
            model=self.qwen_ocr_model,
            temperature=0,
            max_tokens=2400,
            messages=[
                {"role": "system", "content": "你是 OCR 引擎，只输出图片中真实可见文字。"},
                {"role": "user", "content": content},
            ],
        )
        return (resp.choices[0].message.content or "", _usage_tuple(resp))

    def _structure_with_qwen_text(self, system_prompt, user_text, ocr_text, schema) -> tuple[dict, tuple[int, int]]:
        prompt = (
            user_text
            + "\n\nOCR_TEXT_FROM_SELECTED_POSTERS:\n"
            + (ocr_text or "(OCR empty)")[:12000]
            + "\n\n只输出符合 schema 的 JSON；不要 Markdown；不要解释。"
        )
        return self._json_completion(
            self.dashscope,
            self.qwen_text_model,
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
        )

    def _structure_with_qwen_vl(self, system_prompt, user_text, image_paths, schema) -> tuple[dict, tuple[int, int]]:
        content = [{"type": "text", "text": user_text + "\n\n只输出符合 schema 的 JSON；不要 Markdown；不要解释。"}]
        content.extend(self._image_content(image_paths))
        return self._json_completion(
            self.dashscope,
            self.qwen_vl_model,
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
        )

    def _structure_with_mimo(self, system_prompt, user_text, image_paths, schema) -> tuple[dict, tuple[int, int]]:
        content = [{"type": "text", "text": user_text + "\n\n只输出符合 schema 的 JSON；不要 Markdown；不要解释。"}]
        content.extend(self._image_content(image_paths))
        return self._json_completion(
            self.mimo,
            self.mimo_model,
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
        )

    def _accept(self, raw: dict, threshold: float) -> bool:
        return _max_conf(raw) >= threshold and not _missing_event_date(raw)

    def extract(self, system_prompt, user_text, image_paths, schema) -> dict:
        self.last_usage = (0, 0)
        errors = []

        try:
            ocr_text, u1 = self._ocr_text(user_text, image_paths)
            raw, u2 = self._structure_with_qwen_text(system_prompt, user_text, ocr_text, schema)
            self.last_usage = (self.last_usage[0] + u1[0] + u2[0], self.last_usage[1] + u1[1] + u2[1])
            if self._accept(raw, self.qwen_ocr_accept_conf):
                return raw
            errors.append(f"qwen_ocr_schema rejected: conf={_max_conf(raw):.2f} missing_date={_missing_event_date(raw)}")
        except Exception as e:
            errors.append(f"qwen_ocr_schema failed: {type(e).__name__}: {e}")

        try:
            raw, u = self._structure_with_qwen_vl(system_prompt, user_text, image_paths, schema)
            self.last_usage = (self.last_usage[0] + u[0], self.last_usage[1] + u[1])
            if self._accept(raw, self.qwen3_accept_conf):
                return raw
            errors.append(f"qwen3_vl rejected: conf={_max_conf(raw):.2f} missing_date={_missing_event_date(raw)}")
        except Exception as e:
            errors.append(f"qwen3_vl failed: {type(e).__name__}: {e}")

        try:
            raw, u = self._structure_with_mimo(system_prompt, user_text, image_paths, schema)
            self.last_usage = (self.last_usage[0] + u[0], self.last_usage[1] + u[1])
            if self._accept(raw, 0.0):
                return raw
            errors.append(f"mimo rejected: conf={_max_conf(raw):.2f} missing_date={_missing_event_date(raw)}")
        except Exception as e:
            errors.append(f"mimo failed: {type(e).__name__}: {e}")

        raise RuntimeError("router_no_glm exhausted; " + " | ".join(errors))


class DirectVlRouterBackend(RouterNoGlmBackend):
    """No-OCR multimodal route.

    This matches the 14w plan wording: give the selected posters directly to a
    VL model, then fall back to MiMo only for invalid, low-confidence, or
    date-missing outputs. It intentionally never calls `_ocr_text` or the
    qwen-turbo text structuring tier.
    """

    def extract(self, system_prompt, user_text, image_paths, schema) -> dict:
        self.last_usage = (0, 0)
        errors = []

        try:
            raw, u = self._structure_with_qwen_vl(system_prompt, user_text, image_paths, schema)
            self.last_usage = (self.last_usage[0] + u[0], self.last_usage[1] + u[1])
            if self._accept(raw, self.qwen3_accept_conf):
                return raw
            errors.append(
                f"qwen3_vl_direct rejected: conf={_max_conf(raw):.2f} "
                f"missing_date={_missing_event_date(raw)}"
            )
        except Exception as e:
            errors.append(f"qwen3_vl_direct failed: {type(e).__name__}: {e}")

        try:
            raw, u = self._structure_with_mimo(system_prompt, user_text, image_paths, schema)
            self.last_usage = (self.last_usage[0] + u[0], self.last_usage[1] + u[1])
            if self._accept(raw, 0.0):
                return raw
            errors.append(f"mimo rejected: conf={_max_conf(raw):.2f} missing_date={_missing_event_date(raw)}")
        except Exception as e:
            errors.append(f"mimo failed: {type(e).__name__}: {e}")

        raise RuntimeError("vl_direct_router exhausted; " + " | ".join(errors))
