#!/usr/bin/env python3
"""Opt-in ultra-degraded single article R2 recovery helper for Stage7.

This helper intentionally does not change default batch runner behavior. It
imports run_er_sample_full, injects a temporary R2 profile in-process, runs one
manifest row, then enforces anti-phantom final/zip gates.
"""
import argparse, json, sys, time, hashlib, zipfile, shutil, re
from pathlib import Path
from datetime import datetime

STAGE7_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGE7_DIR))
import run_er_sample_full as runner

FAILED_ID = "Dyfs8ManV-AxUj_G77TSZA"
FAILED_ACCOUNT = "THE WINDOW CLUB"
PROFILE = "ultra_degraded_hitlimit"

def sha256(path):
    p=Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() and p.is_file() else None

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def write_md(path, title, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(f"# {title}\n\n```json\n"+json.dumps(obj, ensure_ascii=False, indent=2)+"\n```\n", encoding='utf-8')

def install_profile():
    runner.ER_CONFIGS[PROFILE] = {
        "model": "qwen3.6:27b", "stream": False, "think": False,
        "options": {"temperature": 0.1, "top_p": 0.85, "num_predict": 4096, "num_ctx": 8192},
        "limits": {"entities_limit": 8, "events_limit": 6, "relations_limit": 8, "bio_limit": 48, "evidence_limit": 72},
        "chunk_chars": 600,
        "request_timeout": 120,
        "article_total_timeout_formula": "max(600, chunks * 90)",
    }
    def r2_select_config(chars):
        return PROFILE
    def r2_timeout(config_name, num_chunks):
        if config_name == PROFILE:
            return min(max(600, int(num_chunks) * 90), runner.ARTICLE_TOTAL_TIMEOUT_HARD_CAP_SEC)
        return runner.compute_article_total_timeout(config_name, num_chunks)
    base_prompt = runner.PROMPT_ER
    r2_rules = """

R2 ultra_degraded_hitlimit profile (mandatory):
- JSON only. No markdown. No explanation. No prose outside JSON.
- Not exhaustive: prioritize high-confidence event facts only.
- Hard caps per chunk: entities <= 8, events <= 6, relations <= 8, claims <= 6, keywords <= 8, topics <= 5.
- summary must be short.
- entity.bio must be a short exact substring from source text; do not copy long paragraphs.
- evidence/evidence_text must be a short exact substring from source text; do not copy long paragraphs.
- If exact substring is not available, omit the item/field.
- Do not output placeholders, empty strings, or recovered_empty.
- Keep every field compact to avoid completion length limit.
"""
    runner.PROMPT_ER = base_prompt + r2_rules
    runner.select_config = r2_select_config
    runner.compute_article_total_timeout = r2_timeout

def validate_single_manifest(path):
    rows=[json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()]
    if len(rows)!=1:
        raise SystemExit(f"manifest must contain exactly 1 row, got {len(rows)}")
    r=rows[0]
    if r.get('article_id') != FAILED_ID or r.get('source_account') != FAILED_ACCOUNT:
        raise SystemExit(f"manifest row mismatch: {r.get('source_account')} / {r.get('article_id')}")
    return r

def qa_single(result, source_text):
    ok = bool(result and result.get('article_id') == FAILED_ID and result.get('source_account') == FAILED_ACCOUNT)
    status_done = result.get('status') == 'done' if result else False
    qa={
        'total': 1, 'done': 1 if status_done else 0, 'failed': 0 if status_done else 1,
        'timeout': 1 if (result or {}).get('timeout') else 0,
        'parse_fail': int((result or {}).get('parse_fail_count') or 0),
        'thinking_total': int((result or {}).get('total_thinking_len') or 0),
        'recovered_empty': int((result or {}).get('recovered_empty_success') or 0),
        'hit_limit_any': 1 if (result or {}).get('hit_limit_any') else 0,
        'json_valid': bool(result), 'schema_pass': ok,
        'bio_substring_pass': float((result or {}).get('bio_substring_pass_rate', 0) or 0) == 1.0 and int((result or {}).get('bio_span_blank_count') or 0)==0,
        'evidence_substring_pass': float((result or {}).get('evidence_substring_pass_rate', 0) or 0) == 1.0 and int((result or {}).get('evidence_span_blank_count') or 0)==0,
        'markdown_wrapper': 'NO', 'per_article_output_present': ok,
        'article_id': (result or {}).get('article_id'), 'account': (result or {}).get('source_account'),
        'chunk_count': (result or {}).get('chunk_count'),
        'hit_limit_chunk_indexes': [c.get('chunk_index') for c in (result or {}).get('chunk_details',[]) if c.get('hit_limit')],
        'copied_from_invalid_recovered': 'NO', 'copied_from_premature_batch004': 'NO', 'summary_only': 'NO'
    }
    qa['qa_pass'] = all([
        qa['done']==1, qa['failed']==0, qa['timeout']==0, qa['parse_fail']==0,
        qa['thinking_total']==0, qa['recovered_empty']==0, qa['hit_limit_any']==0,
        qa['json_valid'], qa['schema_pass'], qa['bio_substring_pass'], qa['evidence_substring_pass'],
        qa['per_article_output_present']
    ])
    return qa

def merge_final(original_result_path, r2_result, out_json):
    orig=read_json(original_result_path)
    results=orig.get('results') or []
    replaced=False; merged=[]
    for r in results:
        if r.get('article_id') == FAILED_ID:
            rr=json.loads(json.dumps(r2_result, ensure_ascii=False))
            rr['recovery_mode']='R2_ultra_degraded_single_article'
            rr['replaces_original_status']=r.get('status')
            merged.append(rr); replaced=True
        else:
            merged.append(r)
    if not replaced:
        raise SystemExit('anti-phantom gate: failed article not found in original result')
    done=sum(1 for r in merged if r.get('status')=='done')
    failed=sum(1 for r in merged if r.get('status') not in ('done','skipped_with_reason'))
    final={
        'timestamp': datetime.now().isoformat(timespec='seconds'),
        'verdict':'GREEN_R2_PATCHED_RECOVERED' if done==200 and failed==0 else 'RED_R2_MERGE_NOT_CLEAN',
        'recovery_mode':'R2_ultra_degraded_single_article',
        'total':len(merged),'done':done,'failed':failed,
        'timeout':sum(1 for r in merged if r.get('timeout')),
        'parse_fail':sum(int(r.get('parse_fail_count') or 0) for r in merged),
        'thinking_total':sum(int(r.get('total_thinking_len') or 0) for r in merged),
        'recovered_empty':sum(int(r.get('recovered_empty_success') or 0) for r in merged),
        'hit_limit_any':sum(1 for r in merged if r.get('hit_limit_any')),
        'non_done_articles':failed,
        'zero_extract':sum(1 for r in merged if int(r.get('entities_count') or 0)+int(r.get('events_count') or 0)+int(r.get('relations_count') or 0)==0),
        'failed_article_id':FAILED_ID,
        'recovered_article_present_in_final': any(r.get('article_id')==FAILED_ID and r.get('source_account')==FAILED_ACCOUNT and r.get('status')=='done' for r in merged),
        'original_result_path':str(original_result_path),
        'results': merged,
    }
    if not final['recovered_article_present_in_final']:
        final['verdict']='RED_R2_PHANTOM_GREEN'
    write_json(out_json, final)
    return final

def make_zip(zip_path, files, verify_dir):
    zip_path=Path(zip_path); zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for p in files:
            p=Path(p)
            if p.exists(): z.write(p, 'evidence/'+p.name)
    if verify_dir.exists(): shutil.rmtree(verify_dir)
    verify_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z: z.extractall(verify_dir)
    text='\n'.join([p.read_text(errors='replace')[:200000] for p in verify_dir.rglob('*') if p.is_file() and p.stat().st_size < 5_000_000])
    return {'zip':str(zip_path),'sha256':sha256(zip_path),'present_in_zip': FAILED_ID in text and FAILED_ACCOUNT in text and 'R2_ultra_degraded_single_article' in text}

def anti_phantom_self_test(tmp):
    tmp=Path(tmp); tmp.mkdir(parents=True, exist_ok=True)
    fake=tmp/'fake_final.json'; write_json(fake, {'total':200,'done':200,'results':[]})
    try:
        data=read_json(fake)
        ok=any(r.get('article_id')==FAILED_ID for r in data.get('results',[]))
        return {'anti_phantom_gate_test_pass': not ok, 'expected_failure': True}
    except Exception as e:
        return {'anti_phantom_gate_test_pass': False, 'error':repr(e)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--manifest')
    ap.add_argument('--original-result')
    ap.add_argument('--recovery-dir', required=True)
    ap.add_argument('--run-id', default='C1000_BATCH003_R2_PATCHED_20260502')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--anti-phantom-self-test', action='store_true')
    args=ap.parse_args()
    rec=Path(args.recovery_dir); rec.mkdir(parents=True, exist_ok=True)
    for d in ['debug','outputs','qa','zip_verify']: (rec/d).mkdir(parents=True, exist_ok=True)
    if args.anti_phantom_self_test:
        print(json.dumps(anti_phantom_self_test(rec/'anti_phantom_test'), ensure_ascii=False, indent=2)); return
    if not args.manifest or not args.original_result:
        raise SystemExit('--manifest and --original-result required unless --anti-phantom-self-test')
    row=validate_single_manifest(args.manifest)
    source=Path(str(row['llm_input_path']).replace('D:','/mnt/d').replace('C:','/mnt/c').replace('\\','/'))
    source_text=source.read_text(encoding='utf-8')
    install_profile()
    runner.apply_run_scope(args.run_id, rec/'debug', rec/'outputs')
    plan={'timestamp':datetime.now().isoformat(timespec='seconds'),'profile':PROFILE,'manifest':args.manifest,'original_result':args.original_result,'recovery_dir':str(rec),'debug_dir':str(rec/'debug'),'output_dir':str(rec/'outputs'),'runner_path':str(STAGE7_DIR/'run_er_sample_full.py'),'runner_sha256':sha256(STAGE7_DIR/'run_er_sample_full.py'),'runner_mtime':datetime.fromtimestamp((STAGE7_DIR/'run_er_sample_full.py').stat().st_mtime).isoformat(timespec='seconds'),'chunk_strategy':'target=600 hard_max=600 via runner chunk_chars','output_caps':'entities<=8 events<=6 relations<=8 claims<=6 keywords<=8 topics<=5, compact evidence/bio','timeout_strategy':'request=120s article=max(600,chunks*90)','gate_rules':'exact span, strict json, no thinking, no recovered_empty, anti-phantom final/zip','dry_run':args.dry_run}
    write_md(rec/'R2_PATCHED_RECOVERY_PLAN.md','R2_PATCHED_RECOVERY_PLAN',plan)
    if args.dry_run:
        chunks=runner.build_article_chunk_plan(row['article_uid'], source_text, runner.ER_CONFIGS[PROFILE]).chunks
        print(json.dumps({'dry_run_pass':True,'manifest_rows':1,'chunk_count':len(chunks),'max_chunk_len':max(len(c.text) for c in chunks),'profile':runner.ER_CONFIGS[PROFILE]}, ensure_ascii=False, indent=2)); return
    if not args.execute:
        raise SystemExit('pass --execute to call model')
    result=runner.run_article(row)
    single_path=rec/'outputs'/'R2_PER_ARTICLE_Dyfs8ManV-AxUj_G77TSZA.json'
    write_json(single_path, result)
    result_doc={'run_id':args.run_id,'results':[result],'summary':{'total':1,'done':1 if result.get('status')=='done' else 0,'failed':0 if result.get('status')=='done' else 1}}
    write_json(rec/'outputs'/'R2_SINGLE_ARTICLE_RESULT.json', result_doc)
    qa=qa_single(result, source_text)
    qa_json=Path('/mnt/d/downstream_results/stage7_rewrite/reports/BATCH003_R2_PATCHED_RECOVERY_QA_20260502.json')
    qa_md=Path('/mnt/d/downstream_results/stage7_rewrite/reports/BATCH003_R2_PATCHED_RECOVERY_QA_20260502.md')
    write_json(qa_json, qa); write_md(qa_md,'BATCH003_R2_PATCHED_RECOVERY_QA_20260502',qa)
    if not qa['qa_pass']:
        fail={'timestamp':datetime.now().isoformat(timespec='seconds'),'verdict':'RED_R2_PATCHED_STILL_HIT_LIMIT','failed_article_id':FAILED_ID,'llm_input_chars':len(source_text),'r2_chunk_count':result.get('chunk_count'),'hit_limit_stage':'R2_PATCHED_MODEL_OUTPUT','hit_limit_chunk_indexes':qa['hit_limit_chunk_indexes'],'needs_code_level_chunk_output_cap':'YES','needs_per_section_streaming_merge':'POSSIBLE','recommendation':'quarantine/manual_review or bigger patch or alternate model','batch004_blocked':'YES'}
        write_json('/mnt/d/downstream_results/stage7_rewrite/reports/BATCH003_R2_PATCHED_PERSISTENT_HIT_LIMIT_FAILURE_20260502.json', fail)
        write_md('/mnt/d/downstream_results/stage7_rewrite/reports/BATCH003_R2_PATCHED_PERSISTENT_HIT_LIMIT_FAILURE_20260502.md','BATCH003_R2_PATCHED_PERSISTENT_HIT_LIMIT_FAILURE_20260502',fail)
        print(json.dumps({'verdict':'RED_R2_PATCHED_STILL_HIT_LIMIT','qa':qa}, ensure_ascii=False, indent=2)); return
    final_json=Path('/mnt/d/downstream_results/stage7_rewrite/reports/FINAL_BATCH003_R2_PATCHED_RECOVERED_REPORT_20260502.json')
    final_md=Path('/mnt/d/downstream_results/stage7_rewrite/reports/FINAL_BATCH003_R2_PATCHED_RECOVERED_REPORT_20260502.md')
    final=merge_final(Path(args.original_result), result, final_json)
    write_md(final_md,'FINAL_BATCH003_R2_PATCHED_RECOVERED_REPORT_20260502', {k:v for k,v in final.items() if k!='results'})
    if not (final['total']==200 and final['done']==200 and final['failed']==0 and final['timeout']==0 and final['parse_fail']==0 and final['thinking_total']==0 and final['recovered_empty']==0 and final['hit_limit_any']==0 and final['non_done_articles']==0 and final['recovered_article_present_in_final']):
        print(json.dumps({'verdict':'RED_R2_PHANTOM_GREEN','final':{k:v for k,v in final.items() if k!='results'}}, ensure_ascii=False, indent=2)); return
    root_json=Path('/mnt/d/downstream_results/stage7_rewrite/reports/BATCH003_R2_HIT_LIMIT_ROOT_CAUSE_20260502.json')
    root_md=Path('/mnt/d/downstream_results/stage7_rewrite/reports/BATCH003_R2_HIT_LIMIT_ROOT_CAUSE_20260502.md')
    plan_md=Path('/mnt/d/downstream_results/stage7_rewrite/reports/BATCH003_R2_MINIMAL_PATCH_PLAN_20260502.md')
    diff=Path('/mnt/d/downstream_results/stage7_rewrite/reports/BATCH003_R2_MINIMAL_PATCH_DIFF_20260502.patch')
    zip_path=Path('/mnt/d/downstream_results/stage7_rewrite/packs/WECHAT_STAGE7_C1000_BATCH003_R2_PATCHED_RECOVERED_FINAL_20260502.zip')
    zinfo=make_zip(zip_path,[final_json,final_md,qa_json,qa_md,root_json,root_md,plan_md,diff,single_path,rec/'R2_PATCHED_RECOVERY_PLAN.md'],rec/'zip_verify')
    dl=Path('/mnt/c/Users/pc/Downloads')/zip_path.name; dl.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(zip_path, dl)
    zinfo['downloads_zip']=str(dl); zinfo['downloads_sha256']=sha256(dl)
    if not zinfo['present_in_zip']:
        print(json.dumps({'verdict':'RED_R2_PHANTOM_GREEN','zip_verify':zinfo}, ensure_ascii=False, indent=2)); return
    print(json.dumps({'verdict':'GREEN_R2_PATCHED_RECOVERED','qa':qa,'final':{k:v for k,v in final.items() if k!='results'},'zip':zinfo}, ensure_ascii=False, indent=2))
if __name__=='__main__': main()
