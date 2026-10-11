"""Fresh synthetic development probes; not a held-out performance estimate."""
import asyncio
import json
import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import GoalResearchRequest
from app.services.goal_intent import classify_goal_intent, user_equation
from app.services.user_fact_registry import UserFactRegistry
from app.services.goal_simulation import run_direct_arithmetic, run_user_formula_calculation, direct_operation_operands
from app.services.calculation_request_ir import parse_request_ir
from app.services.citation_semantics import ground_research_claims
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_execution_state import GoalExecutionState


CASES = [
    ('start pressure=860 psi; end pressure=730 psi; year=2041. Find the difference: start pressure minus end pressure.', 'direct_calc'),
    ('initial=64 psi; final=80 psi. What is the percentage increase?', 'direct_calc'),
    ('motor=14 kW; duration=3 h. Determine energy use.', 'direct_calc'),
    ('A=26 psi; B=38 psi; noise=200 psi. Find the average of A and B.', 'direct_calc'),
    ('q=165 stb/d; Pinj=2900 psi; Pres=2600 psi. J=q/(Pinj-Pres). Find J.', 'user_formula_calc'),
    ('porosity 0.23; bulk_volume=640 m3. PV=porosity*bulk_volume. 구해줘.', 'user_formula_calc'),
    ('power=18 kW; power factor 0.75. active=power*power_factor. Compute active.', 'user_formula_calc'),
    ('Use the textbook equation to calculate fluid compressibility.', 'kb_formula_calc'),
    ('교재의 식을 찾아 수직응력을 계산해줘.', 'kb_formula_calc'),
    ('Explain why average reservoir pressure at 2700 psi is not a local well pressure.', 'knowledge_qa'),
    ('Describe the purpose of a capillary end correction.', 'knowledge_qa'),
    ('다상 유동에서 상대투과도의 의미를 설명해줘.', 'knowledge_qa'),
    ('Can I assume cement always eliminates every migration pathway?', 'premise_check'),
    ('Determine fracture aperture.', 'direct_calc'),
]


@pytest.mark.parametrize('text,route', CASES)
def test_fresh_routes(text, route):
    request = GoalResearchRequest(topic=text, goal=text)
    facts = UserFactRegistry.from_topic(text)
    assert classify_goal_intent(request, has_user_facts=bool(facts.records)).kind.value == route


@pytest.mark.parametrize('a,b', [(860,730),(940,810)])
@pytest.mark.parametrize('verb', ['Find','Compute','Determine'])
def test_named_difference_ignores_distractor(tmp_path, a, b, verb):
    text = f'start pressure={a} psi; end pressure={b} psi; year=2041. {verb} the difference: start pressure minus end pressure.'
    request = GoalResearchRequest(topic=text, goal=text, allow_python_execution=True, python_execution_approved=True)
    facts = UserFactRegistry.from_topic(text).named_operands(text,['difference'])
    order, missing = direct_operation_operands(text,facts,['difference'])
    assert not missing and len(facts.records)==2
    calc=asyncio.run(run_direct_arithmetic(Settings(data_dir=tmp_path),request,'dev-difference',facts,['difference'],'CALC1',order))
    assert calc.validation_passed
    assert any(row['value']==a-b for row in calc.output_manifest.values())


@pytest.mark.parametrize('text,expected', [(CASES[1][0],25),(CASES[2][0],42),(CASES[3][0],32)])
def test_direct_operations_execute(tmp_path,text,expected):
    req=GoalResearchRequest(topic=text,goal=text,allow_python_execution=True,python_execution_approved=True)
    operations=parse_request_ir(req,[]).requested_operation_types
    facts=UserFactRegistry.from_topic(text).named_operands(text,operations)
    calc=asyncio.run(run_direct_arithmetic(Settings(data_dir=tmp_path),req,'dev-direct',facts,operations,'CALC1'))
    assert calc.validation_passed
    assert any(row['value']==expected for row in calc.output_manifest.values())
    if 'increase' in text:
        assert calc.output_manifest['OUT_percentage_increase']['value']==expected


@pytest.mark.parametrize('text,expected', [(CASES[4][0],.55),(CASES[5][0],147.2),(CASES[6][0],13.5)])
def test_user_formulas_execute_with_bound_provenance(tmp_path,text,expected):
    req=GoalResearchRequest(topic=text,goal=text,allow_python_execution=True,python_execution_approved=True)
    facts=UserFactRegistry.from_topic(text)
    calc=asyncio.run(run_user_formula_calculation(Settings(data_dir=tmp_path),req,'dev-formula',user_equation(text),facts,'CALC1','USERF99'))
    assert calc.validation_passed and calc.output['OUT_RESULT']==pytest.approx(expected)
    assert calc.formula_source_ids==['USERF99'] and calc.bound_variables and calc.execution_hash


def test_grounding_receives_late_support_and_required_goal():
    text='Background. '*200+'The seal prevents vertical leakage through connected pores.'
    class LocalJudge:
        async def chat_structured(self,messages,*args,**kwargs):
            payload=json.loads(messages[1]['content'])
            assert payload['sources'][0]['text']==text
            assert payload['required_goal']=='Explain the seal function.'
            return json.dumps({'claims':[{'index':0,'supported':True,'source_ids':['KB1']}]})
    req=GoalResearchRequest(topic='Explain the seal function.')
    answer,rejected=asyncio.run(ground_research_claims(LocalJudge(),req,'The seal prevents vertical leakage. [KB1]',[{'evidence_id':'KB1','source_type':'knowledge_base','text':text}]))
    assert '[KB1]' in answer and not rejected


def test_missing_calculation_names_requested_target():
    state=GoalExecutionState.from_criteria('dev','Determine fracture aperture.',[])
    answer=GoalExecutionAgent._safe_unavailable_answer('',state,'direct_calculation_blocked')
    assert 'fracture aperture' in answer and 'measured values' in answer
