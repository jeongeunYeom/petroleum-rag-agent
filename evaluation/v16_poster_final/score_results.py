"""Frozen-policy aggregation; no model calls, no task changes, raw records immutable."""
import json,re,math,statistics,hashlib,subprocess
from collections import Counter
from pathlib import Path
import numpy as np
from freeze import snapshot,sha,PRODUCT
P=Path(__file__).resolve().parent;ROOT=P.parents[1]
def load(p):return json.loads((P/p).read_text(encoding='utf-8'))
def save(p,data):(P/p).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def mean(xs):return float(np.mean(xs)) if xs else None
def summaries(xs):return {'mean':mean(xs),'median':float(np.median(xs)),'p95':float(np.percentile(xs,95))}
def numeric_ok(task,a):
    if task['numeric_gold'] is None:return None
    outputs=a.get('numeric_outputs',{})
    return bool(a.get('units_correct') is True and all(isinstance(outputs.get(k),(int,float)) and not isinstance(outputs.get(k),bool) and math.isfinite(outputs[k]) and abs(outputs[k]-v)<=task['tolerance'] for k,v in task['numeric_gold'].items()))
def route_ok(t,r):
    actions=[a['action_type'] for a in r.get('action_history',[]) if a['action_type']!='stop']
    if t['category'] in ('direct_calculation','user_formula'):return bool(actions and actions[0] in ('calculate','simulate'))
    if t['category']=='kb_formula':return 'retrieve' in actions and any(a in actions for a in ('calculate','simulate')) and actions.index('retrieve')<min(actions.index(a) for a in ('calculate','simulate') if a in actions)
    return None
