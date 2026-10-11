"""Fresh synthetic development cases only; no benchmark artifacts or real KB writes."""
import asyncio
import itertools
import re
from dataclasses import replace

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import GoalResearchRequest, GoalCriterion
from app.services.calculation_request_ir import parse_request_ir
from app.services.calculation_requirements import rank_formula_candidates
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_clarification import calculation_readiness
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_execution_state import GoalExecutionState
from app.services.goal_intent import classify_goal_intent, user_equation
from app.services.goal_simulation import run_direct_arithmetic, run_user_formula_calculation, user_formula_bindings
from app.services.source_answerability import literal_answer
from app.services.user_fact_registry import UserFactRegistry, validate_original_operands


LISTS = [
    ('Readings: 2.7%, 5.1%, 2.7%, and 6.3%. Find median.', 'median', 3.9, 4),
    ('Rates were 114, 153, 128, 171, and 159 stb/d. Calculate mean.', 'mean', 145, 5),
    ('측정값은 13, 21, 13, 17 psi. 합계 계산해줘.', 'sum', 64, 4),
    ('Values: 12, 18, 24 psi; weights: 2, 3, 4. Find weighted mean.', 'weighted_average', 174/9, 6),
]
DIRECT = [
    ('oak=37 psi; elm=49 psi. Calculate mean.', 'mean', 43),
    ('north=71 stb/d; south=83 stb/d. 합계를 계산해줘.', 'sum', 154),
    ('Values: 9, 16, 9, 28 m. Find minimum.', 'minimum', 9),
    ('Observations: 52, 77, 61 kg. Find maximum.', 'maximum', 77),
]
FORMULAS = [
    ('cost=length*price; length=27 m; price=6 USD/m. Compute cost.', 162, 'USD'),
    ('a=0.4 dimensionless; b=0.2 dimensionless; result=a**2/b. 계산해줘.', .8, None),
    ('delivery=stream*duration; stream=19 stb/d; duration=4 d. Calculate delivery.', 76, 'stb'),
    ('gain=0.65; base=18; offset=7; score=base*gain+offset. Calculate score.', 18.7, None),
]
KB = [
    ('Use the textbook pore capacity equation to calculate capacity. area=13 m2; height=8 m; fraction=0.17.',
     'Pore capacity\ncapacity=area*height*fraction\nfraction is dimensionless.', 17.68),
    ('교재의 식으로 total_pressure를 계산해줘. load=270 psi; bias=45 psi.',
     'Total pressure\ntotal_pressure=load+bias', 315),
    ('Use the textbook travel equation to calculate travel. speed=7 m/s; time=11 s.',
     'Travel distance\ntravel=speed*time', 77),
]
QA = [
    ('Describe the function of the coalescer.', 'The coalescer separates entrained liquid droplets from the gas stream.'),
    ('여과기의 역할을 설명해줘.', '여과기는 유체에 포함된 고체 입자를 제거하는 역할을 합니다.'),
    ('Define wettability; describe the function of the desander.',
     'Wettability means the preference of a solid surface for contact with a fluid.\nThe desander removes entrained solids from produced fluids.'),
]
UNDERDETERMINED = [
    ('Determine the exact inhibitor dosage, but fluid composition and laboratory data are not provided.',
     'The exact inhibitor dosage is site-specific and requires fluid composition and laboratory compatibility tests.',
     ['fluid composition', 'laboratory']),
    ('정확한 최적 주입량을 구해줘, 유체 특성과 현장 시험 자료는 제공되지 않았어.',
     '최적 주입량은 유체 특성과 현장 시험 결과에 의존하며 이 자료가 필요합니다.',
     ['유체 특성', '현장 시험']),
]


def request(text):
    return GoalResearchRequest(topic=text, goal=text, allow_python_execution=True,
                               python_execution_approved=True, execution_mode='autonomous_goal_execution')


def evidence(text, sid='KB1'):
    return {'evidence_id': sid, 'source_type': 'knowledge_base', 'text': text,
            'document': 'Synthetic Development Notes', 'page': 1, 'locator': 'Synthetic Development Notes p.1'}


