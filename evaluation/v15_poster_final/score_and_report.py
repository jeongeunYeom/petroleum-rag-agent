"""Frozen-rule aggregation: no model calls and no mutation of raw/frozen data."""
import hashlib, json, math, re, statistics, subprocess
from collections import Counter
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from run_evaluation import ROOT, REPO, PRODUCT, BASELINE, JUDGE, read, answer, snapshot, assert_frozen

def save(name,data):
    (ROOT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def pct(items):return 100*float(np.mean(items)) if items else None
def summary_latency(values):return dict(mean=statistics.mean(values),median=statistics.median(values),p95=float(np.percentile(values,95)))
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,row))+' |' for row in rows])
def self_check():
    assert abs((7.2+2*3.4)/(1+.6)-8.75)<1e-10
    assert abs(4.6**2-3*4.6+5.8/2-10.26)<1e-10
    assert abs((6.3*2.5+9.45)/(2.5+2)-5.6)<1e-10
    assert (1280+965-185)==2060 and abs((2060/2000-1)*100-3)<1e-10
    assert statistics.median([14,29,17,33,21,26,19])==21
    assert 3.8*410/2==779

def main():
    self_check();freeze=assert_frozen()
    tasks=read(ROOT/'benchmark.json')['tasks'];rows=[];reviews={};raws={};citation_links=[]
    assert len(tasks)==24 and sum(bool(t['numeric_targets']) for t in tasks)==10
    for t in tasks:
        review=read(ROOT/f'review/{t["id"]}.json');assert not review['error']
        body=review['response']['choices'][0]['message']['content']
        judged=json.loads(body);reviews[t['id']]=judged
        for label,system in review['label_mapping'].items():
            raw=read(ROOT/f'raw/{system}/{t["id"]}.json');raws[(t['id'],system)]=raw
            j=judged[label];claim=j['claim_scores']
            assert len(claim)==len(t['required_claims']) and all(x in [0,.5,1] for x in claim),(t['id'],claim)
            outputs=j['numeric_outputs'];assert len(outputs)==len(t['numeric_targets']),(t['id'],outputs)
            numeric_ok=[]
            for gold,got in zip(t['numeric_targets'],outputs):
                value=got['reported_value_in_gold_units']
                ok=(isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
                    and abs(value-gold['value'])<=gold['absolute_tolerance']+1e-10
                    and got['unit_equivalent'] is True and bool(got.get('quote')))
                numeric_ok.append(ok)
            usable=bool(answer(raw,system=='agent').strip()) and not raw.get('error')
            numeric=all(numeric_ok) if numeric_ok else None
            goal=usable and all(x==1 for x in claim) and j['goal_success'] and not j['material_errors'] and numeric is not False
            r=raw['response'] if system=='agent' else {}
            computations=r.get('computations',[]);actions=r.get('action_history',[])
            citations=j.get('citation_audit',[])
            if system=='agent':
                for cite in citations:citation_links.append(dict(task_id=t['id'],**cite))
            row=dict(task_id=t['id'],category=t['category'],group={'knowledge':'Knowledge','reasoning':'Reasoning','direct_calculation':'Calculation','user_formula':'Calculation','kb_formula':'Calculation','false_premise':'Safety','unanswerable':'Safety'}[t['category']],
                system=system,goal_success=int(goal),claim_coverage=float(np.mean(claim)) if usable else 0,
                hallucination_free=int(usable and j['hallucination_free'] and not j['material_errors']),numeric_accuracy=int(numeric) if numeric is not None else None,
                latency_seconds=raw['wall_seconds'],claim_scores=claim,numeric_checks=numeric_ok,numeric_outputs=outputs,
                rationale=j['concise_rationale'],material_errors=j['material_errors'],error=raw.get('error'),
                run_status=r.get('run_status'),internal_status=r.get('status'),iterations=r.get('iterations_completed'),
                python_calls=r.get('python_calls_total'),calculation_executed=bool(r.get('python_calls_total')) if system=='agent' else None,
                validated_calculation=any(c.get('validation_passed') for c in computations) if system=='agent' else None,
                action_sequence=[a.get('action_type') for a in actions],timing=r.get('timing'),telemetry=r.get('telemetry'),
                extractive_fallback_used=r.get('telemetry',{}).get('extractive_fallback_used'),
                diagnostics=j.get('diagnostics',{}),citation_bearing=bool(re.search(r'\[(?:KB|FIG|WEB)\d+\]',answer(raw,True))) if system=='agent' else None,
                citation_links=len(citations),citation_supported=sum(c['source_exists'] and c['semantic_support'] for c in citations))
            rows.append(row)
    save('scored_rows.json',rows)
    keys=['goal_success','claim_coverage','hallucination_free','numeric_accuracy']
    metrics={};categories={}
    for s in ['agent','chatgpt']:
        sr=[r for r in rows if r['system']==s]
        metrics[s]={key:pct([r[key] for r in sr if r[key] is not None]) for key in keys}
        metrics[s]['latency_seconds']=summary_latency([r['latency_seconds'] for r in sr])
        categories[s]={g:pct([r['goal_success'] for r in sr if r['group']==g]) for g in ['Knowledge','Reasoning','Calculation','Safety']}
    paired={};rng=np.random.default_rng(15152026)
    for key in keys:
        delta=[]
        for t in tasks:
            a=next(r for r in rows if r['system']=='agent' and r['task_id']==t['id'])[key]
            b=next(r for r in rows if r['system']=='chatgpt' and r['task_id']==t['id'])[key]
            if a is not None:delta.append(a-b)
        d=np.array(delta)*100;draws=d[rng.integers(0,len(d),(10000,len(d)))].mean(axis=1)
        paired[key]=dict(difference_percentage_points=float(d.mean()),ci95_percentile=list(map(float,np.percentile(draws,[2.5,97.5]))),n=len(d),resamples=10000,seed=15152026)
    usage={}
    for model,folder,prices in [(BASELINE,'raw/chatgpt',(.75,.075,4.5)),(JUDGE,'review',(2.5,.25,15))]:
        items=[read(ROOT/f'{folder}/{t["id"]}.json') for t in tasks]
        tokens=[i['response']['usage'] for i in items if i['response']]
        inp=sum(u['prompt_tokens'] for u in tokens);out=sum(u['completion_tokens'] for u in tokens)
        cached=sum(u.get('prompt_tokens_details',{}).get('cached_tokens',0) for u in tokens)
        usage[model]=dict(calls=len(items),input_tokens=inp,output_tokens=out,cached_input_tokens=cached,
            estimated_list_price_usd=((inp-cached)*prices[0]+cached*prices[1]+out*prices[2])/1e6)
    ar=[r for r in rows if r['system']=='agent']
    total_links=len(citation_links);supported=sum(c['source_exists'] and c['semantic_support'] for c in citation_links)
    supplementary=dict(citation_semantic_support_percent=100*supported/total_links if total_links else None,supported_links=supported,total_links=total_links,
        citation_bearing_responses=sum(r['citation_bearing'] for r in ar),responses=24)
    diagnostics=dict(status_counts=dict(Counter(r['run_status'] for r in ar)),internal_status_counts=dict(Counter(r['internal_status'] for r in ar)),
        iterations_total=sum(r['iterations'] or 0 for r in ar),
        numeric={key:dict(true=sum(r[key] is True for r in ar if r['numeric_accuracy'] is not None),denominator=10) for key in ['calculation_executed','validated_calculation']},
        numeric_judge={k:dict(true=sum(r['diagnostics'].get(k) is True for r in ar if r['numeric_accuracy'] is not None),not_measured=sum(r['diagnostics'].get(k) is None for r in ar if r['numeric_accuracy'] is not None),denominator=10) for k in ['correct_routing','operand_completeness','formula_selected']},
        relevant_evidence_but_goal_failed=[r['task_id'] for r in ar if r['diagnostics'].get('relevant_evidence_retrieved') is True and not r['goal_success']],
        unnecessary_refusal=[r['task_id'] for r in ar if r['diagnostics'].get('unnecessary_refusal') is True],
        extractive_fallback_used=[r['task_id'] for r in ar if r['extractive_fallback_used'] is True],
        extractive_fallback_not_instrumented=[r['task_id'] for r in ar if r['extractive_fallback_used'] is None])
    current=snapshot();before=read(ROOT/'preflight.json')['db']
    attempts={folder:len(list((ROOT/folder).glob('P??.attempt.json'))) for folder in ['raw/agent','raw/chatgpt','review']}
    changed=subprocess.check_output(['git','diff',PRODUCT,'--name-only'],cwd=REPO,text=True).splitlines()
    checks=dict(agent_records=len(list((ROOT/'raw/agent').glob('P??.json')))==24,
        baseline_records=len(list((ROOT/'raw/chatgpt').glob('P??.json')))==24,judge_reviews=len(reviews)==24,
        product_unchanged=all(p.startswith('evaluation/v15_poster_final/') for p in changed),
        benchmark_unchanged=hashlib.sha256((ROOT/'benchmark.json').read_bytes()).hexdigest()==freeze['benchmark_sha256'],
        chroma_counts_unchanged=current['document_counts']==before['document_counts'],chroma_metadata_unchanged=current['metadata_sha256']==before['metadata_sha256'],
        no_automatic_retries=all(v==24 for v in attempts.values()) and all(r['attempts']==1 for r in raws.values()),
        main_unchanged=subprocess.check_output(['git','rev-parse','main'],cwd=REPO,text=True).strip()==read(ROOT/'manifest.json')['main_sha_before'],
        all_collections_usable=all(not r.get('error') for r in raws.values()))
    finalized=all(checks.values());save('completion_checks.json',dict(finalized=finalized,checks=checks,attempt_counts=attempts,db_after=current))
    result=dict(product_sha=PRODUCT,freeze=freeze,tasks=24,numeric_tasks=10,models={'agent':'qwen3:8b','baseline':BASELINE,'judge':JUDGE},
        primary_metrics_percent=metrics,category_goal_success_percent=categories,paired_bootstrap=paired,agent_supplementary=supplementary,
        agent_diagnostics=diagnostics,api_usage=usage,estimated_api_cost_usd=sum(u['estimated_list_price_usd'] for u in usage.values()),finalized=finalized)
    save('final_metrics.json',result);save('citation_links.json',citation_links)
    # Flat typed matrices for artifact-tool CSV exports; raw records remain unchanged.
    flatkeys=['task_id','category','group','system',*keys,'latency_seconds','run_status','internal_status','iterations','python_calls','calculation_executed','validated_calculation','citation_bearing','citation_links','citation_supported','rationale','error']
    matrices={'final_results.csv':[flatkeys]+[[r[k] for k in flatkeys] for r in rows],
        'poster_metrics.csv':[['System','Goal Success %','Claim Coverage %','Hallucination-free %','Numerical Accuracy %','Mean Latency s','Median Latency s','P95 Latency s']]+[[name]+[metrics[s][k] for k in keys]+list(metrics[s]['latency_seconds'].values()) for s,name in [('agent','Petroleum RAG Agent'),('chatgpt','GPT-5.4 mini (Closed-book)')]],
        'poster_category_metrics.csv':[['System','Category','N','Goal Success %']]+[[name,g,n,categories[s][g]] for s,name in [('agent','Petroleum RAG Agent'),('chatgpt','GPT-5.4 mini (Closed-book)')] for g,n in [('Knowledge',6),('Reasoning',4),('Calculation',10),('Safety',4)]],
        'poster_citation_support.csv':[['System','Citation Semantic Support %','Supported Links','Audited Links','Citation-bearing Responses','All Responses']]+[['Petroleum RAG Agent',supplementary['citation_semantic_support_percent'],supported,total_links,supplementary['citation_bearing_responses'],24]]}
    save('csv_matrices.json',matrices)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'svg.fonttype':'none'})
    def plot(name,labels,aa,bb,title,caption):
        fig,ax=plt.subplots(figsize=(11,5.8));x=np.arange(len(labels));w=.34
        for delta,vals,label,color in [(-w/2,aa,'Petroleum RAG Agent','#255A78'),(w/2,bb,'GPT-5.4 mini (Closed-book)','#BC6D35')]:
            bars=ax.bar(x+delta,vals,w,label=label,color=color)
            ax.bar_label(bars,labels=[f'{v:.1f}%' for v in vals],padding=4,fontsize=10,clip_on=False)
        ax.set(ylim=(0,100),ylabel='Performance (%)',xticks=x,xticklabels=labels)
        ax.spines[['top','right']].set_visible(False);ax.set_axisbelow(True);ax.grid(axis='y',alpha=.2)
        fig.suptitle(title,fontsize=15,y=.98);ax.legend(loc='upper center',bbox_to_anchor=(.5,1.18),ncol=2,frameon=False)
        fig.text(.5,.025,caption,ha='center',fontsize=9,color='#444444')
        fig.subplots_adjust(top=.78,bottom=.15,left=.08,right=.98)
        fig.savefig(ROOT/(name+'.png'),dpi=220);fig.savefig(ROOT/(name+'.svg'));plt.close(fig)
    plot('poster_model_comparison',['Goal Success','Claim Coverage','Hallucination-free','Numerical Accuracy'],[metrics['agent'][k] for k in keys],[metrics['chatgpt'][k] for k in keys],
        'Performance Comparison on Final Pilot Benchmark','Independent pilot: 24 tasks; numerical accuracy: 10 tasks. Single-reviewer AI-assisted adjudication.')
    groups=['Knowledge','Reasoning','Calculation','Safety']
    plot('poster_category_comparison',[g+f' (n={n})' for g,n in zip(groups,[6,4,10,4])],[categories['agent'][g] for g in groups],[categories['chatgpt'][g] for g in groups],
        'Goal Success by Task Category','Small, purposive pilot. Categories and scoring criteria frozen before model execution.')
    primary_table=table(['System','Goal Success','Claim Coverage','Hallucination-free','Numerical Accuracy','Median latency (s)'],[[name]+[f'{metrics[s][k]:.2f}%' for k in keys]+[f"{metrics[s]['latency_seconds']['median']:.2f}"] for s,name in [('agent','Petroleum RAG Agent'),('chatgpt','GPT-5.4 mini (Closed-book)')]])
    category_table=table(['Category','Agent GS','GPT GS'],[[g,f"{categories['agent'][g]:.1f}%",f"{categories['chatgpt'][g]:.1f}%"] for g in groups])
    ci_table=table(['Metric','Agent − baseline (pp)','Paired bootstrap 95% CI (pp)','N'],[[k,f"{v['difference_percentage_points']:.2f}",f"[{v['ci95_percentile'][0]:.2f}, {v['ci95_percentile'][1]:.2f}]",v['n']] for k,v in paired.items()])
    wins=[k for k in keys if metrics['agent'][k]>metrics['chatgpt'][k]]
    conclusion=(f"On this independent 24-task pilot, Agent exceeded the closed-book baseline on {', '.join(wins)}. " if wins else 'The closed-book baseline was at least as strong on every primary metric in this independent pilot. ')
    conclusion+=f"Goal Success was {metrics['agent']['goal_success']:.1f}% for Agent and {metrics['chatgpt']['goal_success']:.1f}% for the baseline. These results do not establish population superiority or a causal improvement over earlier, different pilot sets."
    (ROOT/'POSTER_RESULTS_TABLE.md').write_text('# Final pilot results\n\n'+primary_table+'\n\n'+category_table+'\n\n'+conclusion+'\n',encoding='utf-8')
    task_table=table(['Task','Group','Agent GS','GPT GS','Agent status','Actions','Agent seconds'],[[t['id'],next(r['group'] for r in ar if r['task_id']==t['id']),next(r['goal_success'] for r in ar if r['task_id']==t['id']),next(r['goal_success'] for r in rows if r['system']=='chatgpt' and r['task_id']==t['id']),next(r['run_status'] for r in ar if r['task_id']==t['id']),' → '.join(str(x) for x in next(r['action_sequence'] for r in ar if r['task_id']==t['id'])),f"{raws[(t['id'],'agent')]['wall_seconds']:.2f}"] for t in tasks])
    report=f'''# V15 final independent poster pilot

Status: **{'FINALIZED' if finalized else 'NOT FINALIZED'}**

Product `{PRODUCT}`; freeze `{freeze['freeze_commit']}`; benchmark SHA256 `{freeze['benchmark_sha256']}`. 24 frozen tasks, 10 numeric; no invalid tasks. Local qwen3:8b + hybrid, existing 12-document / 18,976-chunk KB; web OFF. Baseline `{BASELINE}`; judge `{JUDGE}`. See POLICY.md for prespecified design and rubric.

## Primary results

{primary_table}

{category_table}

## Statistical uncertainty

{ci_table}

10,000 paired resamples, fixed seed. Small purposive pilot; correlated concepts and reviewer uncertainty are not fully captured by task bootstrap. Claims use a shared frozen rubric; tool/provenance/citation advantages are supplementary, not asymmetrical primary requirements.

## Agent citation support and execution

{json.dumps(supplementary,indent=2)}

{json.dumps(diagnostics,indent=2)}

Citation support denominator is audited citation-to-claim links, NOT all tasks. Uncited responses cannot earn link credit. Diagnostics derive from raw trace plus judge audit; missing instrumentation is not a measured zero. Retrieved-relevant-evidence-but-goal-failed IDs identify current synthesis/orchestration gaps, not a causal comparison to v14.

## Every task (failures retained)

{task_table}

## Latency

Agent mean/median/p95 seconds: {metrics['agent']['latency_seconds']}. Baseline: {metrics['chatgpt']['latency_seconds']}. Includes cold start and polling. Stage timings remain in scored_rows.json. No warm-up inference or successful/failed response rerun.

## API usage and cost

{json.dumps(usage,indent=2)}

Estimated API list-price total: ${result['estimated_api_cost_usd']:.6f}; not an invoice, excludes local hardware/electricity. Pricing references in POLICY.md.

## Independence, limitations and integrity

Candidates preceded access to old task strings. Dedup covered Git-history and local evaluation/development material with exact/lexical/LSA checks and manual concept review. LSA is a limited semantic screen, not proof of no near-duplicate. Generic arithmetic operators and a few within-pilot topics recur. Gold text is the actual stored Chroma extraction; page metadata was not independently revalidated against rendered PDFs. Acoustic depth source relation is expressed verbally. Reasoning tasks may combine paragraphs within one chunk. All prompts are English, so this pilot does not establish Korean performance. No multi-turn resume or figure-viewer evaluation was included. Judge is one AI reviewer from the same provider family as the baseline; answer labels were randomized, but citation attachments can reveal system identity. No human adjudication is claimed. No frozen heldout or older benchmark was rerun or pooled. Product tests/CI were not rerun because no product files changed. Failure rationales and numeric extraction audit remain per-row.

Completion checks: {json.dumps(checks)}

## Poster-safe conclusions

{conclusion}

No post-result tuning was performed.
'''
    (ROOT/'FINAL_REPORT.md').write_text(report,encoding='utf-8')
    audit=table(['Task','System','Claim scores','Numeric checks','Adjudication'],[[r['task_id'],r['system'],str(r['claim_scores']),str(r['numeric_checks']),r['rationale'].replace('|','/').replace('\n',' ')] for r in rows])
    (ROOT/'SCORING_AUDIT.md').write_text('# Scoring audit\n\nSingle-reviewer AI-assisted semantic adjudication; deterministic all-claim, tolerance and denominator checks applied afterward. No response edits or model reruns. Raw judge labels and extracted numeric quotes are retained.\n\n'+audit+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