def main():
    tasks=load('benchmark.json')['tasks'];manifest=load('manifest.json');systems=['qwen_closed_book','agent','gpt_reference'];rows=[];raws={};audits={}
    for t in tasks:
        review=load('review/'+t['id']+'.json');assert 'error' not in review
        judge=review['judgement'];assert len(judge['assessments'])==3
        labels=review['labels'];assert len({a['label'] for a in judge['assessments']})==3
        audits[t['id']]=judge['evidence_audit']
        for a in judge['assessments']:
            system=labels[a['label']];raw=load('raw/'+system+'/'+t['id']+'.json');assert 'error' not in raw
            assert raw['question']==t['question'];raws[(system,t['id'])]=raw
            scores=a['claim_scores'];assert len(scores)==len(t['required_claims']) and all(v in (0,0.5,1) for v in scores)
            correct=numeric_ok(t,a);coverage=mean(scores)
            fabricated=bool(a['fabricated_fact']);wrong=bool(a['wrong_calculation'])
            goal=bool(a['goal_success'] and coverage==1 and not fabricated and not wrong and correct is not False)
            row={'task_id':t['id'],'system':system,'category':t['category'],'answerable':t['answerable'],'goal_success':goal,'claim_coverage':coverage,'hallucination_free':not(fabricated or wrong),'numeric_accuracy':correct,'fabricated_fact':fabricated,'wrong_calculation':wrong,'incorrect_refusal':bool(a['incorrect_refusal']),'omission':bool(a['omission']),'unnecessary_refusal':bool(t['answerable'] and a['refusal']),'latency_seconds':raw['latency_seconds'],'reason':a['reason'],'judge_goal_success':a['goal_success'],'deterministic_override':goal!=a['goal_success']}
            if system=='agent':
                resp=raw['response'];tel=resp.get('telemetry',{});audit=audits[t['id']]
                row.update(run_status=resp['run_status'],internal_status=resp['status'],iterations=resp['iterations_completed'],actions=[x['action_type'] for x in resp['action_history']],python_calls=resp['python_calls_total'],relevant_evidence_present=bool(audit['relevant_evidence_present']),non_refusal_final_answer=bool(audit['non_refusal_final_answer']),correct_route=route_ok(t,resp),citation_bearing=bool(re.search(r'\[(?:KB|FIG|WEB)\d+\]',raw['answer'])))
                for k in ('claim_support_checked','supported_claim_count','answerability_status','extractive_fallback_attempted','extractive_fallback_used','extractive_fallback_failure_reason','final_answer_kind','operands_expected','operands_bound','operand_validation_passed','formula_ready','calculation_ready','calculation_executed','calculation_validated'):row[k]=tel.get(k)
            rows.append(row)
    metrics={};groups={'knowledge':'Knowledge','reasoning':'Reasoning','direct_calculation':'Calculation','user_formula':'Calculation','kb_formula':'Calculation','false_premise':'Safety','unanswerable':'Safety'}
    common=['goal_success','claim_coverage','hallucination_free','numeric_accuracy']
    for system in systems:
        rs=[r for r in rows if r['system']==system]
        metrics[system]={k:mean([float(r[k]) for r in rs if r[k] is not None]) for k in common}
        metrics[system]['counts']={k:sum(bool(r[k]) for r in rs) for k in ('goal_success','hallucination_free','numeric_accuracy','unnecessary_refusal','fabricated_fact','incorrect_refusal','omission','wrong_calculation')}
        metrics[system]['latency_seconds']=summaries([r['latency_seconds'] for r in rs])
        metrics[system]['category_goal_success']={g:mean([float(r['goal_success']) for r in rs if groups[r['category']]==g]) for g in dict.fromkeys(groups.values())}
    ag=[r for r in rows if r['system']=='agent'];nums=[r for r in ag if r['numeric_accuracy'] is not None]
    links=[];discarded_links=[];unreviewed_citations=[]
    for i,a in audits.items():
        actual=set(re.findall(r'\[((?:KB|FIG|WEB)\d+)\]',raws['agent',i]['answer']))
        reviewed=set()
        for link in a.get('citation_links',[]):
            item=dict(task_id=i,**link)
            if link['citation_id'].strip('[]') in actual:
                links.append(item);reviewed.add(link['citation_id'].strip('[]'))
            else:discarded_links.append(item)
        unreviewed_citations.extend({'task_id':i,'citation_id':cid} for cid in actual-reviewed)
    save('citation_mapping_audit.json',{'discarded_non_cited_links':discarded_links,'unreviewed_actual_citations':unreviewed_citations,'policy':'Only actual citation IDs present in final answer are eligible; no semantic score edited.'})
    for link in links:assert link['support_score'] in (0,0.5,1)
    diag={'status_counts':dict(Counter(r['run_status'] for r in ag)),'internal_achieved':sum(r['internal_status']=='achieved' for r in ag),'mean_iterations':mean([r['iterations'] for r in ag]),'unnecessary_refusal_count':sum(r['unnecessary_refusal'] for r in ag),'unnecessary_refusal_rate_answerable':sum(r['unnecessary_refusal'] for r in ag)/22,'unnecessary_refusal_rate_all':sum(r['unnecessary_refusal'] for r in ag)/24,'relevant_evidence_but_failed':sum(r['relevant_evidence_present'] and not r['goal_success'] for r in ag),'relevant_evidence_count':sum(r['relevant_evidence_present'] for r in ag),'relevant_to_non_refusal_count':sum(r['relevant_evidence_present'] and r['non_refusal_final_answer'] for r in ag),'fallback_attempted':sum(r['extractive_fallback_attempted'] is True for r in ag),'fallback_used':sum(r['extractive_fallback_used'] is True for r in ag),'fallback_successful_finalization':sum(r['extractive_fallback_used'] is True and r['goal_success'] for r in ag),'citation_bearing_responses':sum(r['citation_bearing'] for r in ag),'citation_link_count':len(links),'citation_semantic_support':mean([l['support_score'] for l in links]),'numeric_pipeline':{k:sum(r[k] is True for r in nums) for k in ('correct_route','operand_validation_passed','formula_ready','calculation_ready','calculation_executed','calculation_validated','numeric_accuracy')},'numeric_pipeline_unknown':{k:sum(r[k] is None for r in nums) for k in ('correct_route','operand_validation_passed','formula_ready','calculation_ready','calculation_executed','calculation_validated')},'timing_stage_mean_seconds':{k:mean([raws[('agent',t['id'])]['response']['timing'].get(k,0) for t in tasks]) for k in ('message_parsing_seconds','planning_seconds','retrieval_seconds','llm_generation_seconds','python_seconds','verification_seconds','evaluation_seconds','synthesis_seconds')},'stage_times_overlap':True}
    diag['relevant_to_non_refusal_rate']=diag['relevant_to_non_refusal_count']/diag['relevant_evidence_count'] if diag['relevant_evidence_count'] else None
    paired={};by={(r['system'],r['task_id']):r for r in rows}
    for k in common:
        ids=[t['id'] for t in tasks if k!='numeric_accuracy' or t['numeric_gold'] is not None]
        diffs=np.array([float(by['agent',i][k])-float(by['qwen_closed_book',i][k]) for i in ids]);rng=np.random.default_rng(16161012)
        means=diffs[rng.integers(0,len(ids),size=(10000,len(ids)))].mean(axis=1)
        paired[k]={'difference':float(diffs.mean()),'ci95':np.percentile(means,[2.5,97.5]).tolist(),'n':len(ids),'resamples':10000,'seed':16161012}
    costs={}
    for system in ('gpt_reference','judge'):
        paths=list((P/('raw/gpt_reference' if system=='gpt_reference' else 'review')).glob('*.json'));u={'calls':len(paths),'input_tokens':0,'output_tokens':0,'cached_tokens':0}
        for path in paths:
            item=json.loads(path.read_text(encoding='utf-8'));usage=item['response'].get('usage',{});u['input_tokens']+=usage.get('prompt_tokens',0);u['output_tokens']+=usage.get('completion_tokens',0);u['cached_tokens']+=usage.get('prompt_tokens_details',{}).get('cached_tokens',0)
        pi,po,pc=(.75,4.5,.075) if system=='gpt_reference' else (2.5,15,.25)
        u['estimated_usd']=((u['input_tokens']-u['cached_tokens'])*pi+u['output_tokens']*po+u['cached_tokens']*pc)/1e6;costs[system]=u
    costs['local']='Local inference; hardware/electricity cost not estimated'
    db=snapshot();save('kb_after.json',db)
    checks={'responses_complete':all(len(list((P/'raw'/s).glob('*.json')))==24 for s in systems),'judging_complete':len(list((P/'review').glob('*.json')))==24,'product_unchanged':not bool(subprocess.check_output(['git','diff',PRODUCT,'--','backend','frontend'],cwd=ROOT)),'benchmark_unchanged':sha(P/'benchmark.json')==manifest['benchmark_sha256'],'policy_unchanged':sha(P/'POLICY.md')==manifest['policy_sha256'],'chroma_logical_unchanged':db['logical_sha256']==manifest['kb_snapshot']['logical_sha256'],'chroma_files_unchanged':db['file_sha256']==manifest['kb_snapshot']['file_sha256'],'no_automatic_retries':all(load(str(p.relative_to(P)))['attempt']==1 for p in (P/'attempts').rglob('*.json')),'exact_questions_identical':all(raw['question']==next(t['question'] for t in tasks if t['id']==i) for (s,i),raw in raws.items()),'no_post_result_tuning':True,'main_unchanged':subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()==manifest['main_sha']}
    checks['actual_citations_reviewed']=not unreviewed_citations
    save('completion_checks.json',{'FINALIZED':all(checks.values()),**checks});save('scored_rows.json',rows)
    save('final_metrics.json',{'FINALIZED':all(checks.values()),'tasks':24,'numeric_tasks':10,'systems':metrics,'agent_diagnostics':diag,'paired_bootstrap':paired,'cost':costs,'product_sha':PRODUCT,'freeze':load('freeze_receipt.json')})
    headers=list(dict.fromkeys(k for r in rows for k in r))
    tables={'final_results.csv':[headers]+[[r.get(k) for k in headers] for r in rows],'poster_rag_effect.csv':[['Metric','Qwen closed-book %','Agent %','Difference pp','CI95 low pp','CI95 high pp']]+[[k,metrics['qwen_closed_book'][k]*100,metrics['agent'][k]*100,paired[k]['difference']*100,*[v*100 for v in paired[k]['ci95']]] for k in common],'poster_reference_metrics.csv':[['Metric','Agent %','GPT reference %']]+[[k,metrics['agent'][k]*100,metrics['gpt_reference'][k]*100] for k in common],'poster_category_metrics.csv':[['Category','N','Qwen %','Agent %','GPT reference %']]+[[g,{'Knowledge':6,'Reasoning':4,'Calculation':10,'Safety':4}[g],*[metrics[s]['category_goal_success'][g]*100 for s in systems]] for g in ('Knowledge','Reasoning','Calculation','Safety')],'poster_agent_diagnostics.csv':[['Metric','Value']]+[[k,json.dumps(v,ensure_ascii=False) if isinstance(v,dict) else v] for k,v in diag.items()],'poster_citation_support.csv':[['task_id','citation_id','claim','support_score','reason']]+[[l.get(k) for k in ('task_id','citation_id','claim','support_score','reason')] for l in links]}
    tables['final_results.csv']=[headers]+[[json.dumps(r.get(k),ensure_ascii=False) if isinstance(r.get(k),(list,dict)) else r.get(k) for k in headers] for r in rows]
    flat=[]
    for k,v in diag.items():
        if isinstance(v,dict):flat.extend([[k+'.'+name,value] for name,value in v.items()])
        else:flat.append([k,v])
    tables['poster_agent_diagnostics.csv']=[['Metric','Value']]+flat
    save('table_data.json',tables)
    demo=[r for r in ag if r['goal_success'] and r['citation_bearing'] and len([a for a in r['actions'] if a not in ('stop',)])>=2]
    demo.sort(key=lambda r:('calculate' in r['actions'],len(set(r['actions']))),reverse=True)
    if demo:
        row=demo[0];r=raws['agent',row['task_id']]['response'];trace={'available':True,'task_id':row['task_id'],'user_goal':r['topic'],'action_history':r['action_history'],'iterations':r['iterations_completed'],'retrieved_evidence_count':len(r['internal_sources'])+len(r['figures']),'state_history':r['state_history'],'computations':r['computations'],'final_answer':r['final_answer'],'internal_sources':r['internal_sources'],'figures':r['figures'],'stop_reason':r['stop_reason'],'final_status':r['run_status']}
        md=f"# Actual successful Agent trace — {row['task_id']}\n\nUser goal: {r['topic']}\n\nActions: {' → '.join(row['actions'])}\n\nIterations: {r['iterations_completed']}; evidence: {trace['retrieved_evidence_count']}; status: {r['run_status']}; stop: {r['stop_reason']}\n\n{r['final_answer']}\n\nNo actions were invented. Detailed evidence, calculations and coverage progression are in the companion JSON.\n"
    else:trace={'available':False,'reason':'No externally successful citation-bearing task with at least two meaningful actions. A fictional success trace was not created.'};md='# Poster demo trace unavailable\n\n'+trace['reason']+'\n'
    save('poster_demo_trace.json',trace);(P/'poster_demo_trace.md').write_text(md,encoding='utf-8')
    print(json.dumps({'systems':metrics,'diagnostics':diag,'bootstrap':paired,'integrity':checks,'cost':costs,'demo':trace.get('task_id')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
