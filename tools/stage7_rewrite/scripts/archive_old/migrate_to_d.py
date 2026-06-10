#!/usr/bin/env python3
"""Migrate database and pipeline output from C: to D: drive.
"""
import os, shutil, json, glob
from pathlib import Path

C_BASE = Path("/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite")
D_BASE = Path("/mnt/d/stage7_data")

DIRS_TO_MOVE = [
    "reports",
    "logs",
    "config",
    "schemas",
    "prompts",
]

D_SUBDIRS = {
    "reports": D_BASE / "reports",
    "logs": D_BASE / "logs", 
    "vectors": D_BASE / "vectors",
    "neo4j": D_BASE / "neo4j",
    "sqlite": D_BASE / "sqlite",
    "qdrant": D_BASE / "qdrant",
}

def migrate():
    print("=== Stage7 Data Migration: C: → D: ===")
    print(f"C: {C_BASE} ({shutil.disk_usage('/mnt/c').free / 1024**3:.0f}GB free)")
    print(f"D: {D_BASE} ({shutil.disk_usage('/mnt/d').free / 1024**3:.0f}GB free)")
    
    D_BASE.mkdir(parents=True, exist_ok=True)
    
    # Create target dirs
    for name, path in D_SUBDIRS.items():
        path.mkdir(parents=True, exist_ok=True)
        print(f"  created: {path}")
    
    # Move reports (largest)
    reports_src = C_BASE / "reports"
    reports_dst = D_SUBDIRS["reports"]
    if reports_src.exists():
        print(f"\n  Moving reports/ ({_size_str(reports_src)})...")
        for item in reports_src.iterdir():
            dst = reports_dst / item.name
            if not dst.exists():
                try:
                    shutil.move(str(item), str(dst))
                except Exception as e:
                    print(f"    FAIL: {item.name}: {e}")
        print(f"  reports moved to {reports_dst}")
    
    # Create symlink so old paths still work
    if not reports_src.exists():
        os.symlink(str(reports_dst), str(reports_src), target_is_directory=True)
        print(f"  symlink: {reports_src} → {reports_dst}")
    
    # Move vectors
    vec_src = Path("/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/vectors_bge_m3_20260510")
    if not vec_src.exists():
        vec_src = glob.glob(str(C_BASE / "reports" / "vectors_*"))
        vec_src = Path(vec_src[0]) if vec_src else None
    
    if vec_src and vec_src.exists():
        vec_dst = D_SUBDIRS["vectors"]
        print(f"\n  Moving vectors ({_size_str(vec_src)})...")
        for item in vec_src.iterdir():
            dst = vec_dst / item.name
            if not dst.exists():
                try:
                    shutil.move(str(item), str(dst))
                except Exception as e:
                    print(f"    FAIL: {item.name}: {e}")
    
    # Print final state
    print(f"\n=== Migration complete ===")
    print(f"D: {D_BASE}")
    for name, path in sorted(D_SUBDIRS.items()):
        size = _size_str(path) if path.exists() else "empty"
        print(f"  {name}/ {size}")

def _size_str(p: Path) -> str:
    if not p.exists(): return "n/a"
    try:
        size = sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
        if size > 1024**3: return f"{size/1024**3:.1f}GB"
        if size > 1024**2: return f"{size/1024**2:.0f}MB"
        return f"{size/1024:.0f}KB"
    except: return "?"

if __name__ == "__main__":
    migrate()