@pytest.mark.parametrize('text,operation,expected,count', LISTS)
def test_numeric_list(tmp_path, text, operation, expected, count):
    facts = UserFactRegistry.from_topic(text)
    assert len(facts.records) == count
    assert len({f.value_span for f in facts.records}) == count
    assert all(f.source_span and f.semantic_role for f in facts.records)
    calc = asyncio.run(run_direct_arithmetic(Settings(data_dir=tmp_path), request(text), 'list', facts, [operation], 'CALC1'))
    assert calc.validation_passed and calc.output['OUT_'+operation] == pytest.approx(expected)


@pytest.mark.parametrize('text,operation,expected', DIRECT)
def test_direct(tmp_path, text, operation, expected):
    facts = UserFactRegistry.from_topic(text)
    req = request(text)
    intent = classify_goal_intent(req, has_user_facts=True)
    state = GoalExecutionState.from_criteria('dev', text, [])
    action = GoalActionPlanner.select(req, state, intent=intent, user_fact_ids=[f.fact_id for f in facts.records],
                                      formula_ready=False, simulation_spec=None)
    assert action.action_type.value == 'calculate'
    calc = asyncio.run(run_direct_arithmetic(Settings(data_dir=tmp_path), req, 'direct', facts, [operation], 'CALC1'))
    assert calc.validation_passed and calc.output['OUT_'+operation] == pytest.approx(expected)


@pytest.mark.parametrize('text,expected,unit', FORMULAS)
def test_user_formula(tmp_path, text, expected, unit):
    req = request(text)
    facts = UserFactRegistry.from_topic(text)
    intent = classify_goal_intent(req, has_user_facts=True)
    assert intent.kind.value == 'user_formula_calc'
    assert not user_formula_bindings(intent.user_equation, facts)[1]
    calc = asyncio.run(run_user_formula_calculation(Settings(data_dir=tmp_path), req, 'formula', intent.user_equation, facts, 'CALC1', 'USERF99'))
    assert calc.validation_passed and calc.output['OUT_RESULT'] == pytest.approx(expected)
    assert calc.output_manifest['OUT_RESULT']['unit'] == unit


@pytest.mark.parametrize('text,source,expected', KB)
def test_found_kb_formula_transitions_and_executes(tmp_path, text, source, expected):
    req, facts, sources = request(text), UserFactRegistry.from_topic(text), [evidence(source), evidence(source, 'KB2')]
    formula, selection = rank_formula_candidates(sources, text, [f.name for f in facts.records])
    assert formula and formula.required_variables and formula.source_document and formula.source_page
    assert selection.candidates_found == 1
    missing = calculation_readiness(formula, sources, facts, [])
    assert missing == []
    action = GoalActionPlanner.select(req, GoalExecutionState.from_criteria('dev', text, []),
        intent=classify_goal_intent(req, has_user_facts=True), user_fact_ids=[f.fact_id for f in facts.records],
        formula_ready=True, formula_inputs_ready=not missing, simulation_spec=None)
    assert action.action_type.value == 'calculate'
    calc = asyncio.run(run_user_formula_calculation(Settings(data_dir=tmp_path), req, 'kb', formula.expression_candidate, facts, 'CALC1', formula.source_id))
    assert calc.validation_passed and calc.output['OUT_RESULT'] == pytest.approx(expected)


@pytest.mark.parametrize('text,source', QA)
def test_directly_supported_qa(text, source):
    answer = literal_answer(request(text), [evidence(source)])
    assert answer and '[KB1]' in answer
    assert all(quote in source for quote in re.findall(r'"([^"]+)"', answer))


@pytest.mark.parametrize('text,source,missing', UNDERDETERMINED)
def test_specific_underdetermined_answer(text, source, missing):
    req = request(text)
    assert classify_goal_intent(req, has_user_facts=False).kind.value == 'knowledge_qa'
    answer = literal_answer(req, [evidence(source)])
    assert answer and all(term in answer for term in missing)
    assert '[KB1]' in answer and not re.search(r'\d', re.sub(r'\[KB1\]', '', answer))


