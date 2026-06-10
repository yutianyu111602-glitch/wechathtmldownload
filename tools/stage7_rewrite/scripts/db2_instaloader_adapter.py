#!/usr/bin/env python3
"""DB2 Instaloader Adapter — 将 instaloader 接入 DB2 外链抓取管线。

替代崩坏的 ig_nuclear_fission_v2.py，承接 IG profile 抓取任务：
1. 从 swarm_progress 读取 pending 的 IG 种子
2. 用 instaloader 抓取 profile bio / external_url / avatar
3. 写入 spool (dj_social_profiles, dj_outlinks, dj_avatars)
4. 更新 swarm_progress 状态

Usage:
  python3 db2_instaloader_adapter.py --limit 100 --sleep 2.0
  python3 db2_instaloader_adapter.py --worker-id 1 --worker-count 2 --limit 500

Cookie 自动从 /home/pc/cookies/www.instagram.com.cookies.json 加载。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import instaloader

# ── 路径默认值 ──────────────────────────────────────────────
DEFAULT_DB = Path(os.environ.get("DB2_SWARM_DB", "/home/pc/swarm_data/atlas_swarm_data.sqlite"))
DEFAULT_SPOOL = Path(os.environ.get("DB2_WRITE_SPOOL", "/home/pc/swarm_data/write_spool"))
DEFAULT_COOKIE = Path(os.environ.get("IG_COOKIE_FILE", "/home/pc/cookies/www.instagram.com.cookies.json"))
DEFAULT_PROXY = os.environ.get("IG_PROXY", "http://192.168.8.1:7890")

WORKER_ID = "instaloader_adapter"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def url_key_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def stable_id(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:16]


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.execute("PRAGMA query_only=ON")
    return conn


# ── Cookie 加载 ─────────────────────────────────────────────
def load_ig_cookies(cookie_path: Path) -> dict[str, str]:
    """从 Netscape/JSON cookie 文件提取 requests 可用的 dict"""
    if not cookie_path.exists():
        raise FileNotFoundError(f"Cookie file not found: {cookie_path}")

    raw = json.loads(cookie_path.read_text())
    if isinstance(raw, list):
        # JSON array 格式
        return {c["name"]: c["value"] for c in raw if "name" in c and "value" in c}
    if isinstance(raw, dict):
        # 可能已经是 {name: value} 格式
        return {k: v for k, v in raw.items() if not k.startswith("_")}

    raise ValueError(f"Unrecognized cookie format in {cookie_path}")


# ── Spool 写入 ──────────────────────────────────────────────
class SpoolWriter:
    """轻量 spool 写入器，兼容 db2_writer_daemon"""

    def __init__(self, spool_dir: Path):
        self.spool_dir = Path(spool_dir)
        self.incoming = self.spool_dir / "incoming"
        self.incoming.mkdir(parents=True, exist_ok=True)

    def write(self, table: str, rows: list[dict[str, Any]]) -> int:
        """写入 JSONL 到 incoming/，返回写入条数"""
        if not rows:
            return 0
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        fname = f"{WORKER_ID}_{table}_{ts}_{os.getpid()}.jsonl"
        path = self.incoming / fname
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                json.dump(row, f, ensure_ascii=False)
                f.write("\n")
        return len(rows)


# ── 主逻辑 ──────────────────────────────────────────────────
def fetch_pending_profiles(
    db_path: Path,
    *,
    limit: int = 100,
    worker_id: int = 0,
    worker_count: int = 1,
) -> list[dict[str, Any]]:
    """从 dj_social_profiles 读取尚未抓取 outlinks 的 IG 种子

    对齐 ig_nuclear_fission_v2.py 的查询逻辑：
    - 找 platform='instagram' 的 profile
    - 排除已有 outlinks 的 eid (避免重复抓取)
    - 按 eid 首 hex 分片
    """
    conn = connect_readonly(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT sp.eid, sp.entity_name, sp.handle, sp.profile_url,
               (SELECT COUNT(DISTINCT platform) FROM dj_social_profiles sp2
                WHERE sp2.eid = sp.eid) AS platform_count
        FROM dj_social_profiles sp
        WHERE sp.platform = 'instagram'
          AND sp.eid NOT IN (
              SELECT DISTINCT eid FROM dj_outlinks
              WHERE platform = 'instagram'
                AND source IN ('ig_fission_v2', 'fission_v4_deep', 'instaloader_adapter')
          )
        ORDER BY sp.eid
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()

    result = [dict(r) for r in rows]

    # Sharding: 按 eid 首 hex 分片 (兼容原有逻辑)
    if worker_count > 1:
        result = [
            r for r in result
            if r.get("eid") and int(r["eid"][0], 16) % worker_count == worker_id
        ]

    return result


def scrape_profile(L: instaloader.Instaloader, handle: str) -> dict[str, Any] | None:
    """抓取单个 IG profile，返回结构化数据"""
    try:
        profile = instaloader.Profile.from_username(L.context, handle)
    except instaloader.exceptions.ProfileNotExistsException:
        return {"_error": "profile_not_found", "handle": handle}
    except instaloader.exceptions.LoginRequiredException:
        return {"_error": "login_required", "handle": handle}
    except Exception as e:
        return {"_error": str(e)[:200], "handle": handle}

    return {
        "handle": handle,
        "userid": str(profile.userid),
        "full_name": profile.full_name or "",
        "biography": profile.biography or "",
        "external_url": profile.external_url or "",
        "followers": profile.followers,
        "followees": profile.followees,
        "is_verified": profile.is_verified,
        "is_business_account": profile.is_business_account,
        "profile_pic_url": str(profile.profile_pic_url) if profile.profile_pic_url else "",
        "media_count": profile.mediacount,
        "igtv_count": profile.igtvcount,
    }


def profile_to_spool_rows(
    profile_data: dict[str, Any],
    eid: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """将 instaloader 抓取结果转为 spool 行"""
    now = now_iso()
    handle = profile_data.get("handle", "")
    uid = profile_data.get("userid", "")
    external_url = profile_data.get("external_url", "")
    avatar_url = profile_data.get("profile_pic_url", "")
    bio = profile_data.get("biography", "")

    profiles: list[dict[str, Any]] = []
    outlinks: list[dict[str, Any]] = []
    avatars: list[dict[str, Any]] = []

    # dj_social_profiles
    profiles.append({
        "eid": eid,
        "platform": "instagram",
        "platform_id": uid,
        "username": handle,
        "display_name": profile_data.get("full_name", ""),
        "bio": bio,
        "external_url": external_url,
        "followers_count": profile_data.get("followers", 0),
        "following_count": profile_data.get("followees", 0),
        "media_count": profile_data.get("media_count", 0),
        "is_verified": int(profile_data.get("is_verified", False)),
        "source": WORKER_ID,
        "created_at": now,
        "updated_at": now,
    })

    # dj_outlinks (from external_url in bio)
    if external_url and external_url.startswith("http"):
        url_hash = url_key_hash(external_url)
        outlinks.append({
            "eid": eid,
            "url": external_url,
            "url_key_hash": url_hash,
            "platform": "instagram",
            "source": WORKER_ID,
            "source_layer": "ig_bio",
            "created_at": now,
        })

    # dj_avatars
    if avatar_url:
        avatars.append({
            "eid": eid,
            "platform": "instagram",
            "avatar_url": avatar_url,
            "source": WORKER_ID,
            "created_at": now,
        })

    return profiles, outlinks, avatars


def update_swarm_status(
    db_path: Path,
    rowid: int,
    status: str,
    error_msg: str = "",
) -> None:
    """更新 swarm_progress (直接写 DB，waL 模式安全)"""
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        "UPDATE swarm_progress SET status=?, error_msg=?, updated_at=? WHERE rowid=?",
        (status, error_msg, now_iso(), rowid),
    )
    conn.commit()
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="DB2 Instaloader Adapter")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--worker-id", type=int, default=0)
    parser.add_argument("--worker-count", type=int, default=1)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--spool-dir", type=Path, default=DEFAULT_SPOOL)
    parser.add_argument("--cookie-file", type=Path, default=DEFAULT_COOKIE)
    parser.add_argument("--proxy", type=str, default=DEFAULT_PROXY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    global WORKER_ID
    WORKER_ID = f"instaloader_w{args.worker_id}"

    # 1. 加载 cookies
    cookies = load_ig_cookies(args.cookie_file)
    print(f"[{now_iso()}] Loaded {len(cookies)} cookies from {args.cookie_file}")

    # 2. 创建 instaloader 实例
    L = instaloader.Instaloader(
        sleep=bool(args.sleep),
        quiet=True,
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        save_metadata=False,
        compress_json=False,
    )

    # 注入 cookies 到 session
    if args.proxy:
        L.context._session.proxies = {"http": args.proxy, "https": args.proxy}
        print(f"[{now_iso()}] Proxy: {args.proxy}")

    for name, value in cookies.items():
        L.context._session.cookies.set(name, value, domain=".instagram.com")

    # 测试登录状态
    try:
        test_username = L.test_login()
        if test_username:
            print(f"[{now_iso()}] Logged in as: {test_username}")
        else:
            print(f"[{now_iso()}] Cookie auth active (no username returned)")
    except Exception as e:
        print(f"[{now_iso()}] Login test: {e}")

    # 3. 读取 pending profiles
    profiles = fetch_pending_profiles(
        args.db,
        limit=args.limit,
        worker_id=args.worker_id,
        worker_count=args.worker_count,
    )
    print(f"[{now_iso()}] Pending profiles: {len(profiles)} (worker {args.worker_id}/{args.worker_count})")

    if args.dry_run:
        for p in profiles[:10]:
            print(f"  DRY-RUN: eid={p['eid']} handle={p.get('handle', '?')}")
        print(f"  ... and {max(0, len(profiles) - 10)} more")
        return

    # 4. 抓取循环
    spool = SpoolWriter(args.spool_dir)
    stats = {"scraped": 0, "errors": 0, "profiles": 0, "outlinks": 0, "avatars": 0}

    for i, p in enumerate(profiles):
        handle = p.get("handle") or p.get("platform_id", "")
        if not handle:
            continue

        print(f"[{now_iso()}] [{i+1}/{len(profiles)}] @{handle} ...", end=" ", flush=True)

        data = scrape_profile(L, handle)
        stats["scraped"] += 1

        if data and "_error" in data:
            print(f"ERROR: {data['_error']}")
            stats["errors"] += 1
            update_swarm_status(args.db, p["rowid"], "failed", str(data["_error"])[:200])
        elif data:
            prof_rows, out_rows, av_rows = profile_to_spool_rows(data, p["eid"])

            if not args.dry_run:
                n_p = spool.write("dj_social_profiles", prof_rows)
                n_o = spool.write("dj_outlinks", out_rows)
                n_a = spool.write("dj_avatars", av_rows)
                stats["profiles"] += n_p
                stats["outlinks"] += n_o
                stats["avatars"] += n_a

            update_swarm_status(args.db, p["rowid"], "done")
            print(f"OK (followers={data.get('followers',0)}, bio_url={bool(data.get('external_url'))})")
        else:
            stats["errors"] += 1
            update_swarm_status(args.db, p["rowid"], "failed", "no_data")
            print("EMPTY")

        if args.sleep and i < len(profiles) - 1:
            time.sleep(args.sleep)

    # 5. 汇总
    print(f"\n{'='*50}")
    print(f"[{now_iso()}] DONE — scraped={stats['scraped']} errors={stats['errors']}")
    print(f"  profiles={stats['profiles']} outlinks={stats['outlinks']} avatars={stats['avatars']}")


if __name__ == "__main__":
    main()
