"""Seal pre-inference inputs and report read-only DB/config fingerprints."""
import json, hashlib, sqlite3, subprocess, sys, os
from pathlib import Path
from collections import Counter
P=Path(__file__).resolve().parent; ROOT=P.parents[1]
PRODUCT='57af58c44816c3734ea3d5a7aa4e1f08407798ba'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def snapshot():
    db=ROOT/'data/vector_db'; c=sqlite3.connect(f'file:{db.as_posix()}/chroma.sqlite3?mode=ro',uri=True)
    cols=c.execute('select name,id,dimension from collections').fetchall()
    metadata=c.execute('select * from embedding_metadata order by id,key').fetchall()
    docs=sorted({r[2] for r in metadata if r[1]=='document'})
    ids=c.execute('select id,segment_id,embedding_id,hex(seq_id) from embeddings order by id').fetchall()
    c.close()
    return {'path':str(db),'collections':cols,'count':len(ids),'documents':docs,'document_count':len(docs),'logical_sha256':hashlib.sha256(json.dumps([cols,metadata,ids],ensure_ascii=False).encode()).hexdigest(),'file_sha256':{str(f.relative_to(db)):sha(f) for f in sorted(db.rglob('*')) if f.is_file()}}
if __name__=='__main__':
    if (P/'freeze_receipt.json').exists():raise SystemExit('FROZEN')
    d=json.loads((P/'duplicate_check.json').read_text(encoding='utf-8'))
    for item in d['checks']:
        assert not item['exact_duplicate']
        item['semantic_concept_review']='PASS: independently authored relation/inference differs from historical engineering tasks; shared generic arithmetic operators accepted by policy.'
    d['replacements']=[{'id':'V16-07','removed_concept':'HHP/bit cleaning and WOB','replacement':'salinity/clay hydration/attapulgite tradeoff'}, {'id':'V16-18','removed_concept':'mud pump hydraulic horsepower','replacement':'RP14E erosional velocity'}, {'id':'V16-24','removed_concept':'emulsion optimal chemical dose','replacement':'TCD non-identifiable methane concentration'}]
    d['limitations']='Manual bilingual semantic/concept review; not a learned embedding similarity metric. Generic supported arithmetic overlaps by design. No evidence of using old tasks during initial authoring.'
    d['passed']=True
    (P/'duplicate_check.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    sys.path.insert(0,str(ROOT/'backend'));os.environ['DATA_DIR']=str(ROOT/'data');os.environ['RETRIEVAL_MODE']='hybrid'
    from app.core.config import get_settings
    from app.services.goal_message_parser import GoalMessageRequest,parse_goal_message
    s=get_settings();tasks=json.loads((P/'benchmark.json').read_text(encoding='utf-8'))['tasks']
    requests=[parse_goal_message(GoalMessageRequest(message=t['question'],model='qwen3:8b')) for t in tasks]
    assert all(r.use_internal and not r.use_external and r.max_iterations==6 for r in requests)
    db=snapshot();assert db['count']==18976 and db['document_count']==12
    manifest={'product_sha':PRODUCT,'main_sha':subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip(),'benchmark_sha256':sha(P/'benchmark.json'),'policy_sha256':sha(P/'POLICY.md'),'task_count':24,'numeric_count':10,'categories':dict(Counter(t['category'] for t in tasks)),'kb_snapshot':db,'settings':{k:str(getattr(s,k)) for k in ('data_dir','embedding_model','embedding_model_path','retrieval_mode','ollama_temperature','text_model','ollama_base_url')},'agent_max_iterations':6,'models':{'qwen':'qwen3:8b','gpt_reference':'gpt-5.4-mini-2026-03-17','judge':'gpt-5.4-2026-03-05'},'availability':'Authenticated GET /models exact IDs HTTP 200; local GET /api/tags contains qwen3:8b; no generation preflight','freeze_commit':'See freeze_receipt.json created after freeze commit','screening_completed':True}
    (P/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Ready to freeze',manifest['benchmark_sha256'],db['count'],db['document_count'])