@pytest.mark.parametrize('numbers', list(itertools.permutations([3, 8, 3, 14]))[:12])
@pytest.mark.parametrize('language', ['en', 'ko'])
def test_list_permutation_language_distractor(tmp_path, numbers, language):
    prefix = 'Installed in 2037. Values: ' if language == 'en' else '2037년 설치. 측정값: '
    text = prefix + ', '.join(map(str, numbers)) + ' psi. ' + ('Find median.' if language == 'en' else '중앙값 계산해줘.')
    facts = UserFactRegistry.from_topic(text).named_operands(text, ['median'])
    calc = asyncio.run(run_direct_arithmetic(Settings(data_dir=tmp_path), request(text), 'metamorphic', facts, ['median'], 'CALC1'))
    assert calc.output['OUT_median'] == 5.5


@pytest.mark.parametrize('assignments', itertools.permutations(['u=9', 'v=4', 'scale=0.3']))
def test_formula_variable_order(tmp_path, assignments):
    text = 'Built in 2039. ' + '; '.join(assignments) + '; metric=(u+v)*scale. Calculate metric.'
    calc = asyncio.run(run_user_formula_calculation(Settings(data_dir=tmp_path), request(text), 'order', user_equation(text), UserFactRegistry.from_topic(text), 'CALC1', 'USERF99'))
    assert calc.output['OUT_RESULT'] == pytest.approx(3.9)


@pytest.mark.parametrize('damage', ['drop', 'duplicate', 'value', 'unit', 'swap'])
def test_independent_validator_rejects_tampered_list_before_python(tmp_path, damage):
    text = LISTS[0][0]
    facts = UserFactRegistry.from_topic(text)
    if damage == 'drop': facts.records.pop()
    elif damage == 'duplicate': facts.records[-1] = facts.records[0].model_copy()
    elif damage == 'value': facts.records[0].value = 100
    elif damage == 'swap': facts.records[0].value, facts.records[1].value = facts.records[1].value, facts.records[0].value
    else: facts.records[0].unit = 'psi'
    with pytest.raises(ValueError, match='operand_extraction_error'):
        asyncio.run(run_direct_arithmetic(Settings(data_dir=tmp_path), request(text), 'tamper', facts, ['median'], 'CALC1'))
    assert not list(tmp_path.rglob('calculation.json'))


def test_explicit_assignment_tampering_and_alias_precedence():
    text = 'q=81 stb/d; rate=19 stb/d; duration=3 d; total=q*duration. Calculate total.'
    facts = UserFactRegistry.from_topic(text)
    bound, missing = user_formula_bindings(user_equation(text), facts)
    assert not missing and bound['q'].value == 81
    bound['q'].value = 19
    with pytest.raises(ValueError, match='operand_source_mismatch'):
        validate_original_operands(text, UserFactRegistry(records=list(bound.values())))


@pytest.mark.parametrize('unit', ['USD/m', 'stb/d', 'psi/ft', 'kg/m3', 'MMscf/d'])
def test_compound_unit_preserved(unit):
    facts = UserFactRegistry.from_topic(f'quantity=23 {unit}; factor=0.6')
    assert [(f.name, f.value, f.unit) for f in facts.records] == [('quantity', 23, unit), ('factor', .6, '')]


def test_incompatible_units_do_not_execute(tmp_path):
    text = 'r=6 m; s=8 kg; out=r+s. Calculate out.'
    with pytest.raises(ValueError, match='incompatible'):
        asyncio.run(run_user_formula_calculation(Settings(data_dir=tmp_path), request(text), 'unit', user_equation(text), UserFactRegistry.from_topic(text), 'CALC1', 'USERF99'))


def test_partial_qa_not_achieved_by_quote():
    req = request(QA[2][0])
    assert literal_answer(req, [evidence(QA[2][1].split('\n')[0])]) is None
    assert literal_answer(request(QA[0][0]), [evidence('The coalescer is mentioned in the equipment catalogue.')]) is None


def test_distinct_formulas_remain_ambiguous():
    text, source, _ = KB[1]
    formula, _ = rank_formula_candidates([evidence(source), evidence(source.replace('load+bias', 'load-bias'), 'KB2')], text, ['load', 'bias'])
    assert formula is None


