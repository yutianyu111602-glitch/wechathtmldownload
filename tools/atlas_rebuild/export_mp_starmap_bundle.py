#!/usr/bin/env python
"""Export a small, mp-sized star map bundle from the reconciled atlas v2 serving DB.

Layout strategy (v2): city-geographic positioning.
- DJ nodes seeded at their city's geographic 2D coordinate + local repulsion/attraction
- Venue/org nodes placed at centroid of connected DJs (inherit the city cluster)
- No Fibonacci ring artifact; clusters read as "上海" "北京" "成都" constellations
"""
import argparse, json, sqlite3, math
from pathlib import Path
import numpy as np

from atlas_dataset_identity import resolve_dataset_id
from atlas_subject_filters import is_placeholder_subject

TYPE_COLOR = {"dj": "#7fd4ff", "venue": "#ffcf6b", "org": "#b794f6", "series": "#2dd4bf"}
REL_PRIORITY = {"b2b": 6, "resident_at": 5, "held_at": 4, "signed_to": 3, "presented_by": 3, "collab": 2}

# China city 2D geographic positions (x=West→East, y=South→North, range≈[-0.8,0.8])
CITY_COORDS = {
    "上海": (0.68, -0.08), "Shanghai": (0.68, -0.08),
    "北京": (0.28, 0.62), "Beijing": (0.28, 0.62),
    "成都": (-0.50, -0.02), "Chengdu": (-0.50, -0.02),
    "深圳": (0.50, -0.68), "Shenzhen": (0.50, -0.68), "South China": (0.48, -0.66),
    "广州": (0.38, -0.72), "Guangzhou": (0.38, -0.72),
    "杭州": (0.70, -0.22), "Hangzhou": (0.70, -0.22),
    "重庆": (-0.18, -0.22),
    "武汉": (0.18, 0.08),
    "昆明": (-0.40, -0.58), "云南": (-0.38, -0.56),
    "大理": (-0.55, -0.54), "Dali": (-0.55, -0.54),
    "南京": (0.56, 0.08), "苏州": (0.64, 0.02),
    "西安": (-0.05, 0.20),
    "长沙": (0.22, -0.30),
    "香港": (0.56, -0.76), "Hong Kong": (0.56, -0.76),
    "澳门": (0.54, -0.79),
    "台湾": (0.82, -0.42), "Taiwan": (0.82, -0.42), "Taipei": (0.82, -0.42),
    "济南": (0.38, 0.22),
    "贵阳": (-0.08, -0.40),
    "乌鲁木齐": (-0.78, 0.35), "新疆": (-0.78, 0.35),
    "吉林": (0.56, 0.76), "中国旧工业基地": (0.52, 0.72), "哈尔滨": (0.40, 0.84),
    "沈阳": (0.50, 0.70), "大连": (0.56, 0.66),
    "中山": (0.44, -0.72),
    "福建": (0.66, -0.38), "闽": (0.66, -0.38),
    "济宁": (0.35, 0.18),
    # international: placed at edge of canvas
    "Berlin": (-0.82, 0.82), "Paris": (-0.86, 0.76),
    "Uptown": (0.68, -0.08),  # assume Shanghai
    "中国": (0.10, 0.05), "China": (0.10, 0.05),
}


def _city_coord(city_str):
    if not city_str:
        return None
    city_str = city_str.strip()
    if city_str in CITY_COORDS:
        return np.array(CITY_COORDS[city_str], dtype=float)
    for k, v in CITY_COORDS.items():
        if k in city_str or city_str in k:
            return np.array(v, dtype=float)
    return None


