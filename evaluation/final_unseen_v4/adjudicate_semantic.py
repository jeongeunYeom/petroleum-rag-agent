"""Record the one-shot, task-level V4 semantic adjudication.

These rows are reviewer decisions against the sealed catalog and rubric, not a
training signal or an automatic model judge. The compact flags make the full
60-pair audit inspectable alongside the raw answers and review packet.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# flags: covered, goal_success, task_completion, hallucination_free,
# numeric_accuracy (x means not applicable), cited_claims, supported_cited_claims.
# Qwen does not have citations, so its final two slots are always zero.
# All comments refer to the visible answer; calculation provenance is checked
# separately where the rubric requires it for Agent Goal Success.
DECISIONS = """
001|0,0,0,1,x,0,0|unnecessary_refusal|Agent stopped although the reservoir-fluid source explicitly says above-bubble oil is undersaturated and gas stays dissolved.|2,1,1,0,x,0,0|Qwen states both bubble-point relations, but adds a false temperature trend and describes exsolution as whole-liquid vaporization.
002|1,0,1,1,x,2,2|incomplete_answer|The cited production text supports reduced hydrostatic head from lift gas; the answer never says lift is considered when reservoir pressure is insufficient.|2,1,1,1,x,0,0|Qwen gives insufficient natural pressure and reduced tubing density/head without a material contradiction.
003|0,0,0,1,x,0,0|unnecessary_refusal|The answer stops instead of using the catalogued simulation source about cheaper option comparison and forecast uncertainty.|2,1,1,1,x,0,0|Qwen explains cheaper modeled options and uncertainty from sparse inputs and model assumptions.
004|2,1,1,1,x,2,2||The drilling excerpts directly identify steel drillstring magnetic distortion and the nonmagnetic collar protection.|2,1,1,1,x,0,0|Qwen attributes compass distortion to magnetized steel and explains Monel's nonmagnetic role.
005|2,1,1,1,x,2,2||The well-test excerpt explicitly names indefinite pressure-only matching and addition of the derivative curve.|2,1,1,1,x,0,0|Qwen explains pressure-only ambiguity and derivative regime discrimination.
006|0,0,0,1,x,0,0|unnecessary_refusal|The Agent gives no Sw pore-volume definition or hydrocarbon remainder despite an answerable source.|1,0,1,0,x,0,0|Qwen defines Sw as water-filled pore fraction but wrongly says the remainder is generally gas rather than hydrocarbons.
007|1,0,1,1,x,2,2|incomplete_answer|KB5 supports post-breakthrough rising water cut; quoted fractional-flow definition does not state the curve's later-oil-production implication.|2,1,1,1,x,0,0|Qwen gives rising water cut and reduced subsequent oil fraction after breakthrough.
008|1,0,1,1,x,2,2|incomplete_answer|Cited compaction-drive span supports pressure-loss compaction; the visible answer does not connect initial porosity to initial oil in place.|2,1,1,1,x,0,0|Qwen links falling pore pressure to effective-stress compaction and initial porosity to in-place volume.
009|0,0,0,1,x,1,0|retrieval_or_synthesis_failure|Cited chart headings do not provide either requested carbonate or Humble equation; Agent stops.|0,0,1,0,x,0,0|Qwen supplies 1/phi and 1/phi^1.3, both inconsistent with the frozen carbonate and Humble source spans.
010|1,0,1,1,x,2,2|incomplete_answer|The cited open-hole pressure-depth/RFT text is relevant, but probe penetration of mud cake is not answered.|1,0,1,0,x,0,0|Qwen identifies a pressure-depth survey but invents a need to remove mud cake rather than describing probe penetration.
011|0,0,0,1,x,0,0|unnecessary_refusal|Agent stops without distinguishing tubing deposits from near-wellbore formation damage.|0,0,0,0,x,0,0|Qwen degenerates into repeated nonsensical tubing-cleaning text and never completes the comparison.
012|1,0,1,1,x,2,2|incomplete_answer|The appraisal source supports large investment decisions amid uncertainty; the answer does not explain limited data/production history.|2,1,1,1,x,0,0|Qwen explicitly relates sparse appraisal data and limited production history to large facilities decisions.
013|0,0,1,0,0,0,0|arithmetic_error|Validated CALC is reported as 146 stb/d, not 136+211+73=420 stb/d; a validated flag cannot repair wrong binding.|1,1,1,1,1,0,0|Qwen sums the three rates to 420 stb/d with the requested unit.
014|0,0,0,1,0,0,0|unnecessary_retrieval|Agent stops rather than subtracting the two explicit gauge pressures.|1,1,1,1,1,0,0|Qwen correctly computes 2780-2550=230 psi.
015|1,1,1,1,1,0,0||Validated mean is 240 stb/d for the three given well rates.|1,1,1,1,1,0,0|Qwen computes the same 240 stb/d mean.
016|0,0,0,1,0,0,0|unnecessary_clarification|Agent asks despite both old and new rates being present; no 15% answer is delivered.|1,1,1,1,1,0,0|Qwen computes (780-663)/780=15%.
017|0,0,0,1,0,0,0|input_binding_failure|Agent asks for a generic validated item rather than using 3780 scf and 135 stb.|0,0,1,1,0,0,0|Qwen obtains 28 but presents it as a bare dimensionless number, omitting the required scf/stb unit.
018|2,1,1,1,1,0,0||Validated maximum is explicitly tied to well B at 208 stb/d.|2,1,1,1,1,0,0|Qwen identifies B and 208 stb/d correctly.
019|0,0,0,1,0,0,0|unnecessary_clarification|Agent requests input instead of calculating the 160 psi rise relative to 1600 psi.|1,1,1,1,1,0,0|Qwen reports the requested 10% increase.
020|0,0,0,1,0,0,0|input_binding_failure|Agent asks for a generic validated item even though both pressure readings are supplied.|1,1,1,1,1,0,0|Qwen computes the absolute difference of 165 psi.
021|1,1,1,1,1,0,0||User equation and both pressure facts lead to a validated P_net=1275 psi.|1,1,1,1,1,0,0|Qwen evaluates the user-specified subtraction as 1275 psi.
022|1,1,1,1,1,0,0||Validated user-defined Z=x*y+4 gives 70 with dimensionless inputs.|1,1,1,1,1,0,0|Qwen evaluates 6*11+4=70.
023|1,1,1,1,1,0,0||Validated score=12+35*0.24 is 20.4, a dimensionless user formula.|1,1,1,1,1,0,0|Qwen computes 20.4 from the supplied definition.
024|0,0,0,1,0,0,0|input_binding_failure|Agent remains in clarification instead of binding 145 stb/d and 6 days to V=q*t.|1,1,1,1,1,0,0|Qwen multiplies the rate and duration to 870 stb.
025|1,1,1,1,1,0,0||Validated average of 33 and 51 psi is 42 psi.|1,1,1,1,1,0,0|Qwen computes R=42 psi.
026|0,0,1,0,0,0,0|wrong_unit|Agent computes scalar 20 but labels the requested percentage as dimensionless, not 20%.|1,1,1,1,1,0,0|Qwen calculates 20% with the required percent sign.
027|0,0,0,1,0,0,0|unnecessary_clarification|Agent waits despite the user-supplied m=7 and F=3*m+2 being complete.|1,1,1,1,1,0,0|Qwen evaluates the given dimensionless expression to 23.
028|1,1,1,1,1,0,0||Validated E=(32+48)/5 is 16 with dimensionless inputs.|1,1,1,1,1,0,0|Qwen computes E=16.
029|2,1,1,1,1,2,2||Reservoir Engineering p90 contains the literal SG-to-API equation; validated CALC gives 28.75 °API and cites KB1.|2,1,1,1,1,0,0|Qwen states the correct conversion and about 28.75 °API without access to the internal citation.
030|0,0,1,1,0,1,1|formula_and_unit_omission|CALC1 uses the correct p90 source, but final text gives bare 16.51255 with no °API and does not state the equation.|1,0,1,0,0,0,0|Qwen states the correct equation but never finishes the requested number and invents specific textbook/standard attributions.
031|0,0,0,1,0,0,0|unnecessary_refusal|Agent does not produce the carbonate F=1/phi² relation or 34.60 result.|0,0,1,0,0,0,0|Qwen uses a wrong carbonate exponent 1.3 and reports about 11.63.
032|0,0,0,1,0,0,0|unnecessary_refusal|Agent stops before the sourced carbonate relation and 12.76 result.|0,0,1,0,0,0,0|Qwen uses F=1/phi rather than carbonate 1/phi² and obtains 3.57.
033|0,0,1,0,0,1,0|wrong_formula_selection|Agent selects the simpler sand 0.81/phi² source in place of the explicitly requested Humble 0.62/phi^2.15, yielding 15.31 instead of 14.61.|0,0,1,0,0,0,0|Qwen substitutes an unrelated 1/phi^1.3 relation and wrong value.
034|1,0,1,1,1,1,1|formula_not_shown|CALC1 correctly uses literal KB20 0.81/phi² and gives 11.11, but the user-facing answer does not display the requested textbook equation/span.|2,1,1,0,1,0,0|Qwen computes the prompt-provided 0.81/phi² relation, but misdefines equation span and invents a 1-to-20 range.
035|1,0,1,1,1,1,1|formula_not_shown|KB4 raw F=a/fm is safely normalized in CALC1 and 21.2046 is correct; final answer omits the requested sourced relation itself.|0,0,1,0,0,0,0|Qwen invents (1-a*phi^m)/phi and computes a wrong result.
036|1,0,1,1,1,1,1|formula_not_shown|CALC1 uses the exact Rt=Ro/Sw² source and yields 17.78 ohm-m; final text provides only the result, not the requested relation.|2,1,1,0,1,0,0|Qwen eventually gives the right Archie relation and value, but begins with an invented nonlinear equation.
037|0,0,0,1,0,0,0|unnecessary_clarification|Agent requests an unspecified additional input although Pf=2100 and Pc=125 are supplied.|2,1,1,1,1,0,0|Qwen states Po=Pf+Pc and obtains 2225 psi.
038|0,0,0,1,0,0,0|unnecessary_clarification|Agent leaves a blank final answer in waiting state instead of rearranging Po=Pf+Pc.|2,1,1,1,1,0,0|Qwen rearranges the pressure balance and computes Pc=250 psi.
039|1,0,1,1,1,1,1|formula_not_shown|CALC1 cites the literal separator GOR relation and gets 30 scf/stb, but the equation the user asked to find is absent from the final text.|2,1,1,1,1,0,0|Qwen states the two-stage separator equation and computes 30 scf/stb.
040|0,0,0,1,0,0,0|unnecessary_clarification|Agent remains waiting with no Bo relation or 1.2 rb/stb answer despite Vres and L2 being present.|2,1,1,1,1,0,0|Qwen gives Bo=Vres/L2 and 1.2 rb/stb.
041|0,0,0,1,0,0,0|unnecessary_retrieval|Agent stops without summing user-only rates or identifying B as largest.|3,1,1,1,1,0,0|Qwen gives total 131 stb/d and B=55 stb/d.
042|0,0,0,1,0,0,0|unnecessary_clarification|Agent waits although all three rates suffice for mean and ranking.|2,1,1,1,1,0,0|Qwen reports mean 110 stb/d and complete B>C>A order.
043|0,0,0,1,0,0,0|unnecessary_clarification|Agent waits instead of reporting both decline measures from 640 and 496 stb/d.|2,1,1,1,1,0,0|Qwen computes 144 stb/d and 22.5%.
044|3,1,1,1,1,0,0||Agent validated calculation gives max B=2510, min A=2430 and mean 2470 psi.|3,1,1,1,1,0,0|Qwen gives the same three pressure statistics with psi unit.
045|0,0,0,1,0,0,0|unnecessary_clarification|Agent waits rather than evaluating the supplied score formula for all three wells.|4,1,1,1,1,0,0|Qwen reports A=45, B=57, C=39 and B as highest.
046|6,1,1,1,1,0,0||Validated sweep lists all four phi-score pairs and the maximum at phi=0.24.|6,1,1,1,1,0,0|Qwen lists the same four cases and identifies the optimum phi.
047|1,0,1,1,0,0,0|incomplete_answer|Agent reports 20% but omits the requested absolute 68 stb/d increase.|2,1,1,1,1,0,0|Qwen gives both 68 stb/d and 20%.
048|3,1,1,1,1,0,0||Validated mean is 190 stb/d and minimum is well A at 162 stb/d.|1,0,1,1,0,0,0|Qwen names A and gives 190/162 but omits stb/d for both requested numerical outputs.
049|2,1,1,1,x,2,2||Agent explicitly rejects the mud-overbalance premise, corrects to formation pressure exceeding mud pressure, and cites drilling evidence.|2,0,1,0,x,0,0|Qwen eventually corrects the kick direction but opens with contradictory '맞습니다', so the correction is not unequivocal.
050|1,0,1,1,x,2,2|incomplete_correction|Agent rejects FWL=OWC and cites capillary separation but does not state the zero-capillary-pressure FWL definition.|1,0,1,0,x,0,0|Qwen rejects equality but says FWL is generally above OWC and does not give the zero-capillary definition.
051|3,0,0,1,x,3,3|contradictory_safe_stop|Agent quotes source for early storage unit slope and plateau onset, yet ends by saying the requested explicit correction remains unverified and stops.|0,0,1,0,x,0,0|Qwen accepts the false flat-derivative premise and incorrectly separates pressure from derivative in early storage.
052|2,1,1,1,x,2,2||Agent rejects the raised-head premise and explains the cited reduced-head advantage and frictional offset.|1,0,1,0,x,0,0|Qwen ultimately mentions lowered head, but also labels the raised-head premise partly correct and repeats it as a definition.
053|1,1,1,1,x,0,0||Agent truthfully reports that no Zephyr-Q relation is verified and computes no number.|1,1,1,1,x,0,0|Qwen declines to invent the absent relation or numerical index.
054|0,0,0,1,x,0,0|incomplete_safe_stop|Agent remains waiting with no visible final explanation that the Lumen-Chi relation is absent.|1,1,1,1,x,0,0|Qwen states the Lumen-Chi relation is not established and does not fabricate a coefficient.
055|0,0,0,0,x,1,0|irrelevant_citation|Agent returns an unrelated grid-refinement quote instead of explaining the missing Raven-Theta definition.|1,1,1,1,x,0,0|Qwen says the named PVT correction is undefined and refrains from computing it.
056|1,1,1,1,x,0,0||Agent safely stops without inventing a Delta-Omega equation or value.|0,0,0,0,x,0,0|Qwen invents a frequency-difference definition for the absent named index before declining a calculation.
057|2,1,1,1,1,2,2||Agent first requests SG, then uses the same run and sourced p90 formula to validate 26.78 °API after the fixed reply.|2,1,1,1,1,0,0|Qwen asks for SG on turn one and then gives about 26.73 °API, within the sealed tolerance.
058|0,0,0,1,0,0,0|retrieval_and_resume_failure|Agent stops before asking for missing porosity, so no same-run sourced F calculation occurs.|1,0,1,1,0,0,0|Qwen asks for phi and applies the right relation, but its 23.07 is outside the frozen tolerance for 23.2233.
059|1,1,1,1,1,0,0||Agent asks once for B, preserves the run, and validates P=58 psi after the reply.|1,1,1,1,1,0,0|Qwen asks for B and then computes 95-37=58 psi.
060|1,0,0,1,1,0,0|false_stop_after_calculation|Agent asks for Q and validates R=7 in the same run, but final status is stopped with insufficient_evidence rather than completed.|1,1,1,1,1,0,0|Qwen asks for Q and completes 84/12=7 after the reply.
""".strip()


def boolean(value: str) -> bool | None:
    return None if value == "x" else value == "1"


def row(flags: str, classes: str, rationale: str) -> dict:
    values = flags.split(",")
    if len(values) != 7:
        raise ValueError(flags)
    covered, goal, completion, hf, numeric, cited, supported = values
    return {
        "goal_success": boolean(goal),
        "task_completion": boolean(completion),
        "claim_count": 0,  # filled from the immutable catalog
        "covered_claims": int(covered),
        "hallucination_free": boolean(hf),
        "numeric_accuracy": boolean(numeric),
        "cited_claims": int(cited),
        "supported_cited_claims": int(supported),
        "citation_omissions": 0,
        "uncertain": False,
        "failure_classes": classes.split(",") if classes else [],
        "rationale": rationale,
    }


def main() -> None:
    packet = json.loads((HERE / "semantic_review_packet.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in packet["items"]}
    parsed = {}
    for raw_line in DECISIONS.splitlines():
        fields = raw_line.split("|")
        if len(fields) != 6:
            raise ValueError(raw_line)
        number, a_flags, a_classes, a_why, q_flags, q_why = fields
        identifier = f"V4-{number}"
        if identifier in parsed:
            raise ValueError(f"Duplicate verdict {identifier}")
        parsed[identifier] = {
            "id": identifier,
            "agent": row(a_flags, a_classes, a_why),
            "qwen_closed_book": row(q_flags, "", q_why),
        }
    if set(parsed) != set(by_id) or len(parsed) != 60:
        raise ValueError("Incomplete 60-task adjudication")
    for identifier, item in parsed.items():
        gold = by_id[identifier]["gold"]
        count = len(gold["atomic_claims"]) + len(gold["numeric_outputs"])
        numeric = bool(gold["numeric_outputs"])
        for condition in ("agent", "qwen_closed_book"):
            verdict = item[condition]
            verdict["claim_count"] = count
            if verdict["covered_claims"] > count:
                raise ValueError(f"Over-coverage {identifier}")
            if (verdict["numeric_accuracy"] is None) == numeric:
                raise ValueError(f"Numeric applicability mismatch {identifier}")
        if item["agent"]["goal_success"] is False and not item["agent"]["failure_classes"]:
            raise ValueError(f"Missing failure class {identifier}")
    result = {
        "catalog_sha256": packet["catalog_sha256"],
        "rubric_sha256": packet["rubric_sha256"],
        "review_method": "single-reviewer AI-assisted semantic adjudication (Codex)",
        "items": [parsed[item["id"]] for item in packet["items"]],
    }
    (HERE / "semantic_scores.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Recorded 60 frozen-rubric paired semantic verdicts")


if __name__ == "__main__":
    main()
