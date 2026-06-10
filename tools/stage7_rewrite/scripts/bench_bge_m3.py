#!/usr/bin/env python3
"""BGE-M3 comprehensive benchmark with real V6 extraction data.

Tests: batch size scaling, memory, throughput, semantic quality.
"""
import json, time, glob, os, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from stage7_runtime_guard import enforce_native_heavy_python_guard

enforce_native_heavy_python_guard("bench_bge_m3")

import torch
from sentence_transformers import SentenceTransformer
import numpy as np

print("=" * 60)
print("BGE-M3 VECTOR BENCHMARK")
print("=" * 60)

# Load model
print("\n[1] Loading BGE-M3...")
t0 = time.perf_counter()
model = SentenceTransformer("BAAI/bge-m3", device="cuda")
print(f"    Loaded in {time.perf_counter()-t0:.1f}s, VRAM: {torch.cuda.memory_allocated()/1024**3:.1f}GB")

# Load real V6 extraction data
v6_paths = glob.glob("/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/overnight_v6_20260510_*/flash_manifest_shard_00_*/flash_rows.partial.jsonl")
if not v6_paths:
    print("ERROR: No V6 data found")
    sys.exit(1)

print(f"\n[2] Loading V6 extraction data from {v6_paths[0]}...")
cards = []
with open(v6_paths[0]) as f:
    for line in f:
        try: row = json.loads(line)
        except: continue
        
        title = row.get("title","")[:80]
        acct = row.get("source_account","")
        
        # Article card
        cards.append(f"公众号:{acct} | 标题:{title}")
        
        # Entity cards from chunks
        for c in row.get("chunks",[]):
            raw = c.get("raw_content","")
            if not raw or not c.get("parse_ok"): continue
            try: data = json.loads(raw)
            except: continue
            for ent in data.get("entities",[]):
                name = ent.get("name","")
                etype = ent.get("type","")
                bio = ent.get("bio","")[:60]
                card = f"实体:{name} | 类型:{etype}"
                if bio: card += f" | 简介:{bio}"
                cards.append(card)
            for ev in data.get("events",[]):
                ev_name = ev.get("name","")[:60]
                ev_time = ev.get("time","")
                ev_place = ev.get("place","")
                card = f"活动:{ev_name}"
                if ev_time: card += f" | 时间:{ev_time}"
                if ev_place: card += f" | 地点:{ev_place}"
                cards.append(card)
        
        if len(cards) > 5000: break  # Enough for benchmark

print(f"    Loaded {len(cards)} cards from V6 extraction")

# Batch size benchmark
batch_sizes = [16, 32, 64, 128, 256]
print(f"\n[3] Batch size benchmark ({len(cards)} cards)...")
print(f"{'Batch':<8} {'Time':<10} {'Cards/s':<10} {'VRAM peak':<12}")
print("-" * 42)

best_bs = 64; best_rate = 0
for bs in batch_sizes:
    torch.cuda.reset_peak_memory_stats()
    t_start = time.perf_counter()
    _ = model.encode(cards[:2000], batch_size=bs, normalize_embeddings=True, show_progress_bar=False)
    elapsed = time.perf_counter() - t_start
    rate = 2000 / elapsed
    vram = torch.cuda.max_memory_allocated() / 1024**3
    print(f"{bs:<8} {elapsed:<10.1f}s {rate:<10.0f} {vram:<12.1f}GB")
    if rate > best_rate:
        best_rate = rate
        best_bs = bs

print(f"\n    Best: batch_size={best_bs}, {best_rate:.0f} cards/s")

# Full throughput test
print(f"\n[4] Full throughput test ({len(cards)} cards, batch_size={best_bs})...")
torch.cuda.reset_peak_memory_stats()
t0 = time.perf_counter()
embeddings = model.encode(cards, batch_size=best_bs, normalize_embeddings=True, show_progress_bar=False)
elapsed = time.perf_counter() - t_start
vram = torch.cuda.max_memory_allocated() / 1024**3
rate = len(cards) / elapsed

print(f"    Time: {elapsed:.1f}s")
print(f"    Rate: {rate:.0f} cards/s")
print(f"    VRAM peak: {vram:.1f}GB")
print(f"    Output: {embeddings.shape}")

# Project to 570K
total = 570000
est_min = total / rate / 60
print(f"    570K projection: {est_min:.0f} min")

# Semantic quality: venue search simulation
print(f"\n[5] Semantic search simulation...")
queries = [
    "上海 ALL Club 电子音乐 Techno 派对",
    "北京 DADA 酒吧 House 之夜 DJ",
    "深圳 OIL 俱乐部 地下音乐 B2B",
    "44KW 实验电子 前卫艺术",
]
query_embs = model.encode(queries, normalize_embeddings=True)
sim = np.dot(query_embs, embeddings.T)

for i, q in enumerate(queries):
    top5 = np.argsort(-sim[i])[:5]
    print(f"\n  查询: {q[:50]}...")
    for j, idx in enumerate(top5):
        score = sim[i][idx]
        print(f"    {j+1}. [{score:.3f}] {cards[idx][:80]}")

# Memory summary
print(f"\n[6] Summary")
print(f"    Model: BGE-M3 (BAAI/bge-m3)")
print(f"    Dim: 1024")
print(f"    Best batch: {best_bs}")
print(f"    Max rate: {best_rate:.0f} cards/s")
print(f"    VRAM usage: {torch.cuda.memory_allocated()/1024**3:.1f}GB (idle)")
print(f"    VRAM peak: {vram:.1f}GB (full load)")
print(f"    570K cards: {est_min:.0f} min")
print(f"    GPU: {torch.cuda.get_device_name(0)}")
print(f"\n✅ BGE-M3 benchmark complete")