def _layout(n, edges, types, cities, seed=20260621):
    """City-geographic constellation layout.

    1. Seed each DJ at its city's 2D map position + small jitter
    2. 60 iterations: local repulsion between DJs + edge attraction + city anchor
    3. Venues/orgs placed at centroid of connected DJs
    No Fibonacci ring; clusters naturally read as city scenes.
    """
    rng = np.random.default_rng(seed)
    pos = np.zeros((n, 2))
    if n == 0:
        return pos

    dj_mask = np.array([t == "dj" for t in types])
    dj_idx = np.where(dj_mask)[0]
    dj_set = set(dj_idx.tolist())

    # build adjacency
    adj = [[] for _ in range(n)]
    for edge in edges:
        a, b = edge[0], edge[1]
        adj[a].append(b)
        adj[b].append(a)

    # Step 1: seed DJ positions from city map
    dj_city_pos = {}  # i -> city_coord or None
    unanchored = []
    for i in dj_idx:
        cp = _city_coord(cities[i] if i < len(cities) else "")
        dj_city_pos[int(i)] = cp
        if cp is not None:
            pos[i] = cp + rng.normal(0, 0.042, size=2)
        else:
            unanchored.append(int(i))

    # unanchored DJs: place near a connected DJ, else random
    for i in unanchored:
        nbrs = [nb for nb in adj[i] if nb in dj_set and np.any(pos[nb] != 0)]
        if nbrs:
            pos[i] = pos[nbrs[0]] + rng.normal(0, 0.05, size=2)
        else:
            pos[i] = rng.uniform(-0.5, 0.5, size=2)

    # Step 2: force-directed on DJs only
    dj_arr = np.array(list(dj_idx), dtype=int)
    dj_edges = [(edge[0], edge[1]) for edge in edges if edge[0] in dj_set and edge[1] in dj_set]

    k_rep = 0.0018
    k_att = 0.012
    k_anc = 0.010  # city anchor pull strength

    for _ in range(60):
        delta = np.zeros((n, 2))
        # pairwise repulsion among DJs
        for ii in range(len(dj_arr)):
            for jj in range(ii + 1, len(dj_arr)):
                a, b = int(dj_arr[ii]), int(dj_arr[jj])
                diff = pos[a] - pos[b]
                d2 = float(np.dot(diff, diff)) + 1e-5
                f = k_rep / d2 * diff
                delta[a] += f
                delta[b] -= f
        # edge attraction
        for a, b in dj_edges:
            diff = pos[b] - pos[a]
            f = k_att * diff
            delta[a] += f
            delta[b] -= f
        # city anchor
        for i in dj_idx:
            cp = dj_city_pos.get(int(i))
            if cp is not None:
                delta[i] += k_anc * (cp - pos[i])
        # cap and apply
        norms = np.linalg.norm(delta[dj_arr], axis=1, keepdims=True)
        cap = 0.018
        capped = np.where(norms > cap, delta[dj_arr] / (norms + 1e-9) * cap, delta[dj_arr])
        for ii, i in enumerate(dj_arr):
            pos[i] += capped[ii]

    # Step 3: venues/orgs at centroid of connected DJs
    for i in range(n):
        if dj_mask[i]:
            continue
        linked = [nb for nb in adj[i] if nb in dj_set]
        if linked:
            pos[i] = pos[linked].mean(axis=0) + rng.normal(0, 0.030, size=2)
        else:
            cp = _city_coord(cities[i] if i < len(cities) else "")
            pos[i] = (cp + rng.normal(0, 0.05, size=2)) if cp is not None else rng.uniform(-0.55, 0.55, size=2)

    span = np.abs(pos).max() or 1.0
    return pos / span


def write_bundle_outputs(out_path, bundle, out_js_path=None):
    out = Path(out_path)
    js_out = Path(out_js_path) if out_js_path else out.with_suffix(".js")
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload + "\n", encoding="utf-8")
    js_out.write_text("module.exports = " + payload + ";\n", encoding="utf-8")
    return out, js_out