@pytest.mark.parametrize('text,source', [(r[0], None) for r in LISTS + DIRECT + FORMULAS] + [(r[0], r[1]) for r in KB])
def test_full_agent_numeric_development(tmp_path, monkeypatch, text, source):
    from test_goal_execution_v8 import NoResearch, StaticResearch, PassingEvaluator
    monkeypatch.setattr('app.services.goal_execution_agent.get_settings', lambda: Settings(data_dir=tmp_path))
    req = request(text).model_copy(update={'max_iterations': 6, 'success_criteria': [
        GoalCriterion(criterion_id='C1', description='Calculate the requested result with validated units and provenance')]})
    agent = GoalExecutionAgent(StaticResearch(source) if source else NoResearch(), object(), evaluator=PassingEvaluator())
    result = asyncio.run(agent.run('fresh-v15-numeric', req))
    assert result.status.value == 'achieved', (result.final_answer, result.action_history)
    actions = [a['action_type'] for a in result.action_history]
    assert actions[0] == ('retrieve' if source else 'calculate')
    assert result.python_calls_total == 1 and all(c.validation_passed for c in result.computations)
    assert actions.count('calculate') == 1 and 'verify' in actions


@pytest.mark.parametrize('text,source', QA + [(r[0], r[1]) for r in UNDERDETERMINED])
def test_full_agent_extractive_fallback(tmp_path, monkeypatch, text, source):
    from test_goal_execution_v8 import StaticResearch, PassingEvaluator
    from app.models.goal_research_schemas import CriterionStatus
    class RefusingEvaluator(PassingEvaluator):
        async def evaluate(self, *args, **kwargs):
            value = await super().evaluate(*args, **kwargs)
            return replace(value, achieved=False, coverage=0, gaps=['unanswered'], criteria=[
                c.model_copy(update={'status': CriterionStatus.UNMET}) for c in value.criteria])
    async def no_generated_answer(*args, **kwargs):
        return ''
    monkeypatch.setattr('app.services.goal_execution_agent.get_settings', lambda: Settings(data_dir=tmp_path))
    req = request(text).model_copy(update={'max_iterations': 6, 'success_criteria': [
        GoalCriterion(criterion_id='C1', description=text)]})
    agent = GoalExecutionAgent(StaticResearch(source), object(), evaluator=RefusingEvaluator(), synthesizer=no_generated_answer)
    result = asyncio.run(agent.run('fresh-v15-qa', req))
    assert result.status.value == 'achieved', (result.final_answer, result.action_history)
    assert result.python_calls_total == 0 and '[KB1]' in result.final_answer


def test_missing_final_result_cannot_inherit_achieved(tmp_path):
    from test_goal_execution_v8 import PassingEvaluator
    req = request(DIRECT[0][0])
    facts = UserFactRegistry.from_topic(req.topic)
    calc = asyncio.run(run_direct_arithmetic(Settings(data_dir=tmp_path), req, 'final-guard', facts, ['mean'], 'CALC1'))
    criteria = [GoalCriterion(criterion_id='C1', description='Calculate mean')]
    evaluation = asyncio.run(PassingEvaluator().evaluate(req, criteria, '', facts.evidence(), {}))
    from app.services.goal_intent import SourceRequirement
    result = GoalExecutionAgent._deterministic_calculation_criteria(evaluation, criteria, 'Done. [CALC1]', [calc], facts.evidence(), SourceRequirement.NONE)
    assert not result.achieved


@pytest.mark.parametrize('text,count', [('Values:1,200, 1,500, 1,800 psi. Find mean.', 3),
                                       ('Values: 0.5, 0.5, 0.5. Find sum.', 3)])
def test_list_literal_boundaries(text, count):
    facts = UserFactRegistry.from_topic(text)
    assert len(facts.records) == count
    validate_original_operands(text, facts, list_operation=True)


def test_actual_accumulator_preserves_formula_document_page():
    from test_goal_execution_v8 import StaticResearch
    from app.models.research_schemas import ResearchRequest
    from app.services.goal_research_agent import EvidenceAccumulator
    from app.services.formula_source_registry import FormulaSourceRegistry
    accumulator = EvidenceAccumulator()
    accumulator.add(asyncio.run(StaticResearch(KB[0][1]).research(ResearchRequest(query='synthetic'))))
    record = FormulaSourceRegistry.from_evidence(accumulator.records()).records[0]
    assert record.source_document == 'source.pdf' and record.source_page == 1


