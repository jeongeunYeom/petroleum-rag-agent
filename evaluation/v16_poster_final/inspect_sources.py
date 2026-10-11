"""Read-only pre-freeze KB inventory. No model generation or DB writes."""
import json, sqlite3, sys, os, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
db = sqlite3.connect(f'file:{ROOT.as_posix()}/data/vector_db/chroma.sqlite3?mode=ro', uri=True)
if len(sys.argv) == 1:
    for row in db.execute('select name,sql from sqlite_master'):
        if row[0] in ('collections','embeddings','embedding_metadata','segments'):
            print(row)
    print('COLLECTIONS',db.execute('select * from collections').fetchall())
elif sys.argv[1] == 'models':
    import httpx
    key=os.environ.get('OPENAI_API_KEY')
    if not key:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as reg:
            try: key=winreg.QueryValueEx(reg,'OPENAI_API_KEY')[0]
            except FileNotFoundError: pass
    print('OpenAI key present:',bool(key))
    if key:
        for model in ('gpt-5.4-mini-2026-03-17','gpt-5.4-2026-03-05'):
            r=httpx.get(f'https://api.openai.com/v1/models/{model}',headers={'Authorization':f'Bearer {key}'},timeout=30)
            print(model, r.status_code, r.json().get('id'), r.json().get('error',{}).get('code'))
    r=httpx.get('http://127.0.0.1:11434/api/tags',timeout=10)
    print('Ollama',r.status_code,[m['name'] for m in r.json()['models']])
else:
    rows={}
    for i,key,s,n,f,b in db.execute('select * from embedding_metadata order by id,key'):
        rows.setdefault(i,{})[key]=s if s is not None else n if n is not None else f if f is not None else b
    if sys.argv[1]=='inventory':
        from collections import Counter
        print('ROWS',len(rows));print('KEYS',list(next(iter(rows.values()))))
        print(Counter(m.get('document') for m in rows.values()))
    elif sys.argv[1]=='rows':
        for i in map(int,sys.argv[2:]): print(json.dumps({'row':i,**rows[i]},ensure_ascii=False))
    else:
        terms=sys.argv[1].lower().split('|')
        n=0
        for i,m in rows.items():
            t=m.get('chroma:document','')
            if all(x in t.lower() for x in terms):
                print(json.dumps({'row':i,'document':m.get('document'),'page':m.get('page'),'text':t},ensure_ascii=False))
                n+=1
                if n>=int(sys.argv[2] if len(sys.argv)>2 else 6):break
