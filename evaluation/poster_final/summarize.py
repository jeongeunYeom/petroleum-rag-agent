"""Apply the frozen policy; produce transparent rows, paired CIs and poster graphics."""
import hashlib,json,math,re,statistics
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT=Path(__file__).parent
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def write(name,data): (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def verdict(text):
    clean=text.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
    result=json.loads(clean)
    for value in result.values():
        for key in ['goal_success','hallucination','numeric_accuracy','citation_support']:
            field=value[key]
            if field is None:
                assert key in {'numeric_accuracy','citation_support'}
            elif type(field) is int and field in (0,1):
                value[key]=bool(field)
            elif type(field) is not bool:
                raise ValueError('Invalid binary reviewer field: '+key)
    return result
def numeric_match(answer,target,tolerance):
    # Citations cannot serve as numerical answers; signed decimals/scientific notation.
    answer=re.sub(r'\[(?:KB|FIG|WEB|CALC|USERF)\d+\]','',answer).replace(',','')
    values=[float(x) for x in re.findall(r'(?<![A-Za-z0-9])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',answer)]
    return any(math.isclose(x,target,rel_tol=0,abs_tol=tolerance) for x in values)

def main():
    manifest=read(OUT/'manifest.json');dataset=read(OUT/'benchmark.json');tasks=dataset['tasks']
    assert hashlib.sha256((OUT/'benchmark.json').read_bytes()).hexdigest()==manifest['dataset_sha256']
    rows=[];usage={}
    for task in tasks:
        review=read(OUT/'review'/f"{task['id']}.json");judged=verdict(review['answer'])
        assert set(judged)=={'A','B'}
        for label,system in review['label_to_system'].items():
            score=judged[label];claims=score['claim_scores']
            assert len(claims)==len(task['expected_claims']) and all(x in {0,.5,1} for x in claims)
            raw=read(OUT/'raw'/system/f"{task['id']}.json")
            numeric=task['numeric_answer'] is not None
            lexical=numeric_match(raw['answer'],task['numeric_answer'],task['tolerance']) if numeric else None
            numeric_ok=bool(score['numeric_accuracy'] is True and lexical) if numeric else None
            coverage=statistics.mean(claims)
            success=bool(score['goal_success'] is True and coverage==1 and not score['hallucination'] and (not numeric or numeric_ok))
            citations=bool(re.search(r'\[(?:KB|FIG|WEB)\d+\]',raw['answer']))
            response=raw['response'] if system=='agent' else {}
            rows.append({'id':task['id'],'system':system,'category':task['category'],'goal_success':success,
                'claim_coverage':coverage,'hallucination':score['hallucination'],'hallucination_free':not score['hallucination'],
                'numeric_accuracy':numeric_ok,'numeric_token_match':lexical,'citation_bearing':citations,
                'citation_support':score['citation_support'] if citations and system=='agent' else None,
                'latency_seconds':raw['latency_seconds'],'internal_status':response.get('status'),
                'run_status':response.get('run_status'),'python_calls':response.get('python_calls_total'),
                'validated_calc_count':sum(bool(c.get('validation_passed')) for c in response.get('computations',[])),
                'actions':[a['action_type'] for a in response.get('action_history',[])],
                'reason':score['reason'],'answer':raw['answer']})
    for folder in ['raw/chatgpt','review']:
        for p in (OUT/folder).glob('P*.json'):
            record=read(p);u=record['response']['usage'];model=record['model']
            a=usage.setdefault(model,{'calls':0,'input_tokens':0,'output_tokens':0,'cached_input_tokens':0})
            a['calls']+=1;a['input_tokens']+=u['input_tokens'];a['output_tokens']+=u['output_tokens']
            a['cached_input_tokens']+=u.get('input_tokens_details',{}).get('cached_tokens',0)
    rates={'gpt-5.4-mini-2026-03-17':(.75,.075,4.5),'gpt-5.4-2026-03-05':(2.5,.25,15)}
    for model,u in usage.items():
        ip,cp,op=rates[model]
        u['usage_based_list_price_usd']=((u['input_tokens']-u['cached_input_tokens'])*ip+u['cached_input_tokens']*cp+u['output_tokens']*op)/1e6
    metrics={};categories={};groups={'knowledge':'Knowledge','reasoning':'Reasoning','direct':'Calculation','user_formula':'Calculation','kb_formula':'Calculation','false_premise':'Safety','unanswerable':'Safety'}
    keys=['goal_success','claim_coverage','hallucination_free','numeric_accuracy']
    for system in ['agent','chatgpt']:
        rs=[r for r in rows if r['system']==system]
        metric={k:statistics.mean(float(r[k]) for r in rs if r[k] is not None) for k in keys}
        metric.update(n=len(rs),numeric_n=sum(r['numeric_accuracy'] is not None for r in rs),
            hallucination_rate=statistics.mean(r['hallucination'] for r in rs),
            mean_latency_seconds=statistics.mean(r['latency_seconds'] for r in rs),
            median_latency_seconds=statistics.median(r['latency_seconds'] for r in rs),
            p95_latency_seconds=float(np.percentile([r['latency_seconds'] for r in rs],95)))
        cited=[r for r in rs if r['citation_bearing']]
        if system=='agent':
            metric.update(citation_n=len(cited),citation_support=(statistics.mean(r['citation_support'] is True for r in cited) if cited else None),internal_achieved=sum(r['internal_status']=='achieved' for r in rs))
        metrics[system]=metric
        categories[system]={g:{'n':sum(groups[r['category']]==g for r in rs),'goal_success':statistics.mean(r['goal_success'] for r in rs if groups[r['category']]==g)} for g in ['Knowledge','Reasoning','Calculation','Safety']}
    rng=np.random.default_rng(14026);cis={}
    for key in keys:
        pairs=[]
        for task in tasks:
            pair={r['system']:r[key] for r in rows if r['id']==task['id']}
            if pair['agent'] is not None:pairs.append([float(pair['agent']),float(pair['chatgpt'])])
        x=np.array(pairs);indices=rng.integers(0,len(x),(10000,len(x)));sample=x[indices].mean(axis=1)
        cis[key]={'n':len(x),'agent':np.percentile(sample[:,0],[2.5,97.5]).tolist(),'chatgpt':np.percentile(sample[:,1],[2.5,97.5]).tolist(),'paired_difference_agent_minus_chatgpt':np.percentile(sample[:,0]-sample[:,1],[2.5,97.5]).tolist()}
    total_cost=sum(u['usage_based_list_price_usd'] for u in usage.values())
    final={'manifest':manifest,'metrics':metrics,'categories':categories,'usage':usage,'usage_based_list_price_usd':total_cost,'bootstrap':cis,'invalid_tasks':[],'frozen_tasks':26,'valid_tasks':26}
    write('final_metrics.json',final);write('scored_rows.json',rows)
    headers=['Metric','Petroleum RAG Agent','ChatGPT']
    labels=['Goal Success (%)','Claim Coverage (%)','Hallucination-free (%)','Numerical Accuracy (%)']
    tables={'poster_metrics.csv':[headers]+[[label,*[round(metrics[s][k]*100,2) for s in ['agent','chatgpt']]] for label,k in zip(labels,keys)],
        'poster_category_metrics.csv':[['Category','Petroleum RAG Agent','ChatGPT','Tasks']]+[[g,*[round(categories[s][g]['goal_success']*100,2) for s in ['agent','chatgpt']],categories['agent'][g]['n']] for g in categories['agent']],
        'poster_citation_support.csv':[['Metric','Petroleum RAG Agent','Citation-bearing responses','All tasks']]+[['Citation Semantic Support (%)',None if metrics['agent']['citation_support'] is None else round(metrics['agent']['citation_support']*100,2),metrics['agent']['citation_n'],26]],
        'final_results.csv':[list(rows[0])]+[[json.dumps(v,ensure_ascii=False) if isinstance(v,list) else v for v in r.values()] for r in rows]}
    write('csv_tables.json',tables)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':12,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
    for name,title,xlabels,values in [
        ('poster_model_comparison','Petroleum RAG Agent vs ChatGPT',['Goal\nSuccess','Claim\nCoverage','Hallucination-\nfree','Numerical\nAccuracy'],[[metrics[s][k]*100 for k in keys] for s in ['agent','chatgpt']]),
        ('poster_category_comparison','Performance by Task Type',list(categories['agent']),[[categories[s][g]['goal_success']*100 for g in categories[s]] for s in ['agent','chatgpt']])]:
        fig,ax=plt.subplots(figsize=(10,6));x=np.arange(4);width=.34
        for j,(label,color) in enumerate([('Petroleum RAG Agent','#6355b8'),('ChatGPT','#4c9295')]):
            bars=ax.bar(x+(j-.5)*width,values[j],width,label=label,color=color)
            for bar,value in zip(bars,values[j]):
                ax.text(bar.get_x()+bar.get_width()/2,min(value+1.8,97),f'{value:.1f}',ha='center',va='bottom' if value<94 else 'top',fontsize=11,color='#20202b')
        ax.set(ylim=(0,100),ylabel='Score (%)',xticks=x,xticklabels=xlabels,title=title)
        ax.set_axisbelow(True);ax.grid(axis='y',alpha=.2);ax.legend(loc='upper center',bbox_to_anchor=(.5,1.18),ncol=2,frameon=False)
        fig.subplots_adjust(top=.80,bottom=.2,left=.08,right=.98)
        fig.text(.08,.055,'Frozen pilot: 26 tasks (10 numerical). ChatGPT = gpt-5.4-mini API, closed book.\nSingle-reviewer AI-assisted adjudication; source-authored, facilities-heavy sample.',fontsize=9,color='#555555')
        fig.savefig(OUT/(name+'.png'),dpi=300);fig.savefig(OUT/(name+'.svg'));plt.close(fig)
    table='| Metric | Petroleum RAG Agent | ChatGPT |\n|---|---:|---:|\n'+'\n'.join(f'| {r[0]} | {r[1]:.2f} | {r[2]:.2f} |' for r in tables['poster_metrics.csv'][1:])
    conclusion=('The closed-book ChatGPT API baseline achieved higher answer-level task success than the local petroleum RAG Agent in this small, facilities-heavy pilot; retrieval and tool orchestration did not ensure correct final answers.' if metrics['chatgpt']['goal_success']>metrics['agent']['goal_success'] else
        'The local petroleum RAG Agent achieved higher answer-level task success in this small, facilities-heavy pilot; the sample does not establish broad superiority.' if metrics['agent']['goal_success']>metrics['chatgpt']['goal_success'] else
        'The two systems achieved equal answer-level task success in this small pilot; source traceability is reported separately.')
    (OUT/'POSTER_RESULTS_TABLE.md').write_text('# Final poster pilot results\n\n'+table+'\n\n'+conclusion+'\n\n26 tasks; numerical accuracy n=10. Citation support is supplementary.\n',encoding='utf-8')
    lines=['# Final poster pilot evaluation — v14','',f"Product: `{manifest['product_sha']}`. Freeze: `{manifest['freeze_commit']}`.",f"Dataset SHA256: `{manifest['dataset_sha256']}`.",'','## Main comparison','',table,'',
        'Goal Success is answer-level success under an identical rubric, not the Agent internal status. No citations or tool use are required of the closed-book baseline.','',
        '## Reproducibility and limitations','',
        '- 26 frozen/valid tasks; 0 invalid. Same exact question strings, web off, one generation per system.',
        '- Agent: qwen3:8b, hybrid, 12 documents / 18,976 chunks; autonomous from-message API.',
        '- ChatGPT label: gpt-5.4-mini-2026-03-17 API (not the consumer application).',
        '- Judge: gpt-5.4-2026-03-05; single-reviewer AI-assisted semantic adjudication, not human review.',
        '- Fixed temperature 0 and no tools for API calls. No fallback or automatic retry.',
        '- Source-authored and facilities-heavy sample. Few questions per stratum; no population-wide or causal superiority claim.',
        '- Development: 14 fresh cases / 28 checks; backend regression 1,159 passed. Tests are not held-out performance.',
        '- Existing questions were used only for duplicate screening after product freeze (740 questions; zero flags at frozen thresholds). Automated screening cannot prove conceptual independence.',
        '- Same provider family for baseline and judge may introduce bias. No independent human adjudication.',
        '- Some reviewer judgments are over-strict about additional established details. Hallucination is the single reviewer\'s assessment, not a separately verified factual error rate. See [scoring audit](SCORING_AUDIT.md).',
        '- Binary integer/boolean reviewer fields are normalized without changing raw judgments or making another API call.',
        '- Correct refusal can be hallucination-free while failing an answerable task. Interpret safety together with success and coverage.',
        '- No post-result product, benchmark or policy changes. No main merge.', '', '## Supplementary citation support','',
        f"Agent citation-bearing responses: {metrics['agent']['citation_n']}/26. Semantic support among them: {(str(round(metrics['agent']['citation_support']*100,2))+'%') if metrics['agent']['citation_support'] is not None else 'N/A'}. Internal achieved: {metrics['agent']['internal_achieved']}/26.",'','## Latency','',
        '| System | Mean s | Median s | P95 s |','|---|---:|---:|---:|']
    for s in ['agent','chatgpt']:
        m=metrics[s];lines.append(f"| {s} | {m['mean_latency_seconds']:.2f} | {m['median_latency_seconds']:.2f} | {m['p95_latency_seconds']:.2f} |")
    lines+=['','## Paired bootstrap 95% intervals','', '| Metric | Agent − ChatGPT, percentage points |','|---|---:|']
    for k,c in cis.items():lines.append(f"| {k} | {c['paired_difference_agent_minus_chatgpt'][0]*100:.2f} to {c['paired_difference_agent_minus_chatgpt'][1]*100:.2f} |")
    lines+=['','10,000 paired task resamples, seed 14026; numerical subset n=10.','', '## Per-task adjudication','', '| ID | Category | Agent success | ChatGPT success | Agent finding |','|---|---|---:|---:|---|']
    for t in tasks:
        a=next(r for r in rows if r['id']==t['id'] and r['system']=='agent');b=next(r for r in rows if r['id']==t['id'] and r['system']=='chatgpt')
        lines.append(f"| {t['id']} | {t['category']} | {int(a['goal_success'])} | {int(b['goal_success'])} | {a['reason'].replace('|','/').replace(chr(10),' ')} |")
    lines+=['','## API usage and cost','',f'Usage-based list-price estimate: **${total_cost:.6f} USD**. This is not a provider invoice.', '','```json',json.dumps(usage,indent=2),'```','', '## Poster-safe conclusion','',conclusion,'']
    (OUT/'FINAL_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'metrics':metrics,'cost':total_cost},indent=2))

if __name__=='__main__':main()
