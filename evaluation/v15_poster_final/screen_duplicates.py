"""Post-authoring, offline non-generative screening across repository refs/files."""
import ast, hashlib, json, re, subprocess
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]
assert not (ROOT/'freeze_receipt.json').exists()
new=json.loads((ROOT/'benchmark.json').read_text(encoding='utf-8'))['tasks']
corpus={}
keys={'question','prompt','message','topic','goal','user_message','initial_message','query','user_question'}
def accept(s,ref):
    if isinstance(s,str) and 30<len(s)<2500 and len(s.split())>4:
        corpus.setdefault(s,[]).append(ref)
def walk(obj,ref):
    if isinstance(obj,dict):
        for k,v in obj.items():
            if k in keys:accept(v,ref)
            if isinstance(v,(list,dict)):walk(v,ref)
    elif isinstance(obj,list):
        for v in obj:walk(v,ref)
def extract(text,path,ref):
    try:
        if path.endswith('.json'):walk(json.loads(text),ref)
        elif path.endswith('.jsonl'):
            for line in text.splitlines():walk(json.loads(line),ref)
        elif path.endswith('.py'):
            for node in ast.walk(ast.parse(text)):
                if isinstance(node,ast.Constant):accept(node.value,ref)
    except (ValueError,SyntaxError):pass

objects=subprocess.check_output(['git','rev-list','--objects','--all'],cwd=REPO,text=True).splitlines()
blobs=[]
for entry in objects:
    oid,_,path=entry.partition(' ')
    if ('evaluation/' in path or 'test' in path or '/dev' in path or 'benchmark' in path) and path.endswith(('.json','.jsonl','.py')) and 'v15_poster_final' not in path:
        blobs.append((oid,path))
batch=subprocess.Popen(['git','cat-file','--batch'],cwd=REPO,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
for oid,path in blobs:
    batch.stdin.write((oid+'\n').encode());batch.stdin.flush()
    header=batch.stdout.readline().decode().strip().split()
    raw=batch.stdout.read(int(header[-1]));batch.stdout.read(1)
    extract(raw.decode('utf-8',errors='replace'),path,f'git:{oid}:{path}')
batch.stdin.close();batch.wait()
local_count=0
for folder in [REPO/'evaluation',REPO/'backend/tests',REPO/'backend/scripts']:
    for path in folder.rglob('*'):
        if path.suffix in {'.json','.jsonl','.py'} and ROOT not in path.parents and path.stat().st_size<50000000:
            extract(path.read_text(encoding='utf-8',errors='replace'),str(path),str(path.relative_to(REPO)))
            local_count+=1
old=list(corpus)
texts=old+[t['question'] for t in new]
def canonical(s):return re.sub(r'[^\w]+',' ',s.lower()).strip()
word=TfidfVectorizer(ngram_range=(1,2),sublinear_tf=True,max_features=50000).fit_transform(texts)
char=TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),max_features=50000,sublinear_tf=True).fit_transform(texts)
lsa=normalize(TruncatedSVD(n_components=min(192,word.shape[0]-1),random_state=1515).fit_transform(word))
out=[]
for i,t in enumerate(new):
    j=len(old)+i
    lexical=np.maximum((word[j]@word[:len(old)].T).toarray()[0],(char[j]@char[:len(old)].T).toarray()[0])
    semantic=lsa[:len(old)]@lsa[j]
    def nearest(scores):
        ix=np.argsort(scores)[-3:][::-1]
        return [dict(score=round(float(scores[k]),5),question=old[k],references=corpus[old[k]][:3]) for k in ix]
    out.append(dict(id=t['id'],exact_matches=[corpus[s][:3] for s in old if canonical(s)==canonical(t['question'])],
                    lexical=nearest(lexical),semantic_lsa=nearest(semantic),
                    requires_manual_review=bool(max(lexical)>=0.55 or max(semantic)>=0.80)))
report=dict(method='Post-authoring exact normalized text, word/bigram and character TF-IDF cosine, semantic latent semantic analysis (192-dimensional TF-IDF SVD), plus manual concept review. No generative or embedding-model call before freeze.',
    limitations='LSA is weaker than multilingual neural semantic embeddings. Low similarity is not proof of independence; concept review is also required. Shared mathematical operators alone are not duplicates.',
    lexical_threshold=0.55,semantic_threshold=0.80,git_blob_count=len(blobs),local_files_scanned=local_count,
    prior_unique_texts=len(old),corpus_sha256=hashlib.sha256('\n'.join(sorted(old)).encode()).hexdigest(),results=out)
(ROOT/'duplicate_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('CORPUS',len(old),'BLOBS',len(blobs),'LOCAL',local_count)
for row in out:
    print(row['id'],row['lexical'][0]['score'],row['semantic_lsa'][0]['score'],row['requires_manual_review'])
    print(' lexical:',row['lexical'][0]['question'][:450])
    print(' semantic:',row['semantic_lsa'][0]['question'][:450])
