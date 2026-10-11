"""Post-authoring duplicate screening; no inference, generation, or corpus mutation."""
import ast, json, re, hashlib, subprocess
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
P=Path(__file__).resolve().parent; ROOT=P.parents[1]
tasks=json.loads((P/'benchmark.json').read_text(encoding='utf-8'))['tasks']
if (P/'freeze_receipt.json').exists(): raise SystemExit('Already frozen')
old=[]; files=[]
def walk(obj,path):
    if isinstance(obj,dict):
        for k,v in obj.items():
            if k in ('question','query','prompt','message','goal','topic','user_message') and isinstance(v,str) and 15<len(v)<2500: old.append((path,v))
            elif isinstance(v,(dict,list)):walk(v,path)
    elif isinstance(obj,list):
        for v in obj:walk(v,path)
for path in sorted((ROOT/'evaluation').rglob('*.json')):
    if P in path.parents:continue
    try:walk(json.loads(path.read_text(encoding='utf-8-sig')),str(path.relative_to(ROOT)));files.append(str(path.relative_to(ROOT)))
    except (ValueError,UnicodeError):continue
for path in sorted((ROOT/'backend/tests').glob('*.py')):
    try: tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    except (ValueError,SyntaxError):continue
    files.append(str(path.relative_to(ROOT)))
    for node in ast.walk(tree):
        if isinstance(node,ast.Constant) and isinstance(node.value,str) and 20<len(node.value)<2000:
            old.append((str(path.relative_to(ROOT)),node.value))
seen=set(); old=[x for x in old if not (x[1] in seen or seen.add(x[1]))]
branches=subprocess.check_output(['git','for-each-ref','--format=%(refname:short)','refs/heads'],cwd=ROOT,text=True).splitlines()
for branch in branches:
    if not branch.startswith(('eval/','evaluation/')) or branch=='eval/v16-poster-final':continue
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',branch,'evaluation'],cwd=ROOT,text=True).splitlines()
    for name in names:
        if not name.endswith('.json') or not any(w in Path(name).name.lower() for w in ('benchmark','question','task','case','unseen_eval')):continue
        ref=branch+':'+name
        try:walk(json.loads(subprocess.check_output(['git','show',ref],cwd=ROOT)),ref);files.append(ref)
        except (ValueError,subprocess.CalledProcessError):continue
seen=set(); old=[x for x in old if not (x[1] in seen or seen.add(x[1]))]
for path,q in old:
    if re.search(r'flash|differential liberation|molecular weight|slip velocity|erosional|accelerator|TCD|Penn.State|attapulgite|coiled|벤토|분자량|미끄럼|이수.*염',q,re.I):
        print('CONCEPT',path,q[:180])
normalize=lambda s:re.sub(r'\W+','',s.casefold())
vector=TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),max_features=100000)
x=vector.fit_transform([o[1] for o in old]+[t['question']+' '+ ' '.join(t['required_claims']) for t in tasks])
scores=(x[-24:]@x[:-24].T).toarray()
checks=[]
for t,row in zip(tasks,scores):
    inds=np.argsort(row)[-6:][::-1]
    matches=[{'path':old[i][0],'question':old[i][1],'lexical_cosine':round(float(row[i]),4)} for i in inds]
    exact=any(normalize(t['question'])==normalize(o[1]) for o in old)
    checks.append({'id':t['id'],'exact_duplicate':exact,'top_matches':matches,'semantic_concept_review':'PENDING'})
    print(t['id'],json.dumps(matches[:3],ensure_ascii=False))
result={'authorship_completed_before_history_access':True,'candidate_sha256':hashlib.sha256((P/'benchmark.json').read_bytes()).hexdigest(),'historical_files_scanned':files,'unique_historical_texts':len(old),'method':'Exact normalized match, character TF-IDF cosine, then bilingual manual semantic/concept comparison. No model inference before freeze.','thresholds':{'exact':1.0,'lexical_flag':0.55,'semantic':'same engineering relation AND requested inference/result, even below lexical threshold; generic arithmetic operation alone is not a duplicate'},'checks':checks,'passed':False}
(P/'duplicate_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