def test_partial_literal_cannot_inherit_passing_evaluator(tmp_path, monkeypatch):
    from test_goal_execution_v8 import StaticResearch, PassingEvaluator
    async def empty_answer(*args, **kwargs): return ''
    monkeypatch.setattr('app.services.goal_execution_agent.get_settings', lambda: Settings(data_dir=tmp_path))
    req = request('Explain relative permeability and water saturation.').model_copy(update={
        'success_criteria': [GoalCriterion(criterion_id='C1', description='Explain relative permeability and water saturation.')]})
    agent = GoalExecutionAgent(StaticResearch('Relative permeability is a function of saturation.'), object(),
        evaluator=PassingEvaluator(), synthesizer=empty_answer)
    result = asyncio.run(agent.run('fresh-v15-partial', req))
    assert result.status.value != 'achieved'


def test_mixed_shared_units_do_not_guess():
    text = 'Values: 4 psi, 7, 8 kg. Find mean.'
    with pytest.raises(ValueError, match='ambiguous shared unit'):
        validate_original_operands(text, UserFactRegistry.from_topic(text), list_operation=True)


def test_nonfinite_list_fails_at_gate_not_extractor():
    text = 'Readings: 1e999, 6, 8 psi. Find mean.'
    facts = UserFactRegistry.from_topic(text)
    with pytest.raises(ValueError, match='operand_extraction_error'):
        validate_original_operands(text, facts, list_operation=True)


def test_compound_unit_digits_do_not_trigger_llm_extraction(tmp_path, monkeypatch):
    from test_goal_execution_v8 import NoResearch, PassingEvaluator
    class NoFactExtraction:
        async def chat_structured(self, messages, *args, **kwargs):
            assert 'Extract only literal numeric facts' not in messages[0]['content']
            return '{"claims": []}'
    text = 'Samples: 9 kg/m3, 15 kg/m3, 12 kg/m3. Find mean.'
    req = request(text).model_copy(update={'max_iterations': 6, 'success_criteria': [
        GoalCriterion(criterion_id='C1', description='Calculate mean')]})
    monkeypatch.setattr('app.services.goal_execution_agent.get_settings', lambda: Settings(data_dir=tmp_path))
    result = asyncio.run(GoalExecutionAgent(NoResearch(), NoFactExtraction(), evaluator=PassingEvaluator()).run('unit-digits', req))
    assert result.python_calls_total == 1
    assert result.computations[0].output['OUT_mean'] == 12


def test_unit_expansion_stays_bounded(tmp_path):
    text = 'length=1 m; result=((length**8)**8)**8. Calculate result.'
    with pytest.raises(ValueError, match='safe bounds'):
        asyncio.run(run_user_formula_calculation(Settings(data_dir=tmp_path), request(text), 'unit-bound', user_equation(text), UserFactRegistry.from_topic(text), 'CALC1', 'USERF99'))


def test_missing_data_answer_does_not_invert_negative_dependency():
    req = request(UNDERDETERMINED[0][0])
    assert literal_answer(req, [evidence('The exact inhibitor dosage does not require fluid composition or laboratory tests.')]) is None


@pytest.mark.parametrize('text', ['Values: 7, 11, 16 psi; weights: 2, 5. Find weighted mean.',
                                'Values: 7 psi, 11 kg; weights: 2, 5. Find weighted mean.'])
def test_weighted_mean_requires_every_pair_and_compatible_units(tmp_path, text):
    with pytest.raises(ValueError, match='weighted average'):
        asyncio.run(run_direct_arithmetic(Settings(data_dir=tmp_path), request(text), 'weights', UserFactRegistry.from_topic(text), ['weighted_average'], 'CALC1'))


def test_weighted_pair_binding_is_independently_checked():
    text = LISTS[3][0]
    facts = UserFactRegistry.from_topic(text)
    facts.records[-1].name, facts.records[-2].name = facts.records[-2].name, facts.records[-1].name
    with pytest.raises(ValueError, match='operand_extraction_error'):
        validate_original_operands(text, facts, list_operation=True)
