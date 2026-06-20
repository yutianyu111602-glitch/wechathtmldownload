#!/usr/bin/env python3
"""ATLAS underground-electronic-music STAR MAP — graph projection (P0).

Reads a Stage4 atlas serving DB (canonical_subject / dj_profile /
dj_relation_rollup) and emits a precomputed 3D layout in the exact shape the
forked cbm graph-ui consumes (`GraphData`):

    { nodes:[{id:int, x,y,z, label, name, size, color, ...extras}],
      edges:[{source:int, target:int, type, ...extras}],
      total_nodes:int, meta:{} }

First lens = "B2B universe": DJ nodes, DJ–DJ relation edges (同台/合作/b2b),
clustered into scenes via weighted label propagation, laid out as constellations
on a Fibonacci sphere. Positions/size/color are baked here so graph-ui just
renders — no cbm C engine, no server needed.

Read-only on the serving DB. numpy-only (no networkx/scipy).
Runnable check: `python export_starmap_layout.py --selftest`.
"""
from __future__ import annotations
import argparse, colorsys, json, math, re, sqlite3, sys
from pathlib import Path
import numpy as np

DEFAULT_DB = "_fleet_14w_g4_40k_increment_20260620/merged/atlas_serving_candidate.sqlite"


def _hsl_hex(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


_VENUE_PUNCT = re.compile(r"[\s·・|｜@＠:：,，.。、_/\\()（）\[\]【】-]")


def _norm_venue(name):
    """Collapse venue name variants of one physical club (Dada Beijing / Dada Bar Beijing)."""
    s = str(name or "").strip().lower().replace("&", "and")
    s = re.sub(r"(club|俱乐部|bar|酒吧|livehouse|live house|studio|space|空间)", "", s)
    return _VENUE_PUNCT.sub("", s)


def load_venues(db_path, kept_dj_ids):
    """DJ->venue rollup rows restricted to the kept DJ set. Tolerates a missing table."""
    db = None
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        keep = set(kept_dj_ids)
        return [
            {"dj_id": r["dj_id"], "venue_name": r["venue_name"], "city": r["city"],
             "event_count": r["event_count"]}
            for r in db.execute("SELECT dj_id, venue_name, city, event_count FROM dj_venue_rollup")
            if r["dj_id"] in keep and (r["venue_name"] or "").strip()
        ]
    except Exception:
        return []
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def load_graph(db_path, min_score, max_nodes, max_edges):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    profiles = {}
    for r in cur.execute(
        "SELECT dj_id, display_name, city_primary, event_count, collaborator_count, "
        "first_seen_at, last_seen_at FROM dj_profile"
    ):
        profiles[r["dj_id"]] = dict(r)

    # relations above the score floor; keep the strongest globally
    rels = cur.execute(
        "SELECT src_dj_id, dst_dj_id, relation_score, b2b_count, same_event_count, "
        "relation_label_zh, sample_evidence_json FROM dj_relation_rollup "
        "WHERE relation_score >= ? ORDER BY relation_score DESC",
        (min_score,),
    ).fetchall()
    db.close()

    # weighted degree to pick the most connected DJs (the B2B core)
    deg = {}
    for r in rels:
        a, b, w = r["src_dj_id"], r["dst_dj_id"], float(r["relation_score"])
        if a == b:
            continue
        deg[a] = deg.get(a, 0.0) + w
        deg[b] = deg.get(b, 0.0) + w
    top = sorted(deg, key=lambda d: deg[d], reverse=True)[:max_nodes]
    keep = set(top)

    # induced edges among kept DJs, strongest first, capped
    edges = []
    seen = set()
    for r in rels:
        a, b = r["src_dj_id"], r["dst_dj_id"]
        if a == b or a not in keep or b not in keep:
            continue
        k = (a, b) if a < b else (b, a)
        if k in seen:
            continue
        seen.add(k)
        edges.append(r)
        if len(edges) >= max_edges:
            break

    # drop isolated DJs (no surviving edge) so the field isn't littered with loners
    connected = set()
    for r in edges:
        connected.add(r["src_dj_id"]); connected.add(r["dst_dj_id"])
    nodes = [d for d in top if d in connected]
    return profiles, nodes, edges


def label_propagation(idx, edges, iters=18, seed=7):
    """Weighted synchronous-ish label propagation -> community per node index."""
    n = len(idx)
    labels = np.arange(n)
    # adjacency as lists for cheap neighbor sweeps
    nbrs = [[] for _ in range(n)]
    for r in edges:
        a, b = idx[r["src_dj_id"]], idx[r["dst_dj_id"]]
        w = float(r["relation_score"])
        nbrs[a].append((b, w)); nbrs[b].append((a, w))
    rng = np.random.default_rng(seed)
    order = np.arange(n)
    for _ in range(iters):
        rng.shuffle(order)
        changed = 0
        for i in order:
            if not nbrs[i]:
                continue
            tally = {}
            for j, w in nbrs[i]:
                tally[labels[j]] = tally.get(labels[j], 0.0) + w
            best = max(tally.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            if best != labels[i]:
                labels[i] = best; changed += 1
        if changed == 0:
            break
    # compact labels -> 0..C-1, ordered by community size desc
    uniq, counts = np.unique(labels, return_counts=True)
    order = uniq[np.argsort(-counts)]
    remap = {old: new for new, old in enumerate(order)}
    return np.array([remap[l] for l in labels]), len(order)


def fibonacci_sphere(n, radius):
    if n == 1:
        return np.array([[0.0, 0.0, 0.0]])
    i = np.arange(n)
    phi = math.pi * (3.0 - math.sqrt(5.0))  # golden angle
    y = 1 - (i / (n - 1)) * 2
    r = np.sqrt(np.clip(1 - y * y, 0, 1))
    theta = phi * i
    return np.stack([np.cos(theta) * r, y, np.sin(theta) * r], axis=1) * radius


def layout(comm, n_comm, sizes, seed=7):
    """Constellation layout: communities spread on a big sphere, members clustered
    around their community center, jittered. Cheap, deterministic, star-map-like."""
    rng = np.random.default_rng(seed)
    centers = fibonacci_sphere(n_comm, radius=120.0)
    pos = np.zeros((len(comm), 3), dtype=float)
    for c in range(n_comm):
        members = np.where(comm == c)[0]
        m = len(members)
        spread = 8.0 + 5.0 * math.sqrt(m)
        local = rng.normal(0, spread, size=(m, 3))
        # bigger nodes drift toward the cluster core
        pull = (sizes[members] / sizes.max()).reshape(-1, 1)
        pos[members] = centers[c] + local * (1.0 - 0.5 * pull)
    return pos


def load_orgs(db_path, kept_dj_ids):
    """DJ->org (label/crew/promoter) rollup rows for the kept DJs. Tolerates a missing table."""
    db = None
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        keep = set(kept_dj_ids)
        return [
            {"dj_id": r["dj_id"], "org_name": r["org_name"], "org_type": r["org_type"],
             "score": r["score"], "sample_evidence_json": r["sample_evidence_json"]}
            for r in db.execute("SELECT dj_id, org_name, org_type, score, sample_evidence_json FROM dj_org_rollup")
            if r["dj_id"] in keep and (r["org_name"] or "").strip()
        ]
    except Exception:
        return []
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def build(db_path, out_path, min_score, max_nodes, max_edges, include_venues=True, max_venues=250,
          venue_dj_cap=12, include_orgs=True, max_orgs=200):
    profiles, node_ids, edges = load_graph(db_path, min_score, max_nodes, max_edges)
    idx = {d: i for i, d in enumerate(node_ids)}

    ev = np.array([float(profiles.get(d, {}).get("event_count") or 0) for d in node_ids])
    comm, n_comm = label_propagation(idx, edges)
    sizes_raw = np.sqrt(ev + 1.0)
    sizes = 0.6 + 3.6 * (sizes_raw / sizes_raw.max() if sizes_raw.max() else sizes_raw)
    pos = layout(comm, n_comm, sizes)

    # color by community (golden-angle hue); lightness nudged by node size
    comm_hue = {c: (c * 0.61803398875) % 1.0 for c in range(n_comm)}
    out_nodes = []
    for i, d in enumerate(node_ids):
        p = profiles.get(d, {})
        out_nodes.append({
            "id": i,
            "x": round(float(pos[i, 0]), 3),
            "y": round(float(pos[i, 1]), 3),
            "z": round(float(pos[i, 2]), 3),
            "label": "dj",
            "name": p.get("display_name") or d,
            # file_path drives the graph-ui sidebar tree -> browse DJs by scene (community)
            "file_path": f"星座{int(comm[i]):02d}/{p.get('display_name') or d}",
            "size": round(float(sizes[i]), 3),
            "color": _hsl_hex(comm_hue[int(comm[i])], 0.72, 0.62),
            # extras (graph-ui ignores unknown fields; detail panel will use them)
            "dj_id": d,
            "city": p.get("city_primary") or "",
            "event_count": int(p.get("event_count") or 0),
            "community": int(comm[i]),
            "first_seen_at": p.get("first_seen_at") or "",
            "last_seen_at": p.get("last_seen_at") or "",
        })

    out_edges = []
    for r in edges:
        a, b = idx[r["src_dj_id"]], idx[r["dst_dj_id"]]
        etype = "b2b" if (r["b2b_count"] or 0) > 0 else "collab"
        # trim inline evidence to the 2 strongest events for the detail panel
        evd = []
        try:
            for e in (json.loads(r["sample_evidence_json"] or "[]"))[:2]:
                evd.append({"title": e.get("event_title"), "date": e.get("starts_at"),
                            "source_ref_id": e.get("source_ref_id")})
        except Exception:
            pass
        out_edges.append({
            "source": a, "target": b, "type": etype,
            "score": round(float(r["relation_score"]), 1),
            "same_event": int(r["same_event_count"] or 0),
            "label_zh": r["relation_label_zh"] or "",
            "evidence": evd,
        })

    # Venue anchors: merge DJ->venue rollup (dedup name variants) into venue nodes
    # placed at the centroid of the DJs who play there, so a club sits inside its scene.
    venue_count = 0
    if include_venues:
        vmap = {}
        for r in load_venues(db_path, node_ids):
            di = idx.get(r["dj_id"])
            if di is None:
                continue
            name = str(r["venue_name"]).strip()
            nkey = _norm_venue(name) or name.lower()
            ec = int(r.get("event_count") or 0)
            g = vmap.setdefault(nkey, {"names": {}, "events": 0, "djs": {}, "city": ""})
            g["names"][name] = g["names"].get(name, 0) + ec
            g["events"] += ec
            g["djs"][di] = g["djs"].get(di, 0) + ec
            if not g["city"]:
                g["city"] = r.get("city") or ""
        ranked = sorted(vmap.values(), key=lambda g: -g["events"])[:max_venues]
        if ranked:
            v_ev = np.sqrt(np.array([g["events"] for g in ranked], dtype=float) + 1.0)
            vsizes = 0.9 + 3.0 * (v_ev / v_ev.max())
            base = len(node_ids)
            vrng = np.random.default_rng(99)
            for k, g in enumerate(ranked):
                djs = sorted(g["djs"].items(), key=lambda kv: -kv[1])
                cen = pos[[di for di, _ in djs]].mean(axis=0) + vrng.normal(0, 4.0, size=3)
                canon = max(g["names"].items(), key=lambda kv: kv[1])[0]
                out_nodes.append({
                    "id": base + k,
                    "x": round(float(cen[0]), 3), "y": round(float(cen[1]), 3), "z": round(float(cen[2]), 3),
                    "label": "venue",
                    "name": canon,
                    "file_path": f"场地/{canon}",
                    "size": round(float(vsizes[k]), 3),
                    "color": "#ffcf6b",  # warm amber anchors, distinct from DJ community hues
                    "city": g["city"],
                    "event_count": int(g["events"]),
                    "community": -1,
                })
                for di, w in djs[:venue_dj_cap]:
                    out_edges.append({"source": di, "target": base + k, "type": "resident_at",
                                      "score": float(w), "same_event": int(w), "label_zh": "驻场/常演", "evidence": []})
            venue_count = len(ranked)

    # Label / crew / promoter (厂牌) anchors: same pattern as venues, with per-edge
    # evidence from the org rollup. Placed at the centroid of their roster DJs.
    org_count = 0
    if include_orgs:
        omap = {}
        for r in load_orgs(db_path, node_ids):
            di = idx.get(r["dj_id"])
            if di is None:
                continue
            name = str(r["org_name"]).strip()
            nkey = _norm_venue(name) or name.lower()
            sc = float(r.get("score") or 0)
            g = omap.setdefault(nkey, {"names": {}, "score": 0.0, "djs": {}, "otype": r.get("org_type") or "", "ev": []})
            g["names"][name] = g["names"].get(name, 0) + 1
            g["score"] += sc
            g["djs"][di] = max(g["djs"].get(di, 0.0), sc)
            if not g["otype"]:
                g["otype"] = r.get("org_type") or ""
            if len(g["ev"]) < 2 and r.get("sample_evidence_json"):
                try:
                    for e in json.loads(r["sample_evidence_json"])[:2]:
                        g["ev"].append({"title": e.get("event_title"), "date": e.get("starts_at"),
                                        "source_ref_id": e.get("source_ref_id")})
                except Exception:
                    pass
        ranked = sorted(omap.values(), key=lambda g: -g["score"])[:max_orgs]
        if ranked:
            o_sc = np.sqrt(np.array([g["score"] for g in ranked], dtype=float) + 1.0)
            osizes = 0.9 + 2.6 * (o_sc / o_sc.max())
            base2 = len(out_nodes)
            orng = np.random.default_rng(123)
            for k, g in enumerate(ranked):
                djs = sorted(g["djs"].items(), key=lambda kv: -kv[1])
                cen = pos[[di for di, _ in djs]].mean(axis=0) + orng.normal(0, 5.0, size=3)
                canon = max(g["names"].items(), key=lambda kv: kv[1])[0]
                out_nodes.append({
                    "id": base2 + k,
                    "x": round(float(cen[0]), 3), "y": round(float(cen[1]), 3), "z": round(float(cen[2]), 3),
                    "label": "org",
                    "name": canon,
                    "file_path": f"厂牌/{canon}",
                    "size": round(float(osizes[k]), 3),
                    "color": "#b794f6",  # violet anchors for labels/crews/promoters
                    "city": "",
                    "event_count": 0,
                    "org_type": g["otype"],
                    "community": -1,
                })
                for di, w in djs[:venue_dj_cap]:
                    out_edges.append({"source": di, "target": base2 + k, "type": "signed_to",
                                      "score": float(w), "same_event": 0, "label_zh": "厂牌/主办", "evidence": list(g["ev"])})
            org_count = len(ranked)

    edge_type_counts = {}
    for e in out_edges:
        edge_type_counts[e["type"]] = edge_type_counts.get(e["type"], 0) + 1
    data = {
        "version": "atlas_starmap.layout.v1",
        "project": "atlas-underground-cn",
        "lens": "b2b_universe",
        "nodes": out_nodes,
        "edges": out_edges,
        "total_nodes": len(out_nodes),
        "meta": {
            "source_db": str(db_path),
            "min_score": min_score,
            "node_count": len(out_nodes),
            "edge_count": len(out_edges),
            "edge_type_counts": edge_type_counts,
            "communities": n_comm,
            "venue_count": venue_count,
            "org_count": org_count,
            "generated_by": "export_starmap_layout.py",
        },
    }
    _validate(data)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _is_finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _validate(data):
    assert isinstance(data, dict), "layout must be a JSON object"
    assert data.get("version") == "atlas_starmap.layout.v1", "bad or missing layout version"
    assert data.get("project") == "atlas-underground-cn", "bad or missing project"
    assert data.get("lens") == "b2b_universe", "bad or missing P1 lens"

    nodes, edges = data.get("nodes"), data.get("edges")
    assert isinstance(nodes, list) and nodes, "no nodes"
    assert isinstance(edges, list), "edges must be a list"
    assert data.get("total_nodes") == len(nodes), "total_nodes must match nodes length"

    ids = [n.get("id") for n in nodes if isinstance(n, dict)]
    assert len(ids) == len(nodes), "every node must be an object with id"
    assert ids == list(range(len(nodes))), "node ids must be contiguous 0..N-1"
    nset = set(ids)

    required_node_fields = ("id", "name", "x", "y", "z", "label", "size", "color")
    for n in nodes:
        missing = [k for k in required_node_fields if k not in n]
        assert not missing, f"node {n.get('id')} missing fields: {missing}"
        assert isinstance(n["name"], str) and n["name"].strip(), f"node {n['id']} missing name"
        assert isinstance(n["label"], str) and n["label"].strip(), f"node {n['id']} missing label"
        for k in ("x", "y", "z"):
            assert _is_finite_number(n[k]), f"node {n['id']} bad {k}"
        assert _is_finite_number(n["size"]) and float(n["size"]) > 0, f"node {n['id']} bad size"
        color = n["color"]
        assert isinstance(color, str) and len(color) == 7 and color.startswith("#"), f"node {n['id']} bad color"
        int(color[1:], 16)

    required_edge_fields = ("source", "target", "type")
    edge_type_counts = {}
    for i, e in enumerate(edges):
        assert isinstance(e, dict), f"edge {i} must be an object"
        missing = [k for k in required_edge_fields if k not in e]
        assert not missing, f"edge {i} missing fields: {missing}"
        assert e["source"] in nset and e["target"] in nset, f"edge {i} references unknown node"
        assert e["source"] != e["target"], f"edge {i} is a self-edge"
        assert isinstance(e["type"], str) and e["type"].strip(), f"edge {i} missing type"
        edge_type_counts[e["type"]] = edge_type_counts.get(e["type"], 0) + 1
        evidence = e.get("evidence", [])
        assert isinstance(evidence, list), f"edge {i} evidence must be a list"
        for j, item in enumerate(evidence):
            assert isinstance(item, dict), f"edge {i} evidence {j} must be an object"
            for k in ("title", "date", "source_ref_id"):
                if item.get(k) is not None:
                    assert isinstance(item[k], str), f"edge {i} evidence {j} bad {k}"

    meta = data.get("meta")
    assert isinstance(meta, dict), "meta must be an object"
    if "node_count" in meta:
        assert meta["node_count"] == len(nodes), "meta.node_count must match nodes length"
    if "edge_count" in meta:
        assert meta["edge_count"] == len(edges), "meta.edge_count must match edges length"
    if "edge_type_counts" in meta:
        assert meta["edge_type_counts"] == edge_type_counts, "meta.edge_type_counts must match edges"

    return {
        "version": data["version"],
        "project": data["project"],
        "lens": data["lens"],
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "b2b": edge_type_counts.get("b2b", 0),
        "collab": edge_type_counts.get("collab", 0),
        "edge_type_counts": edge_type_counts,
    }


def validate_file(layout_path):
    data = json.loads(Path(layout_path).read_text(encoding="utf-8"))
    summary = _validate(data)
    print("validation OK:", json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return summary


def _selftest():
    # synthetic two-cluster graph -> expect 2 communities, valid layout
    import tempfile, os
    fd, p = tempfile.mkstemp(suffix=".sqlite"); os.close(fd)
    db = sqlite3.connect(p); c = db.cursor()
    c.execute("CREATE TABLE dj_profile(dj_id TEXT, display_name TEXT, city_primary TEXT, "
              "event_count INT, collaborator_count INT, first_seen_at TEXT, last_seen_at TEXT)")
    c.execute("CREATE TABLE dj_relation_rollup(src_dj_id TEXT,dst_dj_id TEXT,relation_score REAL,"
              "b2b_count INT,same_event_count INT,relation_label_zh TEXT,sample_evidence_json TEXT)")
    djs = [f"dj:a{i}" for i in range(6)] + [f"dj:b{i}" for i in range(6)]
    for d in djs:
        c.execute("INSERT INTO dj_profile VALUES(?,?,?,?,?,?,?)", (d, d.upper(), "", 10, 3, "2025-01-01", "2025-06-01"))
    def link(a, b, s, b2b=0):
        c.execute("INSERT INTO dj_relation_rollup VALUES(?,?,?,?,?,?,?)",
                  (a, b, s, b2b, 2, "同台", '[{"event_title":"X","starts_at":"2025-01-01","source_ref_id":"src:1"}]'))
    for i in range(6):
        for j in range(i + 1, 6):
            link(f"dj:a{i}", f"dj:a{j}", 30); link(f"dj:b{i}", f"dj:b{j}", 30)
    link("dj:a0", "dj:b0", 25, b2b=1)  # one bridge
    db.commit(); db.close()
    data = build(p, p + ".out.json", min_score=20, max_nodes=100, max_edges=1000)
    summary = validate_file(p + ".out.json")
    os.remove(p); os.remove(p + ".out.json")
    assert data["meta"]["communities"] == 2, f"expected 2 communities, got {data['meta']['communities']}"
    assert data["total_nodes"] == 12
    assert summary["total_nodes"] == 12
    assert summary["b2b"] == 1
    assert data["meta"]["edge_type_counts"]["b2b"] == 1
    assert any(e["type"] == "b2b" for e in data["edges"])
    print("selftest OK:", data["total_nodes"], "nodes,", len(data["edges"]), "edges,",
          data["meta"]["communities"], "communities")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default="_starmap_out/atlas_layout.json")
    ap.add_argument("--min-score", type=float, default=20.0)
    ap.add_argument("--max-nodes", type=int, default=1500)
    ap.add_argument("--max-edges", type=int, default=8000)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--validate", help="validate an existing atlas_layout.json and print P1 contract summary")
    ap.add_argument("--no-venues", action="store_true", help="exclude venue anchor nodes (DJ-only B2B lens)")
    ap.add_argument("--max-venues", type=int, default=250)
    ap.add_argument("--no-orgs", action="store_true", help="exclude label/crew/promoter (厂牌) anchor nodes")
    ap.add_argument("--max-orgs", type=int, default=200)
    a = ap.parse_args()
    if a.selftest:
        _selftest(); return
    if a.validate:
        validate_file(a.validate); return
    data = build(a.db, a.out, a.min_score, a.max_nodes, a.max_edges,
                 include_venues=not a.no_venues, max_venues=a.max_venues,
                 include_orgs=not a.no_orgs, max_orgs=a.max_orgs)
    comms = {}
    for n in data["nodes"]:
        comms[n["community"]] = comms.get(n["community"], 0) + 1
    xs = [n["x"] for n in data["nodes"]]
    print(f"wrote {a.out}")
    print(f"  nodes={data['total_nodes']} edges={len(data['edges'])} communities={data['meta']['communities']}")
    print(f"  coord x range [{min(xs):.1f},{max(xs):.1f}]  size range "
          f"[{min(n['size'] for n in data['nodes']):.2f},{max(n['size'] for n in data['nodes']):.2f}]")
    top = sorted(comms.items(), key=lambda kv: -kv[1])[:6]
    print("  top communities (size):", top)
    b2b = sum(1 for e in data["edges"] if e["type"] == "b2b")
    print(f"  edges: b2b={b2b} collab={len(data['edges'])-b2b}")
    # name a few hubs per top community for a sanity sniff
    for c, _ in top[:3]:
        names = [n["name"] for n in sorted(data["nodes"], key=lambda n: -n["event_count"]) if n["community"] == c][:5]
        print(f"  community {c} top DJs:", names)


if __name__ == "__main__":
    main()
