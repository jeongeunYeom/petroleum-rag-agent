"""Self-checks for numerical backstop and frozen cohort accounting."""
import importlib.util,json
from pathlib import Path

HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('poster_summary',HERE/'summarize.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_numeric_backstop():
    assert module.numeric_match('PB = 60 hp [CALC1]',60,.005)
    assert not module.numeric_match('No supported result [KB60]',60,.005)
    assert not module.numeric_match('PB = 6 hp',60,.005)
    assert module.numeric_match('The result is 1.66667e-1 in.',1/6,.005)

def test_cohort():
    tasks=json.loads((HERE/'benchmark.json').read_text(encoding='utf-8'))['tasks']
    assert len(tasks)==26 and len({r['id'] for r in tasks})==26
    assert sum(r['numeric_answer'] is not None for r in tasks)==10
    assert sum(not r['answerable'] for r in tasks)==2
    for task in tasks:
        assert task['expected_claims'] and task['reference_answer']
        assert all(s['page']>0 and s['text'] for s in task['sources'])

def test_reviewer_binary_representation_not_regraded():
    for positive in [True,1]:
        value={'goal_success':positive,'hallucination':0,'numeric_accuracy':positive,'citation_support':None}
        parsed=module.verdict(json.dumps({'A':value}))['A']
        assert parsed['goal_success'] is True and parsed['numeric_accuracy'] is True
        assert parsed['hallucination'] is False and parsed['citation_support'] is None