def build(v2_path, out_path, max_nodes=240, max_edges=640, out_js_path=None, dataset_id=None):
    resolved_dataset_id = resolve_dataset_id(Path(v2_path), dataset_id)
    db = sqlite3.connect(f"file:{v2_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    meta = {r["subject_id"]: r for r in db.execute(
        "SELECT subject_id, subject_type, display_name, city_primary, "
        "COALESCE(event_count, 0) AS event_count, "
        "COALESCE(relation_count, 0) AS relation_count, "
        "COALESCE(source_count, 0) AS source_count, "
        "first_seen_at, last_seen_at FROM subject")}
    clean_subjects = {
        sid for sid, row in meta.items()
        if not is_placeholder_subject(sid, row["subject_type"], row["display_name"])
    }
    # degree from the unified relation table (fetching weight for edge sorting)
    deg = {}
    rels = db.execute(
        "SELECT src_subject_id s, dst_subject_id d, relation_type t, COALESCE(weight,1) w FROM relation"
    ).fetchall()
    for r in rels:
        if r["s"] not in clean_subjects or r["d"] not in clean_subjects:
            continue
        deg[r["s"]] = deg.get(r["s"], 0) + 1
        deg[r["d"]] = deg.get(r["d"], 0) + 1
    top = sorted(deg.items(), key=lambda kv: kv[1], reverse=True)[:max_nodes]
    idx = {sid: i for i, (sid, _) in enumerate(top)}
    db.close()

    # collect candidate edges, sort by priority then weight so b2b/resident_at come first
    seen = set()
    candidates = []
    for r in rels:
        a, b = r["s"], r["d"]
        if a not in idx or b not in idx:
            continue
        ia, ib = idx[a], idx[b]
        key = (min(ia, ib), max(ia, ib))
        if key in seen:
            continue
        seen.add(key)
        pri = REL_PRIORITY.get(r["t"], 1)
        candidates.append((pri, float(r["w"]), ia, ib, r["t"]))

    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    edges = [[ia, ib, t, round(weight, 3)] for _, weight, ia, ib, t in candidates[:max_edges]]

    order = [sid for sid, _ in top]
    types = [(meta[s]["subject_type"] if s in meta else "dj") for s in order]
    cities = [(meta[s]["city_primary"] or "") if s in meta else "" for s in order]
    pos = _layout(len(order), edges, types, cities)

    degs = [deg[s] for s in order]
    dmax = max(degs) if degs else 1
    nodes = []
    for i, sid in enumerate(order):
        m = meta.get(sid)
        t = m["subject_type"] if m else "dj"
        nodes.append({
            "i": i,
            "u": sid,
            "n": (m["display_name"] if m else sid),
            "t": t,
            "c": (m["city_primary"] if m else "") or "",
            "x": round(float(pos[i, 0]), 4),
            "y": round(float(pos[i, 1]), 4),
            "s": round(0.5 + 2.5 * (deg[sid] / dmax), 3),
            "ec": int(m["event_count"] or 0),
            "rc": int(m["relation_count"] or 0),
            "sc": int(m["source_count"] or 0),
            "fs": (m["first_seen_at"] or ""),
            "ls": (m["last_seen_at"] or ""),
            "col": TYPE_COLOR.get(t, "#8fb6d9"),
        })

    bundle = {
        "schemaVersion": "atlas.mp.starmap.v2",
        "datasetId": resolved_dataset_id,
        "lens": "entity",
        "generation": "g1_g7_city_geo",
        "nodes": nodes,
        "edges": edges,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
    }
    out, js_out = write_bundle_outputs(out_path, bundle, out_js_path)
    by_type = {}
    for nn in nodes:
        by_type[nn["t"]] = by_type.get(nn["t"], 0) + 1
    print(f"wrote {out} and {js_out}: {len(nodes)} nodes {len(edges)} edges  by_type={by_type}")
    # print city distribution for sanity check
    from collections import Counter
    city_dist = Counter(nn["c"] for nn in nodes if nn["t"] == "dj")
    print("DJ cities (top10):", city_dist.most_common(10))


