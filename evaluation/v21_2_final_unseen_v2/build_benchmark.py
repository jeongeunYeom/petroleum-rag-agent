"""Author the one-shot benchmark from the preselected, read-only source pool."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path


OUT = Path(__file__).resolve().parent
POOL = json.loads((OUT / "source_pool.json").read_text(encoding="utf-8"))["sources"]
PAGES = {(row["document"], row["page"]): row["text"] for row in POOL}
DOC = {
    "drill": "Heriot-Watt_University_-_Drilling_Engineering.pdf",
    "fe": "Heriot_Watt_University_-_Formation_Evaluation.pdf",
    "re": "Heriot-Watt University - Reservoir Engineering.pdf",
    "pt1": "Heriot-Watt_University_-_Production_Technology_I.pdf",
    "pt2": "Heriot-Watt_University_-_Production_Technology_II.pdf",
    "sim": "Heriot-Watt_University_-_Reservoir_Simulation.pdf",
    "wt": "Heriot-Watt_University_-_Well_Test_Analysis.pdf",
    "lake1": "Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_I.pdf",
    "lake5": "Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf",
}


def source(key: str, page: int, anchor: str, length: int = 450) -> dict:
    document = DOC[key]
    text = PAGES[(document, page)]
    try:
        offset = text.index(anchor)
    except ValueError as error:
        raise ValueError(f"missing source anchor: {document} p.{page} {anchor!r}") from error
    return {"document": document, "page": page, "exact_supporting_span": text[offset:offset + length]}


def numeric(name: str, expression: str, unit: str, abs_tol: float = 0.02, rel_tol: float = 0.001) -> dict:
    value = eval(expression, {"__builtins__": {}}, {"sqrt": math.sqrt})
    assert math.isfinite(value)
    return {"target_name": name, "expected_value": round(value, 12), "expected_unit": unit,
            "absolute_tolerance": abs_tol, "relative_tolerance": rel_tol,
            "computation_expression": expression}


def task(number: int, category: str, domain: str, language: str, question: str,
         claims: list[str], *, goals: list[str] | None = None, sources: list[dict] | None = None,
         forbidden: list[str] | None = None, targets: list[dict] | None = None,
         formula: dict | None = None, missing: list[str] | None = None,
         answerable: bool = True) -> dict:
    return {
        "task_id": f"V212U-{number:03d}", "category": category, "domain": domain,
        "question_language": language, "question": question, "answerable": answerable,
        "multi_goal": goals is not None, "required_goals": goals or [question],
        "required_claims": claims, "forbidden_claims": forbidden or [],
        "gold_sources": sources or [], "numeric_targets": targets or [],
        "formula_source": formula or {"required": False}, "missing_inputs": missing or [],
        "citation_required_for_agent": bool(sources),
    }


tasks = [
    task(1,"knowledge_qa","drilling","ko","시추 중 과압 전이대로 들어갈 때, 다른 시추 조건이 같다면 굴진율(ROP)은 보통 어떻게 변하나요?",
         ["A less compacted, more porous transition zone increases ROP."], sources=[source("drill",177,"In the transition zone the rock will be more porous",410)]),
    task(2,"knowledge_qa","petrophysics","ko","밀도 검층기의 감마선 산란 신호가 실제로 민감한 지층의 물리량은 무엇인가요?",
         ["Density-tool response is essentially governed by formation electron density."], sources=[source("fe",73,"The number of Compton-scattering collisions",550)]),
    task(3,"knowledge_qa","reservoir_engineering","ko","사암의 공극률을 판단할 때 모래 알갱이의 절대 크기만 보면 충분한가요?",
         ["Absolute grain size alone does not determine sandstone porosity; grain-size variation matters."], sources=[source("re",219,"The absolute sizes of the sand grains",280)]),
    task(4,"knowledge_qa","production_technology","en","What happens to rock permeability immediately around a shaped-charge perforation tunnel?",
         ["The adjacent crushed/compacted zone has substantially lower permeability than the original rock."], sources=[source("pt1",282,"The zone immediately adjacent to the",300)]),
    task(5,"knowledge_qa","production_technology","ko","튜빙 세척(tubing wash)은 매트릭스 처리와 달리 유체를 지층에 주입하나요? 핵심 차이를 설명해줘.",
         ["Tubing wash fluid is normally retained inside tubing and not injected into the formation."], sources=[source("pt2",267,"The treatment fluid is normally",340)]),
    task(6,"knowledge_qa","reservoir_simulation","ko","저류층 시뮬레이션에서 격자를 더 촘촘히 해도 회수율 곡선이 거의 바뀌지 않으면, 격자 오차를 어떻게 해석해야 하나요?",
         ["Grid convergence means grid errors are probably a small contribution to overall uncertainty."], sources=[source("sim",128,"refinement, the answer",360)]),
    task(7,"knowledge_qa","well_testing","ko","압력천이시험의 middle-time region을 로그 도함수 그래프에서 어떤 형태로 알아볼 수 있나요?",
         ["In the MTR, the logarithmic pressure derivative attains a constant plateau."], sources=[source("wt",218,"The MTR (when present) is characterised",280)]),
    task(8,"knowledge_qa","production_technology","en","Which operating conditions should guide the material choice for artificial-lift equipment?",
         ["Bottomhole temperature, corrosive conditions, solids production, and producing velocities inform material choice."], sources=[source("pt2",76,"The choice of materials",520)]),

    task(9,"multi_claim_reasoning","drilling","en","For exploration-well casing design, explain why a higher load margin is needed and what contingency the casing layout should retain.",
         ["Exploration-well loads are estimated rather than learned from previous wells.","Exploration casing design should use a higher safety margin.","Its configuration should allow an extra casing string if needed."],
         goals=["Explain load uncertainty and margin","State layout contingency"], sources=[source("drill",258,"When drilling a development well",850)]),
    task(10,"multi_claim_reasoning","petrophysics","ko","유도 검층에서 송신 코일의 교류가 수신 전압으로 이어지는 경로와 bucking coil의 역할을 각각 설명해줘.",
         ["Transmitter alternating field induces formation currents and a receiver voltage.","Receiver voltage is proportional to formation conductivity.","Bucking coils remove direct transmitter-receiver coupling."],
         goals=["Explain signal path","Explain bucking-coil role"], sources=[source("fe",98,"A high frequency alternating current",1050)]),
    task(11,"multi_claim_reasoning","reservoir_engineering","en","In sweep assessment, compare the uncertainty of areal and vertical sweep, and describe how production history can constrain areal sweep.",
         ["Areal sweep is considered more uncertain than vertical sweep.","Vertical sweep calculation combined with recovery production data can history-match areal sweep."],
         goals=["Compare uncertainty","Describe history matching"], sources=[source("re",784,"Dake2 considered",460)]),
    task(12,"multi_claim_reasoning","production_technology","ko","다자간정(multilateral well)이 단일 유정 투자비와 전체 유전 개발비에 미치는 영향을 각각 설명해줘.",
         ["Capital cost per multilateral well is higher.","Total field development cost may be lower because fewer wells are needed."],
         goals=["Explain per-well capital cost","Explain field-level development cost"], sources=[source("pt1",420,"Characteristics of multi-lateral well costs",360)]),
    task(13,"multi_claim_reasoning","production_technology","en","In a tectonically relaxed setting, explain the stress direction a hydraulic fracture propagates toward and its expected plane orientation.",
         ["Fracture propagation is perpendicular to minimum in-situ stress.","In a relaxed environment, its expected plane is vertical and trends along intermediate/maximum horizontal stress."],
         goals=["Identify propagation direction","Identify expected orientation"], sources=[source("pt2",324,"Propagation of a Hydraulic Fracture",700)]),
    task(14,"multi_claim_reasoning","reservoir_simulation","ko","물젖음 저류층의 물주입 시뮬레이션에서 drainage 곡선을 그대로 입력하면 왜 문제가 될 수 있는지, 이력현상의 두 원인과 함께 설명해줘.",
         ["Pore-structure hysteresis makes filling and emptying occur at different capillary pressures.","Topological hysteresis distinguishes imbibition and drainage pathways.","A water-wet waterflood should not use drainage curves as simulation input indiscriminately."],
         goals=["Explain hysteresis mechanisms","Explain input-curve choice"], sources=[source("sim",326,"Pore structure hysteresis",650)]),

    task(15,"direct_calculation","production_technology","en","A well's water cut moved from 18% to 27%. What is the change in percentage points?",
         ["Water cut increased by 9 percentage points."], targets=[numeric("water_cut_change","27-18","percentage points")]),
    task(16,"direct_calculation","production_technology","en","A pump ran at 420 bbl/d for 8 hours and 540 bbl/d for the next 16 hours. Find its 24-hour time-weighted rate.",
         ["The time-weighted daily-average rate is 500 bbl/d."], targets=[numeric("time_weighted_rate","(420*8+540*16)/24","bbl/d")]),
    task(17,"direct_calculation","reservoir_engineering","en","Gas injection rose from 1.8 to 2.25 MMscf/d. Calculate the percentage increase relative to the initial rate.",
         ["Gas-injection rate increased by 25%."], targets=[numeric("percent_increase","(2.25-1.8)/1.8*100","%")]),
    task(18,"direct_calculation","production_technology","en","A separator receives 255 stb/d oil and 85 stb/d water. What percentage of the total liquid rate is oil?",
         ["Oil is 75% of total liquid throughput."], targets=[numeric("oil_fraction","255/(255+85)*100","%")]),
    task(19,"direct_calculation","reservoir_engineering","en","Water injection volumes on three days were 1350, 1425 and 1275 bbl. What is the cumulative injected volume?",
         ["The cumulative injected volume is 4050 bbl."], targets=[numeric("cumulative_injection","1350+1425+1275","bbl")]),
    task(20,"direct_calculation","production_technology","en","A tank falls from 1750 to 1435 bbl over 7 hours. What is its average net withdrawal rate in bbl/h?",
         ["Average net withdrawal is 45 bbl/h."], targets=[numeric("withdrawal_rate","(1750-1435)/7","bbl/h")]),

    task(21,"user_formula","production_technology","en","Use only the supplied relation t = V/Q. A separator holds V=120 bbl and liquid outflow is Q=30 bbl/min. Calculate residence time.",
         ["Residence time is 4 min."], targets=[numeric("residence_time","120/30","min")]),
    task(22,"user_formula","drilling","en","For this site test define a dimensionless power index H = 0.5 × Q × ΔP. With Q=8 and ΔP=22, compute H.",
         ["The supplied dimensionless power index is 88."], targets=[numeric("power_index","0.5*8*22","dimensionless")]),
    task(23,"user_formula","production_technology","en","For this treatment use the supplied rule chemical mass = dosage × fluid volume. Dosage is 0.45 kg/m3 and volume is 280 m3. Find chemical mass.",
         ["Required chemical mass is 126 kg."], targets=[numeric("chemical_mass","0.45*280","kg")]),
    task(24,"user_formula","reservoir_engineering","en","Use the provided relation pore volume = area × thickness × porosity. Area=1500 m2, thickness=8 m, and porosity=0.17. What is pore volume?",
         ["Pore volume is 2040 m3."], targets=[numeric("pore_volume","1500*8*0.17","m3")]),

    task(25,"kb_formula","drilling","ko","내부 시추 교재에 따른 머드펌프의 총 유압 마력을 구해줘. 토출압력 Pt=2100 psi, 유량 Q=410 gpm이야.",
         ["The sourced relation is HHPt = Pt × Q / 1714.","Total hydraulic horsepower is about 502.33 hp."],
         sources=[source("drill",406,"HHPt =",330)],
         targets=[numeric("total_hhp","2100*410/1714","hp")],
         formula={"required":True,"document":DOC["drill"],"page":406,"exact_formula_span":source("drill",406,"HHPt =",55)["exact_supporting_span"]}),
    task(26,"kb_formula","petrophysics","ko","내부 지층평가 자료의 식으로 선형 유동량을 계산해줘. 투과도 0.75 Darcy, 단면적 8 cm², 압력차 2 atm, 길이 4 cm, 점도 1.5 cP야.",
         ["The sourced Darcy relation is Q=kAΔP/(lμ).","Flow is 2 cm3/s."],
         sources=[source("fe",28,"Q = k  A",540)],
         targets=[numeric("darcy_flow","0.75*8*2/(4*1.5)","cm3/s")],
         formula={"required":True,"document":DOC["fe"],"page":28,"exact_formula_span":source("fe",28,"Q = k  A",25)["exact_supporting_span"]}),
    task(27,"kb_formula","production_technology","en","Consult the internal gas-well deliverability relation. With C=0.015 Mscf/d per (psi²)^n, PR=2400 psi, Pwf=1800 psi and n=0.75, calculate gas rate.",
         ["The sourced relation is q=C(PR²−Pwf²)^n.","Gas rate is about 948.73 Mscf/d."],
         sources=[source("pt2",11,"q = C (PR",310)],
         targets=[numeric("gas_rate","0.015*(2400**2-1800**2)**0.75","Mscf/d",0.1)],
         formula={"required":True,"document":DOC["pt2"],"page":11,"exact_formula_span":source("pt2",11,"q = C (PR",40)["exact_supporting_span"]}),
    task(28,"kb_formula","reservoir_engineering","en","Use the internal handbook gas-density equation for SI inputs: p=12000 kPa, gas gravity γg=0.67, z=0.89, and T=350 K. Compute density.",
         ["The sourced SI relation is ρg=3.4834 pγg/(zT).","Gas density is about 89.91 kg/m3."],
         sources=[source("lake5",993,"For pressure in kPa",170)],
         targets=[numeric("gas_density","3.4834*12000*0.67/(0.89*350)","kg/m3",0.1)],
         formula={"required":True,"document":DOC["lake5"],"page":993,"exact_formula_span":source("lake5",993,"ρg = 3.4834",55)["exact_supporting_span"]}),
    task(29,"kb_formula","reservoir_engineering","en","Find the internal handbook definition of volumetric strain. If a rock sample changes volume by ΔV=-12 cm3 from an initial V=800 cm3, calculate εV.",
         ["The sourced definition is εV=ΔV/V.","Volumetric strain is -0.015 dimensionless."],
         sources=[source("lake1",606,"εV = ΔV",120)],
         targets=[numeric("volumetric_strain","-12/800","dimensionless",0.0001)],
         formula={"required":True,"document":DOC["lake1"],"page":606,"exact_formula_span":source("lake1",606,"εV = ΔV",18)["exact_supporting_span"]}),
    task(30,"kb_formula","production_technology","en","According to the internal production text, calculate vertical-lift pressure loss when friction, hydrostatic-head and kinetic contributions are 65, 210 and 5 psi.",
         ["The sourced relation is ΔPVL=ΔPFRICT+ΔPHHD+ΔKE.","Vertical-lift pressure loss is 280 psi."],
         sources=[source("pt1",33,"∆PVL = ∆PFRICT",260)],
         targets=[numeric("vertical_lift_loss","65+210+5","psi")],
         formula={"required":True,"document":DOC["pt1"],"page":33,"exact_formula_span":source("pt1",33,"∆PVL = ∆PFRICT",38)["exact_supporting_span"]}),

    task(31,"false_premise","reservoir_simulation","en","Unsteady-state relative-permeability tests normally take longer than steady-state tests, so we should choose them for the most reservoir-representative measurements, correct?",
         ["The premise is false: unsteady-state tests are usually faster.","Steady-state measurements at low rates are considered most indicative of reservoir behaviour."],
         forbidden=["Unsteady-state tests are normally slower than steady-state tests."],
         sources=[source("sim",303,"Relative permeabilities can be measured",670),source("sim",303,"Although the time involved",280)]),
    task(32,"false_premise","production_technology","ko","PCP에 가스가 섞이면 펌프 효율이 좋아지니 가스 앵커는 필요 없다는 설명이 맞나요? 내부 자료로 교정해줘.",
         ["The premise is false: gas reduces PCP efficiency.","A gas anchor is frequently included in PCP completions."],
         forbidden=["Gas improves PCP efficiency."], sources=[source("pt2",125,"The presence of gas reduces",200)]),
    task(33,"false_premise","well_testing","en","In a bounded reservoir, boundary effects leave the late-time drawdown semilog line unchanged from the infinite-acting middle-time line, right?",
         ["The premise is false: boundary effects cause the late-time semilog plot to curve downward.","The straight-line middle-time region follows wellbore storage and corresponds to infinite-acting flow."],
         forbidden=["Late-time boundary effects leave the infinite-acting semilog straight line unchanged."],
         sources=[source("wt",318,"The semilog plot of the drawdown data",520),source("wt",318,"The late time region commences",390)]),

    task(34,"unanswerable","drilling","en","Use H = pressure × flow / 1714 to find mud-pump horsepower. The pressure is 2450 psi, but the flow rate has not been measured. Give the horsepower now.",
         ["Horsepower cannot be computed without a flow rate.","Request the missing flow rate instead of inventing it."],
         forbidden=["A numeric horsepower value is established."], missing=["flow rate Q in gpm"], answerable=False),
    task(35,"unanswerable","petrophysics","en","For a core test use k = QμL/(AΔP). Q=2 cm3/s, μ=1 cP, L=6 cm and ΔP=3 atm, but the core cross-sectional area was not supplied. Determine k numerically.",
         ["Permeability cannot be computed without core area A.","Ask for A in cm2; do not guess it."],
         forbidden=["A numeric permeability value is established."], missing=["core cross-sectional area A in cm2"], answerable=False),
    task(36,"unanswerable","production_technology","en","Use treatment chemical mass = dosage × total fluid volume. The dosage is 0.6 kg/m3, but the planned fluid volume is unknown. State the exact chemical mass.",
         ["Exact chemical mass is undetermined without fluid volume.","Request total fluid volume in m3."],
         forbidden=["A numeric chemical mass is established."], missing=["total fluid volume in m3"], answerable=False),
]

resume = [
    {"probe_id":"V212R-01","domain":"production_technology","turn_1":"For this separator, use residence time = liquid volume / outflow. Liquid volume is 147 bbl. Calculate residence time, but I do not yet have the outflow rate.","turn_2":"The outflow rate is 21 bbl/min.","missing_input":"outflow rate","expected_value":7.0,"expected_unit":"min"},
    {"probe_id":"V212R-02","domain":"drilling","turn_1":"Use the provided field rule pump energy index = 0.4 × displacement × pressure change. Displacement is 12 units. Determine the index; pressure change will follow.","turn_2":"Pressure change is 35 units.","missing_input":"pressure change","expected_value":168.0,"expected_unit":"index units"},
    {"probe_id":"V212R-03","domain":"production_technology","turn_1":"Use produced-water mass = volume × density. Produced-water volume is 64 m3. Find mass once density is available.","turn_2":"Measured density is 1025 kg/m3.","missing_input":"water density","expected_value":65600.0,"expected_unit":"kg"},
    {"probe_id":"V212R-04","domain":"reservoir_engineering","turn_1":"For this lab comparison use pore-volume change = bulk volume × porosity change. Bulk volume is 260 m3. Find the change, but I have not supplied porosity change yet.","turn_2":"The porosity change is 0.035 (dimensionless).","missing_input":"porosity change","expected_value":9.1,"expected_unit":"m3"},
]


def validate() -> None:
    assert len(tasks) == 36 and len(resume) == 4
    assert len({row["task_id"] for row in tasks}) == 36
    assert Counter(row["category"] for row in tasks) == {
        "knowledge_qa":8,"multi_claim_reasoning":6,"direct_calculation":6,
        "user_formula":4,"kb_formula":6,"false_premise":3,"unanswerable":3}
    assert sum(bool(row["numeric_targets"]) for row in tasks) == 16
    assert sum(row["question_language"] == "ko" for row in tasks) == 12
    assert sum(row["multi_goal"] for row in tasks) == 6
    for row in tasks:
        if row["category"] == "kb_formula":
            f = row["formula_source"]
            assert f["required"] and f["exact_formula_span"] in PAGES[(f["document"], f["page"])]
        if row["gold_sources"]:
            assert all(s["exact_supporting_span"] in PAGES[(s["document"],s["page"])] for s in row["gold_sources"])
        if row["category"] in {"knowledge_qa","multi_claim_reasoning","kb_formula","false_premise"}:
            assert row["gold_sources"]
        if not row["answerable"]:
            assert row["missing_inputs"] and not row["numeric_targets"]


if __name__ == "__main__":
    validate()
    (OUT / "benchmark.json").write_text(json.dumps({"primary_tasks":tasks,"resume_probes":resume},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"primary":len(tasks),"resume":len(resume),"numeric":sum(bool(x["numeric_targets"]) for x in tasks),"korean":sum(x["question_language"]=="ko" for x in tasks),"multi_goal":sum(x["multi_goal"] for x in tasks)},indent=2))
