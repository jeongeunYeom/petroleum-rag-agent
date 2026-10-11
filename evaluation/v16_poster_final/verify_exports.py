"""Independent stdlib CSV round-trip and frozen artifact completeness check."""
import csv,json,math
from pathlib import Path
P=Path(__file__).resolve().parent
tables=json.loads((P/'table_data.json').read_text(encoding='utf-8'))
result={}
for name,expected in tables.items():
    with (P/name).open(encoding='utf-8',newline='') as f:actual=list(csv.reader(f))
    assert len(actual)==len(expected),name
    for got,want in zip(actual,expected):
        assert len(got)==len(want),name
        for value,target in zip(got,want):
            if target is None:assert value==''
            elif isinstance(target,bool):assert value==str(target).lower()
            elif isinstance(target,(int,float)):assert math.isclose(float(value),target,abs_tol=1e-12)
            else:assert value==str(target)
    result[name]={'data_rows':len(actual)-1,'columns':len(actual[0]),'round_trip_passed':True}
required=['benchmark.json','POLICY.md','manifest.json','duplicate_check.json','freeze_receipt.json','scored_rows.json','final_metrics.json','FINAL_REPORT.md','POSTER_RESULTS_TABLE.md','SCORING_AUDIT.md','completion_checks.json','poster_demo_trace.md','poster_demo_trace.json',*tables]
assert all((P/f).exists() for f in required)
result['required_artifacts_exist']=True
(P/'export_verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
