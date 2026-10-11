"""Read old questions only for dedup AFTER product freeze. Never read raw answers."""
import ast, hashlib, json, re, subprocess
from pathlib import Path
import numpy as np
import requests

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT).decode('utf-8')
corpus={}
def add(text,source):
    if isinstance(text,str) and 25<=len(text)<=2500:
        corpus.setdefault(text,source)
def walk(value,source):
    if isinstance(value,dict):
        for k,v in value.items():
            if k in {'question','query','message','topic','prompt','user_message','initial_message'}: add(v,source)
            elif isinstance(v,(dict,list)): walk(v,source)
    elif isinstance(value,list):
        for item in value: walk(item,source)
refs=['HEAD','eval/v12-unseen','eval/v13-unseen-v2',*[f'evaluation/final-benchmark-v{x}' for x in range(1,5)]]
files=[]
for ref in refs:
    for file in git('ls-tree','-r','--name-only',ref,'evaluation').splitlines():
        if (file.endswith('.json') and re.search(r'benchmark|heldout|unseen|/dev/',file)
            and not re.search(r'/raw/|/review/|result|metric|manifest|rubric|retrieved|adjudication|same_evidence|poster_final',file)):
            try: walk(json.loads(git('show',f'{ref}:{file}')),f'{ref}:{file}');files.append(f'{ref}:{file}')
            except (ValueError,subprocess.CalledProcessError): pass
for p in (ROOT/'backend/tests').glob('test_*.py'):
    try:
        tree=ast.parse(p.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.Constant) and isinstance(node.value,str) and ('?' in node.value or re.search(r'calculate|compute|explain|determine|계산|설명|구해',node.value,re.I)):
                add(node.value,str(p.relative_to(ROOT)))
    except (ValueError,SyntaxError): pass
tasks=json.loads((OUT/'benchmark.json').read_text(encoding='utf-8'))['tasks']
cache_path=ROOT/'data/cache/v14_poster_dedup.json'
cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
texts=list(corpus)+[t['question'] for t in tasks]
missing=[t for t in texts if hashlib.sha256(t.encode()).hexdigest() not in cache]
print('Corpus',len(corpus),'new',len(tasks),'uncached',len(missing),flush=True)
for i in range(0,len(missing),24):
    batch=missing[i:i+24]
    r=requests.post('http://127.0.0.1:11434/api/embed',json={'model':'qwen3-embedding:0.6b','input':batch,'keep_alive':'5m'},timeout=180)
    r.raise_for_status()
    for text,vector in zip(batch,r.json()['embeddings']): cache[hashlib.sha256(text.encode()).hexdigest()]=vector
    cache_path.parent.mkdir(parents=True,exist_ok=True)
    cache_path.write_text(json.dumps(cache))
    print('Embedded',min(i+24,len(missing)),flush=True)
def matrix(items):
    x=np.array([cache[hashlib.sha256(t.encode()).hexdigest()] for t in items]);return x/np.linalg.norm(x,axis=1,keepdims=True)
old=list(corpus);similarity=matrix([t['question'] for t in tasks])@matrix(old).T
def tokens(s): return set(re.findall(r'[a-z가-힣]+',s.lower()))
rows=[]
for task,sims in zip(tasks,similarity):
    a=tokens(task['question']);lex=[len(a&tokens(b))/max(1,len(a|tokens(b))) for b in old]
    j=int(sims.argmax());k=int(np.argmax(lex))
    rows.append({'id':task['id'],'semantic_max':float(sims[j]),'semantic_source':corpus[old[j]],
        'semantic_question_sha256':hashlib.sha256(old[j].encode()).hexdigest(),
        'lexical_max':lex[k],'lexical_source':corpus[old[k]],
        'flagged':bool(sims[j]>=.86 or lex[k]>=.60)})
within=matrix([t['question'] for t in tasks]);pairs=[]
for i in range(len(tasks)):
    for j in range(i):
        sim=float(within[i]@within[j])
        if sim>=.86:pairs.append({'ids':[tasks[i]['id'],tasks[j]['id']],'similarity':sim})
report={'product_fixed_before_comparison':True,'embedding_model':'qwen3-embedding:0.6b','semantic_threshold':.86,'lexical_jaccard_threshold':.60,'corpus_question_count':len(corpus),'corpus_files':files,'rows':rows,'within_candidates':pairs,'limitations':'Automated similarity screening is not proof of conceptual independence; generic operations can share mathematical structure.'}
(OUT/'duplicate_check.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'flagged':[r for r in rows if r['flagged']],'within':pairs},indent=2),flush=True)
