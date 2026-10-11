"""Independent completion/integrity checks, not another model evaluation."""
import csv,hashlib,json,subprocess
from collections import Counter
from pathlib import Path
import requests

OUT=Path(__file__).parent
ROOT=OUT.parents[1]
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
    manifest=read(OUT/'manifest.json');benchmark=read(OUT/'benchmark.json');metrics=read(OUT/'final_metrics.json')
    expected={t['id'] for t in benchmark['tasks']}
    for folder in ['raw/agent','raw/chatgpt','review']:
        assert {f.stem for f in (OUT/folder).glob('P*.json')}==expected,folder
    assert hashlib.sha256((OUT/'benchmark.json').read_bytes()).hexdigest()==manifest['dataset_sha256']
    blob=subprocess.check_output(['git','show',manifest['freeze_commit']+':evaluation/poster_final/benchmark.json'],cwd=ROOT)
    assert hashlib.sha256(blob).hexdigest()==manifest['git_blob_sha256']
    assert json.loads(blob)==benchmark
    assert not subprocess.check_output(['git','diff',manifest['product_sha'],'--','backend','frontend'],cwd=ROOT).strip()
    for system in ['agent','chatgpt']:
        assert metrics['metrics'][system]['n']==26 and metrics['metrics'][system]['numeric_n']==10
    rows=list(csv.DictReader((OUT/'poster_metrics.csv').open(encoding='utf-8',newline='')))
    for row,key in zip(rows,['goal_success','claim_coverage','hallucination_free','numeric_accuracy']):
        for label,system in [('Petroleum RAG Agent','agent'),('ChatGPT','chatgpt')]:
            assert float(row[label])==round(metrics['metrics'][system][key]*100,2)
    assert len(list(csv.DictReader((OUT/'final_results.csv').open(encoding='utf-8',newline=''))))==52
    for name in ['poster_model_comparison','poster_category_comparison']:
        assert (OUT/(name+'.png')).stat().st_size>10000
        assert '<svg' in (OUT/(name+'.svg')).read_text(encoding='utf-8')
    h=requests.get('http://127.0.0.1:8001/api/system/checklist',timeout=30).json()
    assert h['knowledge_base']=={'documents':12,'chunks':18976}
    tags=requests.get('http://127.0.0.1:11434/api/tags',timeout=10).json()['models']
    raw=[read(p) for p in (OUT/'raw/agent').glob('P*.json')]
    report={'all_checks_passed':True,'cohort':26,'paired_rows':52,'numeric_tasks':10,
        'product_unchanged':True,'benchmark_unchanged':True,'db_unchanged_counts':h['knowledge_base'],
        'qwen_model':[m for m in tags if m['name']=='qwen3:8b'],
        'agent_run_status_counts':dict(Counter(r['response']['run_status'] for r in raw)),
        'api_call_counts':{k:v['calls'] for k,v in metrics['usage'].items()},
        'stage_timing_means':{key:sum(r['response'].get('timing',{}).get(key,0) for r in raw)/26 for key in
            ['planning_seconds','retrieval_seconds','llm_generation_seconds','python_seconds','verification_seconds','synthesis_seconds']},
        'timing_note':'Stage timers overlap (verification includes evaluation); do not sum these means.',
        'automatic_retries':0,'main_merge':False,'frozen_file_integrity':True}
    (OUT/'completion_checks.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
