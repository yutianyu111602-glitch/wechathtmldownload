#!/usr/bin/env python
"""Export a small, mp-sized star map bundle from the reconciled atlas v2 serving DB.

The WeChat mini-program cannot run the web's 3D r3f galaxy, so it renders a native
<canvas type="2d"> graph. This emits the L0 overview bundle (top-degree subjects +
edges among them, with a precomputed 2D layout) as static JSON the mp bundles like
data/column-content.json. DJ-trajectory / future-activity / deeper drill come later
via a CloudRun endpoint; this gives a working, backend-free first version.

Read-only on the v2 DB. ponytail: tiny spring layout in Python (≤300 nodes), the mp
only renders + pans/zooms — no layout math on-device.
"""
import argparse, json, sqlite3, math
from pathlib import Path
import numpy as np

# type -> color (matches the web star map / mp neon palette)
TYPE_COLOR = {"dj": "#7fd4ff", "venue": "#ffcf6b", "org": "#b794f6", "series": "#2dd4bf"}


def _layout(n, edges, iters=140, seed=20260621):
    """Tiny Fruchterman-Reingold; deterministic. Returns Nx2 in roughly [-1,1]."""
    rng = np.random.default_rng(seed)
    pos = rng.normal(0, 0.3, size=(n, 2))
    if n <= 1:
        return pos
    k = 1.0 / math.sqrt(n)
    E = np.array(edges, dtype=int) if edges else np.zeros((0, 2), dtype=int)
    for it in range(iters):
        disp = np.zeros((n, 2))
        # repulsion (all pairs; n is small)
        for i in range(n):
            d = pos[i] - pos                      # (n,2)
            dist = np.sqrt((d * d).sum(1)) + 1e-4
            f = (k * k) / dist
            disp[i] = (d / dist[:, None] * f[:, None]).sum(0)
        # attraction along edges
        for a, b in E:
            d = pos[a] - pos[b]
            dist = math.sqrt(float((d * d).sum())) + 1e-4
            f = (dist * dist) / k
            mv = d / dist * f
            disp[a] -= mv
            disp[b] += mv
        t = 0.1 * (1.0 - it / iters)              # cooling
        ln = np.sqrt((disp * disp).sum(1)) + 1e-4
        pos += disp / ln[:, None] * np.minimum(ln, t)[:, None]
    # normalize to [-1,1]
    span = np.abs(pos).max() or 1.0
    return pos / span


def build(v2_path, out_path, max_nodes=240, max_edges=640):
    db = sqlite3.connect(f"file:{v2_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    # degree from the unified relation table
    deg = {}
    rels = db.execute("SELECT src_subject_id s, dst_subject_id d, relation_type t FROM relation").fetchall()
    for r in rels:
        deg[r["s"]] = deg.get(r["s"], 0) + 1
        deg[r["d"]] = deg.get(r["d"], 0) + 1
    top = sorted(deg.items(), key=lambda kv: kv[1], reverse=True)[:max_nodes]
    keep = {sid for sid, _ in top}
    idx = {sid: i for i, sid in enumerate(keep)}
    meta = {r["subject_id"]: r for r in db.execute(
        "SELECT subject_id, subject_type, display_name, city_primary, event_count FROM subject "
        f"WHERE subject_id IN ({','.join('?' * len(keep))})", list(keep))}
    db.close()

    # edges among kept set, strongest first, capped
    seen = set()
    edges = []
    for r in rels:
        a, b = r["s"], r["d"]
        if a in idx and b in idx:
            key = (idx[a], idx[b]) if idx[a] < idx[b] else (idx[b], idx[a])
            if key in seen:
                continue
            seen.add(key)
            edges.append([idx[a], idx[b], r["t"]])
            if len(edges) >= max_edges:
                break

    order = [sid for sid, _ in top]
    pos = _layout(len(order), [(e[0], e[1]) for e in edges])
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
            "s": round(0.5 + 2.5 * (deg[sid] / dmax), 3),   # render size 0.5..3
            "col": TYPE_COLOR.get(t, "#8fb6d9"),
        })

    bundle = {
        "schemaVersion": "atlas.mp.starmap.v1",
        "lens": "entity",
        "generation": "g1_g7_full",
        "nodes": nodes,
        "edges": edges,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    by_type = {}
    for nn in nodes:
        by_type[nn["t"]] = by_type.get(nn["t"], 0) + 1
    print(f"wrote {out_path}: {len(nodes)} nodes {len(edges)} edges  by_type={by_type}")


def _selftest():
    import tempfile, os
    fd, p = tempfile.mkstemp(suffix=".sqlite"); os.close(fd)
    s = sqlite3.connect(p)
    s.execute("CREATE TABLE subject(subject_id TEXT,subject_type TEXT,display_name TEXT,city_primary TEXT,event_count INT)")
    s.execute("CREATE TABLE relation(src_subject_id TEXT,dst_subject_id TEXT,relation_type TEXT)")
    for i in range(6):
        s.execute("INSERT INTO subject VALUES(?,?,?,?,?)", (f"dj:{i}", "dj", f"DJ{i}", "上海", i))
    for i in range(5):
        s.execute("INSERT INTO relation VALUES(?,?,?)", (f"dj:{i}", f"dj:{i+1}", "collab"))
    s.commit(); s.close()
    outp = p + ".json"
    build(p, outp, max_nodes=10, max_edges=20)
    b = json.loads(Path(outp).read_text(encoding="utf-8"))
    assert b["schemaVersion"] == "atlas.mp.starmap.v1"
    assert b["counts"]["nodes"] == 6 and b["counts"]["edges"] == 5, b["counts"]
    assert all("x" in n and "y" in n for n in b["nodes"])
    os.remove(p); os.remove(outp)
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", default="_sandbox_v2_reconciled_20260621/atlas_serving_v2.sqlite")
    ap.add_argument("--out", default="../../apps/weekly_activity_miniprogram/data/atlas_starmap.json")
    ap.add_argument("--max-nodes", type=int, default=240)
    ap.add_argument("--max-edges", type=int, default=640)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        _selftest(); return
    build(a.v2, a.out, a.max_nodes, a.max_edges)


if __name__ == "__main__":
    main()