def _selftest():
    import tempfile, os
    fd, p = tempfile.mkstemp(suffix=".sqlite"); os.close(fd)
    s = sqlite3.connect(p)
    s.execute(
        "CREATE TABLE subject("
        "subject_id TEXT,subject_type TEXT,display_name TEXT,city_primary TEXT,"
        "event_count INT,relation_count INT,source_count INT,first_seen_at TEXT,last_seen_at TEXT)"
    )
    s.execute("CREATE TABLE relation(src_subject_id TEXT,dst_subject_id TEXT,relation_type TEXT,weight REAL,b2b_count INT)")
    for i in range(6):
        s.execute(
            "INSERT INTO subject VALUES(?,?,?,?,?,?,?,?,?)",
            (f"dj:{i}", "dj", f"DJ{i}", "上海", i, i + 5, i + 1, "2020-01-01", "2026-06-20"),
        )
    s.execute("INSERT INTO subject VALUES(?,?,?,?,?,?,?,?,?)", ("dj:b2b", "dj", "B2B", "上海", 99, 99, 99, "2020-01-01", "2026-06-20"))
    s.execute("INSERT INTO subject VALUES(?,?,?,?,?,?,?,?,?)", ("dj:compound", "dj", "Alpha b2b Beta", "上海", 99, 99, 99, "2020-01-01", "2026-06-20"))
    s.execute("INSERT INTO subject VALUES(?,?,?,?,?,?,?,?,?)", ("venue:tba", "venue", "TBA", "上海", 99, 99, 99, "2020-01-01", "2026-06-20"))
    for i in range(5):
        s.execute("INSERT INTO relation VALUES(?,?,?,?,?)", (f"dj:{i}", f"dj:{i+1}", "collab", 10.0, 0))
    s.execute("INSERT INTO relation VALUES(?,?,?,?,?)", ("dj:b2b", "dj:0", "b2b", 100.0, 2))
    s.execute("INSERT INTO relation VALUES(?,?,?,?,?)", ("dj:compound", "dj:0", "collab", 5.0, 0))
    s.execute("INSERT INTO relation VALUES(?,?,?,?,?)", ("venue:tba", "dj:0", "held_at", 3.0, 0))
    s.commit(); s.close()
    outp = p + ".json"
    js_out = p + ".js"
    test_dataset_id = "atlas-selftest-shared-generation-0001"
    build(p, outp, max_nodes=10, max_edges=20, out_js_path=js_out, dataset_id=test_dataset_id)
    b = json.loads(Path(outp).read_text(encoding="utf-8"))
    assert b["schemaVersion"] == "atlas.mp.starmap.v2"
    assert b["datasetId"] == test_dataset_id
    assert resolve_dataset_id(Path(p)).startswith("atlas-sha256-")
    assert str(Path(p).parent) not in json.dumps(b, ensure_ascii=False)
    assert b["counts"] == {"nodes": 6, "edges": 5}, b["counts"]
    assert not {"dj:b2b", "dj:compound", "venue:tba"} & {n["u"] for n in b["nodes"]}
    assert all("x" in n and "y" in n for n in b["nodes"])
    assert all({"ec", "rc", "sc", "fs", "ls"} <= set(n) for n in b["nodes"])
    assert all(len(edge) == 4 and isinstance(edge[3], (int, float)) for edge in b["edges"])
    js_bundle = json.loads(
        Path(js_out).read_text(encoding="utf-8")
        .removeprefix("module.exports = ")
        .removesuffix(";\n")
    )
    assert js_bundle == b
    os.remove(p); os.remove(outp); os.remove(js_out)
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", default="_sandbox_v2_reconciled_20260621/atlas_serving_v2.sqlite")
    ap.add_argument("--out", default="../../apps/weekly_activity_miniprogram/data/atlas_starmap.json")
    ap.add_argument("--out-js")
    ap.add_argument("--max-nodes", type=int, default=240)
    ap.add_argument("--max-edges", type=int, default=640)
    ap.add_argument("--dataset-id", help="Shared public ATLAS generation id; defaults to the v2 DB SHA256")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        _selftest(); return
    build(a.v2, a.out, a.max_nodes, a.max_edges, a.out_js, a.dataset_id)


if __name__ == "__main__":
    main()
