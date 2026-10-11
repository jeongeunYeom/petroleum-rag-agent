"""Synthetic development checks for source-grounded premises and domain retrieval."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.models.goal_research_schemas import GoalResearchRequest
from app.models.research_schemas import InternalEvidence
from app.services.goal_intent import GoalIntentKind, classify_goal_intent
from app.services.goal_knowledge_retrieval import domain_hint, plan_query, rerank_sources
from app.services.premise_grounding import (assess_premise, derive_safe_relation_from_equation,
                                            expand_premise_context)


PREMISES = [
    ("reservoir_engineering", "An aquifer has no effect on reservoir pressure",
     "Water influx from an active aquifer supports reservoir pressure."),
    ("reservoir_engineering", "Material balance cannot include cumulative production",
     "The reservoir material balance includes cumulative fluid production."),
    ("reservoir_simulation", "Numerical grid spacing never affects discretization error",
     "Numerical grid spacing affects discretization error in reservoir simulation."),
    ("reservoir_simulation", "Transmissibility is independent of cell permeability",
     "Transmissibility between grid cells depends on permeability."),
    ("well_testing", "A pressure buildup test has no shut-in period",
     "A pressure buildup test measures pressure after a well is shut in."),
    ("well_testing", "Early wellbore storage has no effect on measured pressure",
     "Wellbore storage affects early-time pressure measurements."),
    ("petrophysics", "Water saturation cannot influence electrical resistivity",
     "Electrical resistivity depends on water saturation in a porous rock."),
    ("petrophysics", "Porosity and permeability are identical rock properties",
     "Porosity describes pore volume while permeability describes fluid-flow capacity."),
    ("drilling", "Mud density has no effect on hydrostatic pressure",
     "Mud-column hydrostatic pressure depends on mud density."),
    ("drilling", "Lost circulation cannot reduce fluid returns",
     "Lost circulation reduces drilling-fluid returns to the surface."),
    ("production", "Separator pressure has no effect on gas liberation",
     "Gas liberation in a production separator depends on separator pressure."),
    ("production", "Pump intake pressure cannot affect cavitation risk",
     "Low pump-intake pressure increases the risk of cavitation in production equipment."),
]


class GroundedModel:
    def __init__(self, quote: str, *, fabricated: bool = False):
        self.quote = quote
        self.fabricated = fabricated

    async def chat_structured(self, _messages, _schema, **_kwargs):
        quote = "An invented statement not present in the source." if self.fabricated else self.quote
        return json.dumps({"verdict": "contradicts", "evidence": [
            {"source_id": "KB1", "quote": quote, "role": "relation"}],
            "corrected_relation": self.quote})


@pytest.mark.parametrize("family,claim,quote", PREMISES)
def test_premise_semantic_case_three_paraphrases(family, claim, quote):
    for suffix in ("right?", "correct?", "always, right?"):
        question = f"{claim}, {suffix}"
        request = GoalResearchRequest(topic=question, goal=question)
        intent = classify_goal_intent(request, has_user_facts=False)
        assert intent.kind == GoalIntentKind.PREMISE_CHECK
        plan = plan_query(question, premise=True)
        assert plan.domain == family
        evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text": quote}]
        assessment = asyncio.run(assess_premise(GroundedModel(quote), request, evidence))
        assert assessment.verdict == "contradicts", (question, assessment)
        assert assessment.supporting_source_ids == ("KB1",)
        assert assessment.supporting_spans == (quote,)
        assert assessment.correction == quote
        assert "[KB1]" in assessment.answer and quote in assessment.answer
        assert "incorrect" in assessment.answer or "contradicted" in assessment.answer


def test_multi_span_definition_plus_equation_must_be_literal():
    source = ("Seal capacity controls the maximum held fluid column.\n"
              "The entry-pressure variable is pc.\n"
              "h = pc / dRho.\n"
              "Here h is the held column height and dRho is the density difference.")
    request = GoalResearchRequest(topic="Seal capacity is unrelated to entry pressure, right?")

    class MultiSpan:
        async def chat_structured(self, *_args, **_kwargs):
            return json.dumps({"verdict": "contradicts", "evidence": [
                {"source_id": "KB1", "quote": "The entry-pressure variable is pc.", "role": "definition"},
                {"source_id": "KB1", "quote": "h = pc / dRho.", "role": "equation"},
                {"source_id": "KB1", "quote": "Here h is the held column height and dRho is the density difference.",
                 "role": "context"}], "corrected_relation": "h depends on pc in the cited relation"})

    assessment = asyncio.run(assess_premise(MultiSpan(), request, [{
        "evidence_id": "KB1", "source_type": "knowledge_base", "text": source}]))
    assert assessment.verdict == "contradicts"
    assert assessment.relation_type == "multi_span" and len(assessment.supporting_spans) == 3
    assert all(span in source for span in assessment.supporting_spans)
    bad = asyncio.run(assess_premise(GroundedModel("Invented source sentence.", fabricated=True), request, [{
        "evidence_id": "KB1", "source_type": "knowledge_base", "text": source}]))
    assert bad.verdict == "insufficient"


def test_indexed_span_selection_uses_exact_source_and_rejects_mismatched_id():
    source = "The active aquifer supplies pressure support as oil production lowers reservoir pressure."
    request = GoalResearchRequest(topic="The aquifer has no effect on reservoir pressure, right?")

    class IndexedModel:
        def __init__(self, span_id="S1", source_id="KB1"):
            self.span_id, self.source_id = span_id, source_id

        async def chat_structured(self, messages, _schema, **_kwargs):
            supplied = json.loads(messages[1]["content"])["source_spans"]
            assert supplied[0]["text"] in source
            return json.dumps({"verdict": "contradicts", "evidence": [{
                "source_id": self.source_id, "span_id": self.span_id, "role": "relation"}],
                "corrected_relation": source})

    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text": source}]
    valid = asyncio.run(assess_premise(IndexedModel(), request, evidence))
    assert valid.verdict == "contradicts" and valid.supporting_spans == (source,)
    invalid = asyncio.run(assess_premise(IndexedModel(span_id="S99"), request, evidence))
    assert invalid.verdict == "insufficient" and invalid.failure_reason == "unknown_or_mismatched_span_id"
    mismatched = asyncio.run(assess_premise(IndexedModel(source_id="KB2"), request, evidence))
    assert mismatched.verdict == "insufficient"


def test_pdf_wrapped_literal_span_is_rendered_as_one_claim_line():
    source = ("An active aquifer provides pressure\n"
              "support when reservoir pressure declines during production.")
    request = GoalResearchRequest(topic="Aquifer support is unrelated to reservoir pressure, right?")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text": source}]
    assessment = asyncio.run(assess_premise(GroundedModel(source), request, evidence))
    assert assessment.verdict == "contradicts"
    assert assessment.supporting_spans == (source,)
    assert "\n" not in assessment.answer
    assert '"An active aquifer provides pressure support' in assessment.answer


def test_korean_negative_premise_cue_routes_to_check():
    for question in ("대수층 물 유입은 저류층 압력과 무관하지?", "이수 밀도가 정수압에 영향을 주지 않지?"):
        request = GoalResearchRequest(topic=question, goal=question)
        assert classify_goal_intent(request, has_user_facts=False).kind == GoalIntentKind.PREMISE_CHECK


def test_simple_equation_inference_requires_literal_sign_and_named_variables():
    question = "y is unrelated to x, right?"
    positive = "The relationship is y = a * x, with a > 0 for these variables."
    result = derive_safe_relation_from_equation(question, {"KB1": positive}, False)
    assert result.verdict == "contradicts" and result.method == "equation_rule"
    assert all(span in positive for span in result.supporting_spans)
    assert derive_safe_relation_from_equation(question, {"KB1": "y = a * x"}, False).verdict == "insufficient"
    assert derive_safe_relation_from_equation("z is unrelated to x, right?", {"KB1": positive}, False).verdict == "insufficient"


def test_context_expansion_is_read_only_adjacent_and_budgeted():
    class Collection:
        def __init__(self):
            self.calls = []

        def get(self, *, ids, include):
            self.calls.append((ids, include))
            existing = [value for value in ids if value.endswith((":c0", ":c2"))]
            return {"ids": existing, "documents": ["Neighbor context for the same page."] * len(existing),
                    "metadatas": [{"document": "engineering.pdf", "page": 7}] * len(existing)}

    class Store:
        collection = Collection()

    source = InternalEvidence(evidence_id="KB1", document="engineering.pdf", page=7,
                              chunk_id="doc:p7:c1", score=1, excerpt="Selected relation.")
    added, events = expand_premise_context(Store(), [source], budget=2)
    assert [item.chunk_id for item in added] == ["doc:p7:c0", "doc:p7:c2"]
    assert events[0]["adjacent_chunks_added"] == 2
    assert all(item.document == source.document for item in added)


KNOWLEDGE = [
    ("reservoir_engineering", "material balance pressure depletion", "material balance links production to pressure depletion"),
    ("reservoir_engineering", "aquifer water influx support", "aquifer water influx supports reservoir pressure"),
    ("reservoir_engineering", "reservoir pore volume compressibility", "reservoir pore volume changes with compressibility"),
    ("reservoir_simulation", "numerical grid discretization", "numerical grid discretization defines simulation cells"),
    ("reservoir_simulation", "finite difference time step", "finite difference time steps control numerical approximation"),
    ("reservoir_simulation", "cell transmissibility permeability", "cell transmissibility depends on permeability"),
    ("well_testing", "pressure drawdown transient", "pressure drawdown records a transient well response"),
    ("well_testing", "pressure buildup shut-in", "pressure buildup follows well shut-in"),
    ("well_testing", "wellbore storage early time", "wellbore storage affects early-time test response"),
    ("petrophysics", "porosity pore volume", "porosity compares pore volume with bulk volume"),
    ("petrophysics", "well log resistivity saturation", "well log resistivity informs saturation estimation"),
    ("petrophysics", "permeability fluid flow", "permeability measures rock fluid-flow capacity"),
    ("drilling", "mud weight hydrostatic pressure", "mud weight sets hydrostatic pressure"),
    ("drilling", "casing cement annulus", "casing cement occupies the annulus"),
    ("drilling", "lost circulation return flow", "lost circulation reduces return flow"),
    ("production", "separator gas liberation", "separator conditions influence gas liberation"),
    ("production", "gravel pack sand control", "gravel pack provides sand control"),
    ("production", "pump intake pressure cavitation", "pump intake pressure affects cavitation risk"),
]
TITLES = {"reservoir_engineering": "Reservoir_Engineering.pdf",
          "reservoir_simulation": "Reservoir_Simulation.pdf", "well_testing": "Well_Test_Analysis.pdf",
          "petrophysics": "Formation_Evaluation.pdf", "drilling": "Drilling_Engineering.pdf",
          "production": "Production_Technology_I.pdf"}


@pytest.mark.parametrize("family,question,excerpt", KNOWLEDGE)
def test_knowledge_query_paraphrases_choose_relevant_family(family, question, excerpt):
    for variant in (f"Explain {question}.", f"What is the role of {question}?",
                    f"Find internal material on {question}."):
        plan = plan_query(variant)
        assert plan.domain == family, (variant, plan.domain)
        relevant = InternalEvidence(evidence_id="KB2", document=TITLES[family], page=4,
                                    chunk_id="relevant", score=.2, excerpt=excerpt)
        distractor = InternalEvidence(evidence_id="KB1", document="Well_Test_Analysis.pdf"
                                      if family != "well_testing" else "Drilling_Engineering.pdf",
                                      page=7, chunk_id="distractor", score=1,
                                      excerpt="General petroleum pressure and operations background.")
        selected, telemetry = rerank_sources([distractor, relevant], plan, limit=2)
        assert selected and selected[0].chunk_id == "relevant", (variant, telemetry)
        assert telemetry["confidence"] in {"MEDIUM", "HIGH"}
        assert telemetry["domain_hint"] == family


def test_soft_domain_prior_allows_stronger_cross_domain_source():
    plan = plan_query("Explain reservoir simulation grid transmissibility and permeability")
    weak = InternalEvidence(evidence_id="KB1", document="Reservoir_Simulation.pdf", page=1,
                            chunk_id="weak", score=1, excerpt="Simulation grid chapter overview.")
    strong = InternalEvidence(evidence_id="KB2", document="Reservoir_Engineering.pdf", page=5,
                              chunk_id="strong", score=.4,
                              excerpt="Reservoir simulation grid transmissibility depends on cell permeability.")
    selected, _ = rerank_sources([weak, strong], plan, limit=2)
    assert any(item.chunk_id == "strong" for item in selected)


def test_query_plan_omits_criteria_noise_and_bounds_variants():
    question = "Explain numerical grid discretization in reservoir simulation."
    plan = plan_query(question)
    assert len(plan.queries) <= 3 and all("Missing:" not in item for item in plan.queries)
    assert domain_hint(question) == "reservoir_simulation"
    assert "grid" in plan.search_text


def test_low_confidence_evidence_requires_refined_query_or_safe_stop():
    question = "Explain grid transmissibility in reservoir simulation"
    plan = plan_query(question)
    unrelated = InternalEvidence(evidence_id="KB1", document="General_Petroleum.pdf", page=2,
                                 chunk_id="generic", score=1, excerpt="General petroleum operations overview.")
    selected, telemetry = rerank_sources([unrelated], plan)
    assert selected == [] and telemetry["confidence"] == "LOW"
    refined = plan_query(question, refined=True)
    assert refined.search_text != plan.search_text and len(refined.queries) <= 3
