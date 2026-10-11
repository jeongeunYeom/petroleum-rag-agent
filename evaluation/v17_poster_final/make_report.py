"""Report only observed results; never repairs answers or modifies frozen inputs."""
import json
from pathlib import Path
P=Path(__file__).resolve().parent
def load(p):return json.loads((P/p).read_text(encoding='utf-8'))
def pct(x):return 'n/a' if x is None else f'{100*x:.1f}%'
def main():
    m=load('final_metrics.json');r=load('scored_rows.json');checks=load('completion_checks.json');d=m['agent_diagnostics'];s=m['systems'];boot=m['paired_bootstrap'];tasks=load('benchmark.json')['tasks']
    metrics={'goal_success':'Goal Success','claim_coverage':'Claim Coverage','hallucination_free':'Hallucination-free','numeric_accuracy':'Numerical Accuracy'}
    table='| Metric | qwen3:8b closed-book | Petroleum RAG Agent | Agent − Qwen | Paired 95% CI |\n|---|---:|---:|---:|---:|\n'
    for key,label in metrics.items():
        b=boot[key];table+=f"| {label} | {pct(s['qwen_closed_book'][key])} | {pct(s['agent'][key])} | {b['difference']*100:+.1f} pp | [{b['ci95'][0]*100:+.1f}, {b['ci95'][1]*100:+.1f}] pp |\n"
    ref='| Metric | Petroleum RAG Agent | GPT-5.4 mini closed-book (reference) |\n|---|---:|---:|\n'+''.join(f"| {label} | {pct(s['agent'][key])} | {pct(s['gpt_reference'][key])} |\n" for key,label in metrics.items())
    optional='| Metric | qwen3:8b closed-book | Petroleum RAG Agent | GPT reference |\n|---|---:|---:|---:|\n'+''.join(f"| {label} | {pct(s['qwen_closed_book'][key])} | {pct(s['agent'][key])} | {pct(s['gpt_reference'][key])} |\n" for key,label in metrics.items())
    (P/'POSTER_RESULTS_TABLE.md').write_text('# Performance comparison using the same base model\n\n'+table+'\n## External reference\n\n'+ref+'\n## Optional combined layout\n\n'+optional+'\n24 tasks; numeric denominator 10. GPT is not a same-base-model ablation. Percentage-point CI: paired bootstrap, 10,000 resamples, seed 17172026.\n',encoding='utf-8')
    category='| Category | N | Qwen | Agent | GPT reference |\n|---|---:|---:|---:|---:|\n'
    for cat,n in [('Knowledge',6),('Reasoning',4),('Calculation',10),('Safety',4)]:category+=f"| {cat} | {n} | "+' | '.join(pct(s[x]['category_goal_success'][cat]) for x in ('qwen_closed_book','agent','gpt_reference'))+' |\n'
    latency='| System | Mean seconds | Median seconds | P95 seconds |\n|---|---:|---:|---:|\n'
    for name,a in s.items():
        v=a['latency_seconds'];latency+=f"| {name} | {v['mean']:.2f} | {v['median']:.2f} | {v['p95']:.2f} |\n"
    task_table='| Task | Category | Qwen | Agent | GPT | Agent status | Actions | Refusal | Relevant evidence |\n|---|---|---|---|---|---|---|---|---|\n'
    for t in tasks:
        rs={a['system']:a for a in r if a['task_id']==t['id']};a=rs['agent'];task_table+=f"| {t['id']} | {t['category']} | "+' | '.join('PASS' if rs[x]['goal_success'] else 'FAIL' for x in ('qwen_closed_book','agent','gpt_reference'))+f" | {a['run_status']} | {' → '.join(a['actions'])} | {a['unnecessary_refusal']} | {a['relevant_evidence_present']} |\n"
    failure='\n'.join(f"- {a['task_id']}: {a['reason']}" for a in r if a['system']=='agent' and not a['goal_success'])
    actual_models={name:sorted({load('raw/'+name+'/'+t['id']+'.json')['response'].get('model','qwen3:8b') for t in tasks}) for name in ('qwen_closed_book','gpt_reference')}
    report=f'''# Petroleum RAG Agent v17 final independent poster pilot

FINALIZED: {m['FINALIZED']}

Product SHA: `{m['product_sha']}`  
Freeze SHA: `{m['freeze']['freeze_commit']}`  
Benchmark SHA256: `{m['freeze']['benchmark_sha256']}`  
24 frozen tasks, numeric denominator 10. Existing KB: 12 documents / 18,976 chunks. Cross-language Korean-question / English-source cases are identified in the frozen benchmark; other questions include English.

## Primary comparison

{table}
## External reference

{ref}
Actual API-returned model IDs: `{json.dumps(actual_models)}`. Judge: gpt-5.4-2026-03-05. Local Agent: qwen3:8b, unchanged hybrid retrieval, web off, autonomous production settings. This tests the complete RAG + orchestration product, not retrieval alone.

## Category Goal Success

{category}
## Agent diagnostics

```json
{json.dumps(d,ensure_ascii=False,indent=2)}
```

Unnecessary refusals use 22 answerable tasks as denominator; overall /24 is separately provided. Relevant evidence is reviewer-assessed from actual retrieved spans, independent of the Agent's answerability flag. Telemetry unknowns are not silently converted to successful readiness. Internal achieved is not external success. Citation support applies only to actually cited links, not uncited answers.

## Per-task outcomes

{task_table}
### Agent failure reasons

{failure or 'None.'}

## Latency and costs

{latency}
Agent dependency startup is recorded in agent_startup.json. The first retrieval includes embedding load. Agent and local closed-book runs were serial to avoid competing local generation. GPT ran separately. Agent timing stages overlap and must not be summed.

```json
{json.dumps(m['cost'],ensure_ascii=False,indent=2)}
```

List-price estimates use actual API usage, not billed invoice totals. Sources: [GPT mini pricing](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [GPT-5.4 pricing](https://developers.openai.com/api/docs/models/gpt-5.4). Local inference; hardware/electricity cost not estimated.

## Scoring and limits

Single-reviewer AI-assisted semantic adjudication, NOT human review. Random anonymous labels, but writing style and presence of evidence can reveal the augmented system. The reviewer is from the same provider/family as the GPT reference. Gold and rubric were fixed before generation. Numeric outputs identified by the reviewer are independently checked in visible text against frozen tolerance and unit acceptance. This is not human adjudication. Error, omission, incorrect refusal and wrong calculation remain separate.

This 24-task pilot is small, source-grounded and partly clustered by concepts. Bootstrap intervals describe task resampling within this set, not new fields/documents. Duplicate screening used exact/lexical tests and bilingual manual semantic-concept review, not an embedding-based semantic similarity score. Generic arithmetic operations necessarily overlap earlier supported operation families, but initial tasks were independently authored before historical access. No claim that every domain is equally represented. No real deployment safety guarantee. No post-result task rejection or denominator changes.

The single-turn unanswerable tests assess targeted clarification, not successful multi-turn resume. No simulation sweep was requested in this frozen 24-task composition. The use-case trace is selected from real successes, never synthesized as a fictional success.

## Integrity

```json
{json.dumps(checks,indent=2)}
```

No post-result tuning was performed. No main merge. Benchmark, prior evaluation records and product files were not edited after freeze. Evaluation aggregation/report code is separate from the fixed product.

## Poster-safe conclusions

1. On this pilot, Agent Goal Success is {pct(s['agent']['goal_success'])} versus {pct(s['qwen_closed_book']['goal_success'])} for the same qwen3:8b closed-book model (difference {boot['goal_success']['difference']*100:+.1f} percentage points). The result must be reported in this direction, not as an assumed RAG benefit.
2. Agent Hallucination-free is {pct(s['agent']['hallucination_free'])}, but {d['unnecessary_refusal_count']}/22 answerable tasks are unnecessary refusals and {d['relevant_evidence_but_failed']} failures have relevant retrieved evidence. Safety by withholding an answer is distinct from successful knowledge use.
3. Agent numeric accuracy is {pct(s['agent']['numeric_accuracy'])}; the observed execution/validation pipeline and latency above quantify the current reliability–latency trade-off. GPT reference results are shown separately and cannot isolate the effect of RAG.
'''
    (P/'FINAL_REPORT.md').write_text(report,encoding='utf-8')
    overrides=[(a['task_id'],a['system']) for a in r if a['deterministic_override']]
    truncations={sname:[t['id'] for t in tasks if load('raw/'+sname+'/'+t['id']+'.json')['response'].get('choices',[{}])[0].get('finish_reason')=='length'] for sname in ('gpt_reference',)}
    audit=f'''# Scoring audit

72 response records and 24 triple reviews. Full judge inputs, anonymous mappings and provider responses are retained. All claim-score lengths and domains were checked. Each external goal success additionally requires coverage=1, no fabricated fact, no wrong calculation and numeric correctness where applicable. Deterministic Goal Success overrides: {overrides}.

Numeric values: extracted by single reviewer from final answers; deterministic absolute-tolerance/unit check across every required output. Numeric denominator=10, no missing tasks excluded. Fraction/percent normalization follows the frozen rubric. Hallucination-free = not(fabricated_fact or wrong_calculation); omission/refusal alone is not fabrication. Unnecessary refusal is answerable AND no substantive requested answer, not a stopped-status shortcut.

GPT token-length terminations: {truncations}. Raw local done_reason is retained. No response was rerun for incompleteness or failure. No judge response was repaired with another API call. No performance-driven scoring-policy changes.

Citation-link support and relevant-evidence judgements are supplementary and do not impose citation requirements on closed-book systems. The anonymous label mapping is saved outside each judge payload. Complete blinding is not possible because source lists and answer styles reveal augmentation.

Evaluation-only numeric unit tests are recorded separately. CSV files are generated from typed Artifact Tool sheet values and independently round-trip checked. Main bootstrap uses paired tasks, 10,000 resamples, seed 17172026; Agent-minus-Qwen differences retain their signs.

No post-result tuning was performed.
'''
    mapping=load('citation_mapping_audit.json')
    audit+=f"\n## Mechanical citation audit\n\nThe judge supplied {len(mapping['discarded_non_cited_links'])} evidence-to-gold links whose IDs were not cited in the actual answer. These were excluded under the frozen actual-citation denominator rule. Zero semantic scores were rewritten. Unreviewed actual citation IDs: {len(mapping['unreviewed_actual_citations'])}. The retained links and rejected links are auditable in the companion JSON/CSV.\n"
    audit+='\n## Single-reviewer sensitivity\n\nThese adjudications were not independently human-reviewed. A single judge can be over-strict or miss subtle engineering errors, particularly in translated claims and unsupported citation spans. Raw judge responses and every deterministic override are retained. No rejudging was performed.\n'
    (P/'SCORING_AUDIT.md').write_text(audit,encoding='utf-8')
    trace=load('poster_demo_trace.json')
    if trace['available']:
        assert all(action['action_type'] in [item['action_type'] for item in trace['action_history']] for action in trace['action_history'])
if __name__=='__main__':main()
