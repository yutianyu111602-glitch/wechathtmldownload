#!/usr/bin/env python3
"""Test BGE-M3 embedding model on RTX 4090 with real WeChat extraction data.

Verifies: dimension, latency, semantic quality, batch throughput.
"""
import json, time, sys, os

print("Loading BGE-M3...", flush=True)
started = time.perf_counter()

from sentence_transformers import SentenceTransformer
import torch

model = SentenceTransformer("BAAI/bge-m3", device="cuda")
elapsed = time.perf_counter() - started
print(f"Model loaded in {elapsed:.1f}s")
print(f"Device: {model.device}")
print(f"VRAM used: {torch.cuda.memory_allocated()/1024**3:.1f} GB")

# Test 1: Single embedding
test_texts = [
    "上海 ALL Club 电子音乐派对 DJ WORDY 现场演出",
    "北京 DADA 酒吧 每周三 House 音乐之夜",
    "深圳 OIL 俱乐部 Techno 派对 B2B 阵容",
    "44KW 上海 地下音乐 实验电子 前卫艺术空间",
]

print(f"\n=== Test 1: Single embeddings ===")
started = time.perf_counter()
embeddings = model.encode(test_texts, normalize_embeddings=True)
elapsed = time.perf_counter() - started

print(f"Shape: {embeddings.shape}")
print(f"Dimension: {embeddings.shape[1]}")
print(f"Time: {elapsed:.3f}s ({elapsed/len(test_texts)*1000:.0f}ms/text)")

# Test 2: Semantic similarity
from sentence_transformers import util
sim = util.cos_sim(embeddings, embeddings)
print(f"\n=== Test 2: Semantic Similarity ===")
for i, t1 in enumerate(test_texts):
    for j, t2 in enumerate(test_texts):
        if i < j:
            print(f"  {sim[i][j]:.3f} | {t1[:40]}... vs {t2[:40]}...")

# Test 3: Batch throughput
batch_texts = []
# Load some real extraction data
manifest = "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/overnight_v5_20260510_000810"
import glob
files = glob.glob(f"{manifest}/flash_manifest_shard_00_*/flash_rows.partial.jsonl")
if files:
    with open(files[0]) as f:
        for i, line in enumerate(f):
            if i >= 200: break
            row = json.loads(line)
            title = row.get("title","")[:80]
            acct = row.get("source_account","")
            # Build a card text similar to what we'd vectorize
            card = f"公众号:{acct} 标题:{title}"
            batch_texts.append(card)

if batch_texts:
    print(f"\n=== Test 3: Batch throughput ({len(batch_texts)} cards) ===")
    started = time.perf_counter()
    batch_emb = model.encode(batch_texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    elapsed = time.perf_counter() - started
    print(f"Shape: {batch_emb.shape}")
    print(f"Time: {elapsed:.1f}s ({elapsed/len(batch_texts)*1000:.1f}ms/card)")
    print(f"Throughput: {len(batch_texts)/elapsed:.0f} cards/s")
    
    # Project 570K cards
    total_cards = 570000
    est_seconds = total_cards / (len(batch_texts)/elapsed)
    print(f"Estimated 570K cards: {est_seconds/60:.0f} min")

# Test 4: Cost comparison
print(f"\n=== Cost Comparison (570K cards) ===")
print(f"  BGE-M3 (4090):     ¥0 (electricity negligible)")
print(f"  OpenAI 3-large:    $11")
print(f"  OpenAI 3-small:    $1.71")

print(f"\n✅ BGE-M3 ready. Dim={embeddings.shape[1]}, GPU={torch.cuda.get_device_name(0)}")
