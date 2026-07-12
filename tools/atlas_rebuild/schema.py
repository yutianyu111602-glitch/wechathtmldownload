"""Rich extraction schema (Pydantic v2) — LIBERAL capture contract.

Philosophy: be liberal in what we accept from the model, strict in what we
canonicalize later (Stage3). Real VL models emit near-perfect but drifting JSON:
missing title, `type` vs `label`, null enums, `social:[]` vs object, a bare string
or null where a list is expected. So the capture schema:
  - `extra="ignore"` — drop unknown keys
  - almost everything Optional; enums relaxed to free strings (normalized later)
  - universal coercion: any list field tolerates None/str/dict; confidence clamps

The model returns ONLY `{events, entities}`. Provenance is attached by the driver.
`extraction_json_schema()` still feeds vLLM guided_json.
"""
from __future__ import annotations
import re
from typing import List, Optional, Annotated
from pydantic import BaseModel, Field, ConfigDict, BeforeValidator, model_validator

_Cfg = ConfigDict(extra="ignore")


# ---- universal coercers (handle real-model drift) ---------------------------
def _strlist(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, list):
        return [str(x).strip() for x in v if x not in (None, "") and str(x).strip()]
    return []


def _objlist(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    if isinstance(v, dict):
        return [v]
    return []


def _lineup(v):
    raw = _objlist_or_list(v)
    out = []
    for item in raw:
        if isinstance(item, str):
            name = _as_str(item)
            if name:
                out.append({"name": name})
            continue
        if not isinstance(item, dict):
            continue
        member = dict(item)
        name = _as_str(member.get("name"))
        if not name:
            name = _as_str(
                member.get("artist")
                or member.get("surface")
                or member.get("name_en")
                or member.get("alias")
            )
        if not name:
            continue
        member["name"] = name
        out.append(member)
    return out


def _b2b(v):
    return [_strlist(x) for x in _objlist_or_list(v)]


def _objlist_or_list(v):
    if isinstance(v, list):
        return v
    if v is None:
        return []
    return [v]


def _conf(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


def _social(v):
    return v if isinstance(v, dict) else None


def _as_str(v):
    # Scalar string fields sometimes arrive as a list (e.g. gear:['vinyl']) or dict.
    if v is None:
        return None
    if isinstance(v, list):
        parts = [str(x).strip() for x in v if x not in (None, "")]
        return ", ".join(parts) or None
    if isinstance(v, dict):
        return None
    s = str(v).strip()
    return s or None


def _entity_objlist(v):
    out = []
    for item in _objlist(v):
        entity = dict(item)
        surface = (
            _as_str(entity.get("surface"))
            or _as_str(entity.get("name"))
            or _as_str(entity.get("name_zh"))
            or _as_str(entity.get("name_en"))
            or _as_str(entity.get("title"))
            or _as_str(entity.get("label"))
        )
        if not surface:
            continue
        entity["surface"] = surface
        out.append(entity)
    return out


def _as_credits(v):
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip():
        return {"designer": v.strip()}   # models emit "Poster by X" as a bare string
    return None


def _as_ticketing(v):
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip():
        return {"platform": v.strip()}
    return None


def _as_obj_or_none(v):
    return v if isinstance(v, dict) else None


def _as_entities(v):
    return v if isinstance(v, dict) else {}   # models sometimes emit entities:[]


def _as_rmb_amount(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(round(float(v)))
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if any(word in s.lower() for word in ("free",)) or any(word in s for word in ("免费", "免票")):
            return 0
        m = re.search(r"\d+(?:\.\d+)?", s)
        return int(round(float(m.group(0)))) if m else None
    return None


StrList = Annotated[List[str], BeforeValidator(_strlist)]
ConfFloat = Annotated[float, BeforeValidator(_conf)]
LooseStr = Annotated[Optional[str], BeforeValidator(_as_str)]


# ---- shared value objects ---------------------------------------------------
class Social(BaseModel):
    model_config = _Cfg
    instagram: LooseStr = None
    soundcloud: LooseStr = None
    bandcamp: LooseStr = None
    resident_advisor: LooseStr = None
    mixcloud: LooseStr = None
    spotify: LooseStr = None
    wechat: LooseStr = None
    website: LooseStr = None


SocialField = Annotated[Optional[Social], BeforeValidator(_social)]


class Geo(BaseModel):
    model_config = _Cfg
    lat: Optional[float] = None
    lng: Optional[float] = None


# ---- event sub-objects ------------------------------------------------------
class SetSlot(BaseModel):
    model_config = _Cfg
    slot: LooseStr = None
    artist: LooseStr = None


class LineupMember(BaseModel):
    model_config = _Cfg
    name: str = Field(description="artist name exactly as printed")
    name_en: LooseStr = None
    role: LooseStr = "unknown"
    performance_type: LooseStr = "unknown"
    styles: StrList = Field(default_factory=list)
    b2b_with: StrList = Field(default_factory=list)


class PriceTier(BaseModel):
    model_config = _Cfg
    label: LooseStr = None
    amount_rmb: Annotated[Optional[int], BeforeValidator(_as_rmb_amount)] = None
    raw: LooseStr = None

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, d):
        if isinstance(d, dict):
            d = dict(d)
            if not d.get("label") and d.get("type"):
                d["label"] = d["type"]
            amt = d.get("amount_rmb")
            if amt is not None:
                d["amount_rmb"] = _as_rmb_amount(amt)
        return d


class Ticketing(BaseModel):
    model_config = _Cfg
    platform: LooseStr = None
    url: LooseStr = None


class PosterCredits(BaseModel):
    model_config = _Cfg
    designer: LooseStr = None
    vj: LooseStr = None
    visual: LooseStr = None


class Event(BaseModel):
    model_config = _Cfg
    title: LooseStr = None
    date_start: LooseStr = None
    date_end: LooseStr = None
    time_text: LooseStr = None
    set_times: Annotated[List[SetSlot], BeforeValidator(_objlist)] = Field(default_factory=list)
    city: LooseStr = None
    venue: LooseStr = None
    address: LooseStr = None
    room: LooseStr = None
    lineup: Annotated[List[LineupMember], BeforeValidator(_lineup)] = Field(default_factory=list)
    b2b_sets: Annotated[List[List[str]], BeforeValidator(_b2b)] = Field(default_factory=list)
    styles: StrList = Field(default_factory=list)
    price_tiers: Annotated[List[PriceTier], BeforeValidator(_objlist)] = Field(default_factory=list)
    ticketing: Annotated[Optional[Ticketing], BeforeValidator(_as_ticketing)] = None
    organizer: LooseStr = None
    presented_by: StrList = Field(default_factory=list)
    series_name: LooseStr = None
    sponsors: StrList = Field(default_factory=list)
    special_concept: StrList = Field(default_factory=list)
    age_policy: LooseStr = None
    dress_theme: LooseStr = None
    poster_credits: Annotated[Optional[PosterCredits], BeforeValidator(_as_credits)] = None
    poster_asset_id: LooseStr = None
    confidence: ConfFloat = 0.0
    evidence: LooseStr = "none"


# ---- entity objects ---------------------------------------------------------
class ArtistEntity(BaseModel):
    model_config = _Cfg
    surface: str
    name_zh: LooseStr = None
    name_en: LooseStr = None
    aliases: StrList = Field(default_factory=list)
    origin_city: LooseStr = None
    nationality: LooseStr = None
    roles: StrList = Field(default_factory=list)
    affiliations: StrList = Field(default_factory=list)
    styles: StrList = Field(default_factory=list)
    social: SocialField = None
    gear: LooseStr = None
    bio_snippet: LooseStr = None


class VenueEntity(BaseModel):
    model_config = _Cfg
    surface: str
    name_en: LooseStr = None
    city: LooseStr = None
    district: LooseStr = None
    address: LooseStr = None
    geo: Annotated[Optional[Geo], BeforeValidator(_as_obj_or_none)] = None
    venue_type: LooseStr = None
    rooms: Optional[int] = None
    capacity: Optional[int] = None
    booth_gear: StrList = Field(default_factory=list)
    sound_brand: StrList = Field(default_factory=list)
    social: SocialField = None
    resident_djs: StrList = Field(default_factory=list)


class OrgEntity(BaseModel):
    model_config = _Cfg
    surface: str
    org_type: LooseStr = "unknown"
    city: LooseStr = None
    roster: StrList = Field(default_factory=list)
    social: SocialField = None


class SeriesEntity(BaseModel):
    model_config = _Cfg
    surface: str
    venue: LooseStr = None
    organizer: LooseStr = None
    concept: LooseStr = None


class Entities(BaseModel):
    model_config = _Cfg
    djs: Annotated[List[ArtistEntity], BeforeValidator(_entity_objlist)] = Field(default_factory=list)
    venues: Annotated[List[VenueEntity], BeforeValidator(_entity_objlist)] = Field(default_factory=list)
    orgs: Annotated[List[OrgEntity], BeforeValidator(_entity_objlist)] = Field(default_factory=list)
    series: Annotated[List[SeriesEntity], BeforeValidator(_entity_objlist)] = Field(default_factory=list)


class ArticleExtraction(BaseModel):
    model_config = _Cfg
    events: Annotated[List[Event], BeforeValidator(_objlist)] = Field(default_factory=list)
    entities: Annotated[Entities, BeforeValidator(_as_entities)] = Field(default_factory=Entities)


def extraction_json_schema() -> dict:
    return ArticleExtraction.model_json_schema()


SYSTEM_PROMPT = """\
你是中文电子音乐演出信息抽取器。输入是一篇微信公众号文章的正文 + 它的海报图（0~N 张）。
任务：把文章里**真实存在**的信息**尽量抽干净**，按给定 JSON schema 输出。

核心规则：
1. 只抽确实出现的事实；看不到就 null/空数组，**禁止编造**（尤其禁止瞎补年份）。
2. 海报图通常是信息主源 —— 日期/时间/时间表/城市/场地/地址/阵容/票价/曲风/主办/系列/音响品牌优先从海报读。
3. 一篇可含多个活动→events 多条；回顾/通知/招聘等非活动→events 返回 []。
4. 每条 event 必须有 title（活动标题，没有就用主标题概括）。
5. date_start/date_end 用 YYYY-MM-DD；price_tiers 每档用 {label, amount_rmb}（label 如 presale/door/student）。
6. 所有数组字段必须是数组；social 必须是对象或省略，不要用字符串或数组。

events 每条尽量填全：title, date_start/end, time_text, set_times[{slot,artist}],
city, venue, address, room, lineup[{name,name_en,role,performance_type,styles,b2b_with}],
b2b_sets, styles, price_tiers[{label,amount_rmb,raw}], ticketing{platform,url},
organizer, presented_by, series_name, sponsors, special_concept, age_policy,
dress_theme, poster_credits, poster_asset_id, confidence(0~1), evidence(poster/text/both/none)。

role 取值：headliner/support/opener/local/resident/b2b；performance_type：dj_set/live/vinyl_only/modular/hybrid。

entities：
- djs：surface, name_zh/name_en, aliases, origin_city, nationality(domestic/foreign),
  roles, affiliations, styles, social{instagram,soundcloud,bandcamp,resident_advisor,mixcloud,spotify}, gear, bio_snippet
- venues：surface, city/district/address, venue_type, booth_gear, sound_brand, resident_djs, social
- orgs：surface, org_type(label/crew/promoter/radio/agency), city, roster, social
- series：surface, venue, organizer, concept

只输出 JSON，不要解释。"""
