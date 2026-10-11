import hashlib,json,os,subprocess,sys
from collections import Counter
from pathlib import Path
from run_evaluation import ROOT,REPO,PRODUCT,snapshot,write
assert not (ROOT/'freeze_receipt.json').exists()
b=json.loads((ROOT/'benchmark.json').read_text(encoding='utf-8'))
dup=json.loads((ROOT/'duplicate_check.json').read_text(encoding='utf-8'))
assert len(dup['results'])==24 and not any(r['exact_matches'] or r['requires_manual_review'] for r in dup['results'])
notes={
 'P01':'Gas anchor free-gas separation and disposal, distinct from coalescer or gas-lift selection.',
 'P02':'Static gel and mechanical solids removal, distinct from lost circulation/mud-pressure questions.',
 'P03':'Remedial squeeze objectives, distinct from mud/cement contamination and primary cement location.',
 'P04':'PCP elastomer chemistry/decompression, distinct from broad lift selection/gas-lift mechanism.',
 'P05':'NPSH inequality and consequence, not prior general system-property claim.',
 'P06':'Oil-mud water/solids viscosity, not cement contamination or mud hydrostatics.',
 'P07':'Pore-size and retained-water comparison, not capillary-pressure definition/FWL relation.',
 'P08':'Bit balling/WOB/hydraulic trade-offs, not old hydraulic-power subtraction calculation.',
 'P09':'Entrained-air density bias plus cavitation, not mudcake/pressure-gradient tasks.',
 'P10':'Coarse-grid numerical dispersion and pseudo curves, not relative-permeability definition.',
 'P11':'Joint sum and mean of shutdown durations; shared arithmetic primitive, independently authored multi-output context.',
 'P12':'Joint order statistic and length range; shared median primitive, not a numeric-only version of old single median tasks.',
 'P13':'Captured/flared gas disposition ratio, not porosity definition or old production ranking.',
 'P14':'Replaced simple decrease template prefreeze with net invoices after credit plus budget overrun.',
 'P15':'New three-input rational expression and distinct variable names, not prior two-input dilution formula.',
 'P16':'New quadratic-plus-offset expression and distinct variable names, not prior squared-difference formula.',
 'P17':'New bilinear rational expression and variable names, not volume product or dilution formula.',
 'P18':'Pressure-flow hydraulic output, distinct from old hydraulic-loss subtraction and shaft efficiency formulas.',
 'P19':'Acoustic round-trip fluid depth, distinct from gas-lift pressure inequality or hydrostatic pressure.',
 'P20':'Circulation pressure loss by surface-minus-bit, distinct from old horsepower loss or vertical-lift component sum.',
 'P21':'False inference from unchanged saturation to resistivity; not prior figure-zone/symbol identification.',
 'P22':'Oil-emulsion phase reversal, not pressure-window false premises or contact-angle claim.',
 'P23':'PCP aromatic/elastomer concentration limit and missing test conditions, not CO2 density/inhibitor dosage.',
 'P24':'Minimum liquid level from NPSH with missing system/pump data, not a generic NPSHA definition.'}
for row in dup['results']:row['manual_concept_review']={'decision':'retain','reason':notes[row['id']]}
dup['final_decision']='24 retained; 0 exact or threshold near-duplicates; all nearest neighbours reviewed after authorship; no inference used.'
dup['prefreeze_changes']=['P14 replaced to avoid a simple percentage-change template.','User-model identifiers made distinct from older model variables.']
(ROOT/'duplicate_check.json').write_text(json.dumps(dup,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
os.environ['DATA_DIR']=str(REPO/'data');os.environ['RETRIEVAL_MODE']='hybrid';os.environ['TEXT_MODEL']='qwen3:8b'
sys.path.insert(0,str(REPO/'backend'))
from app.core.config import Settings
s=Settings()
settings={k:str(getattr(s,k)) for k in ['data_dir','vector_db_dir','embedding_model','embedding_model_path','retrieval_mode','text_model','collection_name','ollama_base_url']}
write(ROOT/'runtime_settings.json',settings)
manifest=dict(product_sha=PRODUCT,branch='eval/v15-poster-final',benchmark_sha256=hashlib.sha256((ROOT/'benchmark.json').read_bytes()).hexdigest(),
    freeze_commit='Recorded in freeze_receipt.json immediately after the freeze commit, before inference.',
    task_count=24,numeric_task_count=10,category_distribution=dict(Counter(t['category'] for t in b['tasks'])),
    source_page_distribution=dict(Counter(f"{s['source_document']}:{s['source_page']}" for t in b['tasks'] for s in t['sources'])),
    main_sha_before=subprocess.check_output(['git','rev-parse','main'],cwd=REPO,text=True).strip(),
    kb_before=snapshot(),dedup_prior_texts=dup['prior_unique_texts'],policy='POLICY.md',
    inference_before_freeze=False,first_model_call='Only after freeze_receipt.json and successful preflight',
    caveat='No automated dedup method proves complete novelty. Shared arithmetic primitives are retained; known task-level duplicates removed before freeze.')
write(ROOT/'manifest.json',manifest)
print('READY TO FREEZE',manifest['benchmark_sha256'])
