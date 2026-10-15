"""Build one source-audited, development-isolated 60-task V4 catalog.

Run once before any V4 model execution. Refuses to overwrite the sealed catalog.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "v4_catalog.json"
HASH = HERE / "v4_catalog.sha256"

# Each key is a literal phrase in the existing Chroma source, not a generated quote.
SOURCE_SPECS = {
    "pvt_above": ("Reservoir Engineering", 165, "When the reservoir pressure is above the"),
    "pvt_bubble": ("Reservoir Engineering", 165, "gas does not come out of solution until the bubble point"),
    "gaslift_need": ("Production_Technology_I", 12, "reservoir pressure is\ninsufficient"),
    "gaslift_gradient": ("Production_Technology_I", 12, "head by injecting gas into the stream"),
    "sim_options": ("Reservoir_Simulation", 15, "much cheaper to model these four cases"),
    "sim_uncertainty": ("Reservoir_Simulation", 15, "assess each of the various uncertainties"),
    "sim_big_decisions": ("Reservoir_Simulation", 19, "biggest - i.e. most expensive"),
    "sim_appraisal": ("Reservoir_Simulation", 19, "least amount of data"),
    "monel": ("Drilling_Engineering", 494, "These collars are made from Monel"),
    "steel_magnetic": ("Drilling_Engineering", 494, "magnetic compass will be incorrect"),
    "derivative_problem": ("Well_Test_Analysis", 219, "lack of definiteness in the pressure match"),
    "derivative_added": ("Well_Test_Analysis", 219, "include the dimensionless derivative response"),
    "storage_overlap": ("Well_Test_Analysis", 219, "overlay on the unit slope diagonal"),
    "derivative_plateau": ("Well_Test_Analysis", 219, "derivative becoming constant"),
    "water_sat": ("Formation_Evaluation", 164, "Water saturation is the fraction"),
    "other_pore_fluid": ("Formation_Evaluation", 164, "pore volume not filled with water is filled with hydrocarbons"),
    "archie_clean": ("Formation_Evaluation", 164, "based on Archie"),
    "breakthrough": ("Reservoir Engineering", 744, "Until breakthrough, only oil is produced"),
    "fractional_flow": ("Reservoir Engineering", 790, "resulting fractional flow curve determines"),
    "compact": ("Reservoir Engineering", 242, "pore pressure declines during production"),
    "initial_porosity": ("Reservoir Engineering", 242, "initial porosity in the reservoir"),
    "carbonate": ("Formation_Evaluation", 165, "in carbonates, F = 1/"),
    "sand_humble": ("Formation_Evaluation", 165, "in sands, F = 0.62/"),
    "sand_simple": ("Formation_Evaluation", 165, "F = 0.81/"),
    "rft_profile": ("Reservoir Engineering", 70, "main application is to provide pressure -depth profiles"),
    "rft_probe": ("Reservoir Engineering", 70, "device places a probe through the well mud cake"),
    "fwl": ("Reservoir Engineering", 70, "FWL, is not coincident with the oil-water contact OWC"),
    "fwl_zero": ("Reservoir Engineering", 70, "free water level is the depth at which the capillary pressure"),
    "tubing_wash": ("Production_Technology_II", 267, "used to improve the well outflow by removing deposits"),
    "matrix_acid": ("Production_Technology_II", 267, "Matrix treatments, and acidising in particular, aim to remove"),
    "kick": ("Drilling_Engineering", 17, "formation pressure exceeding the pressure exerted by the mud column"),
    "api_formula": ("Reservoir Engineering", 90, "API = (141.5 / SG) -131.5"),
    "generic_f": ("Formation_Evaluation", 164, "F  = a/fm"),
    "rt_formula": ("Formation_Evaluation", 167, "Rt = Ro/Sw"),
    "po_formula": ("Reservoir Engineering", 242, "Po = Pf + Pc"),
    "gor_formula": ("Reservoir Engineering", 559, "GOR = (V1+V2) / L2"),
    "bo_formula": ("Reservoir Engineering", 559, "Bo = Vres / L2"),
}


def read_sources() -> dict[str, dict]:
    import chromadb

    sqlite = Path(os.environ["DATA_DIR"]).resolve() / "vector_db" / "chroma.sqlite3"
    if not sqlite.is_file():
        raise RuntimeError("Existing ChromaDB missing; never create a replacement")
    collection = chromadb.PersistentClient(path=str(sqlite.parent)).get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        raise RuntimeError("Existing KB count changed")
    rows = collection.get(include=["documents", "metadatas"])
    sources = {}
    for key, (name_hint, page, needle) in SOURCE_SPECS.items():
        matches = []
        for chunk_id, passage, metadata in zip(rows["ids"], rows["documents"], rows["metadatas"]):
            metadata = metadata or {}
            if (name_hint.casefold() not in str(metadata.get("document") or "").casefold()
                    or str(metadata.get("page")) != str(page)):
                continue
            pattern = re.compile(r"\s+".join(re.escape(part) for part in needle.split()), re.I)
            matched = pattern.search(passage)
            if matched:
                matches.append((chunk_id, passage, metadata, matched))
        if not matches:
            raise RuntimeError(f"Literal KB span not found: {key} {name_hint} p.{page} {needle!r}")
        chunk_id, passage, metadata, matched = matches[0]
        start = max(0, matched.start() - 180)
        end = min(len(passage), matched.end() + 320)
        span = passage[start:end]
        if matched.group(0) not in span:
            raise AssertionError(key)
        sources[key] = {"key": key, "document": metadata["document"], "page": page,
                        "chunk_id": chunk_id, "literal_span": span, "needle": matched.group(0)}
    return sources


def claim(text: str, *source_keys: str, support: str = "explicit") -> dict:
    return {"text": text, "source_keys": list(source_keys), "support": support}


def number(target: str, value: float, unit: str, formula: str, bindings: dict,
           *, source_key: str | None = None, tolerance: float | None = None) -> dict:
    return {"target": target, "value": round(value, 8),
            "tolerance": tolerance if tolerance is not None else max(0.02, abs(value) * 0.005),
            "unit": unit, "formula": formula, "bindings": bindings,
            "requires_kb_formula": source_key is not None,
            "formula_source_keys": [source_key] if source_key else []}


def make_catalog(sources: dict[str, dict]) -> dict:
    tasks: list[dict] = []

    def add(category: str, language: str, domain: str, prompt: str, *,
            claims: list[dict] | None = None, numbers: list[dict] | None = None,
            follow_up: str | None = None, false_premise: dict | None = None,
            unanswerable: dict | None = None, resume: dict | None = None,
            visitor_style: bool = False) -> None:
        claims = claims or []
        numbers = numbers or []
        keys = {key for item in claims for key in item["source_keys"]}
        keys.update(key for item in numbers for key in item["formula_source_keys"])
        for key in keys:
            if key not in sources:
                raise AssertionError(f"Unknown gold source: {key}")
        goals = [item["text"] for item in claims]
        goals.extend(f"{item['target']} = {item['value']} {item['unit']}" for item in numbers)
        task = {"id": f"V4-{len(tasks) + 1:03d}", "category": category,
                "language": language, "domain": domain, "prompt": prompt,
                "follow_up": follow_up, "visitor_style": visitor_style,
                "gold": {"required_goals": goals, "atomic_claims": claims,
                         "numeric_outputs": numbers,
                         "source_spans": [sources[key] for key in sorted(keys)]}}
        if false_premise:
            task["gold"]["false_premise"] = false_premise
        if unanswerable:
            task["gold"]["unanswerable"] = unanswerable
        if resume:
            task["gold"]["resume"] = resume
        tasks.append(task)

    # 12 KB-grounded knowledge / explanation tasks: 5 KO, 5 EN, 2 mixed.
    add("knowledge", "ko", "reservoir fluids / PVT",
        "버블포인트보다 높은 압력의 원유에서는 자유 가스가 곧바로 나오나요? 내부 유체 교재 기준으로 설명해줘.",
        claims=[claim("Above bubble point the oil is undersaturated", "pvt_above"),
                claim("Gas does not leave solution until bubble point is reached", "pvt_bubble")], visitor_style=True)
    add("knowledge", "en", "production / artificial lift",
        "In the production notes, when is assisted lift considered, and what does injected lift gas change inside tubing? Cite both points.",
        claims=[claim("Artificial lift is considered when reservoir pressure is insufficient", "gaslift_need"),
                claim("Gas injection lowers the hydrostatic head / tubing pressure gradient", "gaslift_gradient")])
    add("knowledge", "ko", "reservoir simulation",
        "개발안 여러 개를 현장에서 직접 시도하는 대신 모델로 비교하는 실무적 이점과 예측상 주의점을 자료 근거로 알려줘.",
        claims=[claim("Modeling options is cheaper than implementing them to test them", "sim_options"),
                claim("Forward predictions carry model uncertainty", "sim_uncertainty")])
    add("knowledge", "en", "drilling / directional survey",
        "Our compass survey needs Monel collars near the drillstring. Which magnetic error are they meant to avoid? Use the drilling manual.",
        claims=[claim("Magnetized steel can distort a magnetic compass", "steel_magnetic"),
                claim("Monel collars leave Earth's magnetic field undisturbed near the survey tool", "monel")])
    add("knowledge", "mixed", "well testing",
        "type-curve matching에서 derivative trace를 함께 보면 pressure-only matching의 어떤 약점을 보완하나요? 내부 well-test 근거로 짧게 답해줘.",
        claims=[claim("Pressure-only type-curve matching lacks definiteness", "derivative_problem"),
                claim("The derivative adds a characteristic response to the type curve", "derivative_added")],
        visitor_style=True)
    add("knowledge", "ko", "petrophysics",
        "깨끗한 지층에서 Sw가 어느 체적에 대한 물의 비율인지, 물이 차지하지 않은 공극은 보통 무엇으로 간주하는지 설명해줘.",
        claims=[claim("Water saturation is water-filled fraction of pore volume", "water_sat"),
                claim("The remaining pore volume is generally assumed hydrocarbon-filled", "other_pore_fluid")])
    add("knowledge", "en", "waterflood / reservoir engineering",
        "From the internal waterflood chapter, what happens to water cut after breakthrough, and what does the fractional-flow curve indicate about later oil production?",
        claims=[claim("Water cut increases after breakthrough", "breakthrough"),
                claim("Fractional-flow shape characterizes breakthrough saturation and subsequent oil production", "fractional_flow")])
    add("knowledge", "en", "reservoir compaction",
        "During depletion, what happens to pore spaces as pore pressure falls, and why does the initial porosity matter to reserves estimates?",
        claims=[claim("Declining pore pressure accompanies pore-space compaction", "compact"),
                claim("Initial porosity defines initial oil-in-place volume", "initial_porosity")])
    add("knowledge", "ko", "petrophysics",
        "공극률과 formation factor의 교재 관계식에서 탄산염암용 식과 사암용 Humble 식을 나란히 적어줘.",
        claims=[claim("Carbonate relation uses F = 1/φ²", "carbonate"),
                claim("Sand Humble relation uses F = 0.62/φ^2.15", "sand_humble")])
    add("knowledge", "mixed", "formation pressure / RFT",
        "RFT open-hole survey는 pressure-depth profile을 어떻게 얻나요? probe와 mud cake의 역할도 내부 자료로 확인해줘.",
        claims=[claim("RFT provides pressure-depth profiles in open hole", "rft_profile"),
                claim("A probe passes through mud cake to take pressure measurements", "rft_probe")])
    add("knowledge", "ko", "stimulation / production",
        "튜빙 세척과 matrix acidising은 처리 대상이 어떻게 다른가요? 주입 위치를 헷갈리지 않게 내부 교재로 구분해줘.",
        claims=[claim("Tubing wash removes tubing deposits without injecting into formation", "tubing_wash"),
                claim("Matrix acidising addresses near-wellbore formation-damage pressure drop", "matrix_acid")],
        visitor_style=True)
    add("knowledge", "en", "reservoir simulation / appraisal",
        "Why might an appraisal-stage reservoir model be especially uncertain even though facilities decisions are most consequential then?",
        claims=[claim("Appraisal involves large facilities investment decisions", "sim_big_decisions"),
                claim("Appraisal has little data or production history, weakening forecasts", "sim_appraisal")])

    # Eight direct, user-value-only deterministic calculations.
    add("direct", "ko", "production rates", "A정 136, B정 211, C정 73 stb/d야. 세 정의 합계 유량만 계산해줘.",
        numbers=[number("total_rate", 420, "stb/d", "A+B+C", {"A":136,"B":211,"C":73})])
    add("direct", "en", "pressure", "Gauge P_up reads 2780 psi and P_down reads 2550 psi. What is P_up minus P_down?",
        numbers=[number("pressure_difference", 230, "psi", "P_up-P_down", {"P_up":2780,"P_down":2550})])
    add("direct", "mixed", "production rates", "세 well의 q가 각각 180, 240, 300 stb/d입니다. arithmetic mean rate?",
        numbers=[number("mean_rate", 240, "stb/d", "(180+240+300)/3", {"q1":180,"q2":240,"q3":300})], visitor_style=True)
    add("direct", "en", "production decline", "Oil rate went from 780 stb/d to 663 stb/d. Give the percentage decrease relative to the old rate.",
        numbers=[number("percentage_decrease", 15, "%", "(780-663)/780*100", {"old":780,"new":663})])
    add("direct", "ko", "PVT ratio", "분리기 가스 3780 scf, 오일 135 stb라면 가스량을 오일량으로 나눈 비는 얼마야?",
        numbers=[number("gas_over_oil", 28, "scf/stb", "gas/oil", {"gas":3780,"oil":135})])
    add("direct", "en", "well-rate comparison", "Only use these rates: A=155, B=208, C=197 stb/d. Name the largest well and its rate.",
        claims=[claim("Well B has the largest stated rate")],
        numbers=[number("maximum_rate_B", 208, "stb/d", "max(A,B,C)", {"A":155,"B":208,"C":197})])
    add("direct", "ko", "pressure change", "저류층 압력이 1600 psi에서 1760 psi로 올랐어. 처음 값 대비 증가율 계산해줘.",
        numbers=[number("increase_percent", 10, "%", "(1760-1600)/1600*100", {"initial":1600,"final":1760})])
    add("direct", "mixed", "pressure readings", "P_high=3025 psi, P_low=2860 psi. 두 값의 absolute difference만 구해줘.",
        numbers=[number("absolute_difference", 165, "psi", "P_high-P_low", {"P_high":3025,"P_low":2860})],
        visitor_style=True)

    # Eight calculations whose equations are explicitly supplied by the visitor.
    add("user_formula", "ko", "pressure accounting", "P_in=1450 psi, P_loss=175 psi이고 내 식은 P_net=P_in-P_loss야. P_net을 계산해줘.",
        numbers=[number("P_net", 1275, "psi", "P_in-P_loss", {"P_in":1450,"P_loss":175})])
    add("user_formula", "en", "dimensionless index", "Use my definition Z=x*y+4, with x=6 and y=11 (both dimensionless). Evaluate Z.",
        numbers=[number("Z", 70, "dimensionless", "x*y+4", {"x":6,"y":11})])
    add("user_formula", "mixed", "porosity score", "phi=0.24야. 사용자 정의 score = 12 + 35*phi 를 적용하면 score는? (dimensionless)",
        numbers=[number("score", 20.4, "dimensionless", "12+35*phi", {"phi":0.24})],
        visitor_style=True)
    add("user_formula", "ko", "production volume", "유량 q=145 stb/d가 6 day 유지돼. 내가 준 식 V=q*t로 누적 부피 V를 구해줘.",
        numbers=[number("V", 870, "stb", "q*t", {"q":145,"t":6})], visitor_style=True)
    add("user_formula", "en", "pressure average", "A=33 psi and B=51 psi. I define R=(A+B)/2. What is R?",
        numbers=[number("R", 42, "psi", "(A+B)/2", {"A":33,"B":51})])
    add("user_formula", "en", "rate-change index", "My percentage formula is I=(final-initial)/initial*100. Initial=80 stb/d, final=96 stb/d; compute I.",
        numbers=[number("I", 20, "%", "(final-initial)/initial*100", {"initial":80,"final":96})])
    add("user_formula", "ko", "user-defined index", "m=7(무차원)이야. 이번 문제에서만 F=3*m+2로 정의했으니 F를 계산해줘.",
        numbers=[number("F", 23, "dimensionless", "3*m+2", {"m":7})])
    add("user_formula", "mixed", "dimensionless ratio", "x=32, y=48, z=5 (all dimensionless). 내 관계식 E=(x+y)/z를 써서 E 값은?",
        numbers=[number("E", 16, "dimensionless", "(x+y)/z", {"x":32,"y":48,"z":5})])

    # Twelve sourced KB equations. The execution expression may normalize PDF layout,
    # but each gold citation is the original literal chunk, not the normalized equation.
    add("kb_formula", "ko", "PVT / API gravity", "SG가 0.883인 원유의 °API를 내부 PVT 교재에서 변환식을 확인한 다음 계산해줘.",
        claims=[claim("The sourced relation is API = 141.5/SG - 131.5", "api_formula")],
        numbers=[number("API", 141.5/0.883-131.5, "°API", "141.5/SG-131.5", {"SG":0.883}, source_key="api_formula")])
    add("kb_formula", "en", "PVT / API gravity", "An oil has SG=0.956. Locate the textbook's API conversion equation, then give its API gravity with a formula citation.",
        claims=[claim("The sourced relation is API = 141.5/SG - 131.5", "api_formula")],
        numbers=[number("API", 141.5/0.956-131.5, "°API", "141.5/SG-131.5", {"SG":0.956}, source_key="api_formula")])
    add("kb_formula", "mixed", "carbonate petrophysics", "carbonate sample의 porosity phi=0.17이야. 교재에 있는 carbonate용 F relation을 찾아 formation factor를 계산해줘.",
        claims=[claim("Carbonate source uses F = 1/φ²", "carbonate")],
        numbers=[number("F", 1/0.17**2, "dimensionless", "1/phi^2", {"phi":0.17}, source_key="carbonate")],
        visitor_style=True)
    add("kb_formula", "ko", "carbonate petrophysics", "탄산염암 공극률이 28%일 때 formation factor는 얼마야? 해당 암종의 내부 식에 연결해서 답해줘.",
        claims=[claim("Carbonate source uses F = 1/φ²", "carbonate")],
        numbers=[number("F", 1/0.28**2, "dimensionless", "1/phi^2", {"phi":0.28}, source_key="carbonate")])
    add("kb_formula", "en", "sand petrophysics", "For a sand with porosity 0.23, use the sourced Humble formation-factor equation rather than the carbonate relation. Compute F.",
        claims=[claim("Sand Humble source uses F = 0.62/φ^2.15", "sand_humble")],
        numbers=[number("F", 0.62/0.23**2.15, "dimensionless", "0.62/phi^2.15", {"phi":0.23}, source_key="sand_humble")])
    add("kb_formula", "en", "sand petrophysics", "Find the textbook's simpler sand approximation F=0.81/phi²; apply it to phi=0.27 and cite the actual equation span.",
        claims=[claim("A sourced simpler sand form is F = 0.81/φ²", "sand_simple")],
        numbers=[number("F", 0.81/0.27**2, "dimensionless", "0.81/phi^2", {"phi":0.27}, source_key="sand_simple")])
    add("kb_formula", "ko", "formation factor", "phi=0.21, a=0.8, m=2.1이야. 일반 formation-factor 식의 원문을 내부 자료에서 찾아 F를 구해줘.",
        claims=[claim("Source-layout equation F=a/fm denotes the porosity-exponent relation with m cementation factor", "generic_f", support="source-layout interpretation")],
        numbers=[number("F", 0.8/0.21**2.1, "dimensionless", "a/phi^m", {"a":0.8,"phi":0.21,"m":2.1}, source_key="generic_f")],
        visitor_style=True)
    add("kb_formula", "mixed", "resistivity / saturation", "Ro=3.6 ohm-m이고 Sw=0.45야. Formation Evaluation에 있는 Rt–Ro–Sw relation을 근거로 Rt 계산해줘.",
        claims=[claim("The source relates Rt to Ro/Sw²", "rt_formula")],
        numbers=[number("Rt", 3.6/0.45**2, "ohm-m", "Ro/Sw^2", {"Ro":3.6,"Sw":0.45}, source_key="rt_formula")])
    add("kb_formula", "en", "reservoir stress", "Use the reservoir text's Po, Pf and Pc balance. If Pf=2100 psi and Pc=125 psi, calculate Po and cite that literal balance.",
        claims=[claim("The literal overburden balance is Po = Pf + Pc", "po_formula")],
        numbers=[number("Po", 2225, "psi", "Pf+Pc", {"Pf":2100,"Pc":125}, source_key="po_formula")])
    add("kb_formula", "ko", "reservoir stress", "Po=2700 psi와 Pf=2450 psi가 주어졌어. 교재의 Po–Pf–Pc 원식을 찾아 Pc만 대수적으로 구해줘.",
        claims=[claim("Original literal source relation is Po = Pf + Pc", "po_formula")],
        numbers=[number("Pc", 250, "psi", "Po-Pf (from Po=Pf+Pc)", {"Po":2700,"Pf":2450}, source_key="po_formula")])
    add("kb_formula", "en", "separator / PVT", "A two-stage separator recorded V1=45 scf, V2=75 scf and L2=4 stb. Find its textbook GOR equation and calculate GOR.",
        claims=[claim("The two-stage separator source gives GOR=(V1+V2)/L2", "gor_formula")],
        numbers=[number("GOR", 30, "scf/stb", "(V1+V2)/L2", {"V1":45,"V2":75,"L2":4}, source_key="gor_formula")])
    add("kb_formula", "ko", "separator / PVT", "2단 분리시험에서 Vres=360 rb, L2=300 stb야. 자료에 인쇄된 Bo 식을 확인하고 Bo를 계산해줘.",
        claims=[claim("The separator source gives Bo=Vres/L2", "bo_formula")],
        numbers=[number("Bo", 1.2, "rb/stb", "Vres/L2", {"Vres":360,"L2":300}, source_key="bo_formula")])

    # Eight compositional tasks requiring every requested output, not a first-result stop.
    add("multi_goal", "ko", "production rates", "A=34, B=55, C=42 stb/d야. 전체 유량과 가장 높은 정의 이름·유량을 함께 알려줘.",
        claims=[claim("Well B is the highest-rate well")],
        numbers=[number("total_rate", 131, "stb/d", "A+B+C", {"A":34,"B":55,"C":42}),
                 number("maximum_rate_B", 55, "stb/d", "max(A,B,C)", {"A":34,"B":55,"C":42})])
    add("multi_goal", "en", "well-rate comparison", "Rates are A=95, B=125, C=110 stb/d. Give both the arithmetic mean and the complete descending well order.",
        claims=[claim("Descending order is B > C > A")],
        numbers=[number("mean_rate", 110, "stb/d", "(A+B+C)/3", {"A":95,"B":125,"C":110})])
    add("multi_goal", "mixed", "production decline", "q_old=640 stb/d, q_new=496 stb/d예요. absolute decline와 old rate 대비 percent decline 둘 다 계산해줘.",
        numbers=[number("absolute_decline", 144, "stb/d", "q_old-q_new", {"q_old":640,"q_new":496}),
                 number("percentage_decline", 22.5, "%", "(q_old-q_new)/q_old*100", {"q_old":640,"q_new":496})],
        visitor_style=True)
    add("multi_goal", "ko", "pressure readings", "세 압력 A=2430, B=2510, C=2470 psi에서 최댓값·최솟값과 평균을 모두 알려줘.",
        numbers=[number("maximum_B", 2510, "psi", "max(A,B,C)", {"A":2430,"B":2510,"C":2470}),
                 number("minimum_A", 2430, "psi", "min(A,B,C)", {"A":2430,"B":2510,"C":2470}),
                 number("mean", 2470, "psi", "(A+B+C)/3", {"A":2430,"B":2510,"C":2470})])
    add("multi_goal", "en", "user-defined well score", "For this exercise define score=2*q+5. Wells A, B, C have q=20, 26, 17 (dimensionless). Compute all three scores and name the highest-scoring well.",
        claims=[claim("Well B has the highest calculated score")],
        numbers=[number("score_A", 45, "dimensionless", "2*q_A+5", {"q_A":20}),
                 number("score_B", 57, "dimensionless", "2*q_B+5", {"q_B":26}),
                 number("score_C", 39, "dimensionless", "2*q_C+5", {"q_C":17})])
    add("multi_goal", "mixed", "porosity sensitivity",
        "phi를 0.12부터 0.24까지 0.04 간격으로 sweep해줘. 내 score 식은 score=40*phi+5야. 모든 case와 최댓값의 phi를 알려줘.",
        claims=[claim("There are four cases at φ=0.12,0.16,0.20,0.24"),
                claim("The maximum score occurs at φ=0.24")],
        numbers=[number("score_phi_0.12", 9.8, "dimensionless", "40*phi+5", {"phi":0.12}),
                 number("score_phi_0.16", 11.4, "dimensionless", "40*phi+5", {"phi":0.16}),
                 number("score_phi_0.20", 13.0, "dimensionless", "40*phi+5", {"phi":0.20}),
                 number("score_phi_0.24", 14.6, "dimensionless", "40*phi+5", {"phi":0.24})],
        visitor_style=True)
    add("multi_goal", "en", "production growth", "Oil rate changed from 340 to 408 stb/d. Report the absolute increase and the percent increase measured from 340.",
        numbers=[number("absolute_increase", 68, "stb/d", "408-340", {"old":340,"new":408}),
                 number("percent_increase", 20, "%", "(408-340)/340*100", {"old":340,"new":408})])
    add("multi_goal", "ko", "well-rate comparison", "A=162, B=190, C=218 stb/d일 때 세 정 평균과 가장 낮은 정의 이름·유량을 둘 다 구해줘.",
        claims=[claim("Well A has the minimum rate")],
        numbers=[number("mean_rate", 190, "stb/d", "(A+B+C)/3", {"A":162,"B":190,"C":218}),
                 number("minimum_rate_A", 162, "stb/d", "min(A,B,C)", {"A":162,"B":190,"C":218})])

    # Four incorrect premises from distinct engineering topics.
    add("false_premise", "ko", "drilling / kick",
        "시추 중 kick은 mud column 압력이 formation pressure보다 높아서 유체가 들어오는 상황 맞죠? 교재로 판정하고 틀리면 고쳐줘.",
        claims=[claim("Explicitly reject the stated pressure direction", "kick"),
                claim("A kick occurs when formation pressure exceeds mud-column pressure", "kick")],
        false_premise={"premise": "mud pressure > formation pressure causes a kick",
                       "correction": "formation pressure > mud-column pressure permits influx",
                       "required_elements": ["explicit rejection", "correct pressure direction", "supporting citation"]},
        visitor_style=True)
    add("false_premise", "en", "reservoir contacts",
        "The free-water level and the oil-water contact are the same depth by definition, yes? Please check the reservoir text and correct me if not.",
        claims=[claim("Explicitly reject equality of FWL and OWC", "fwl"),
                claim("FWL is where capillary pressure is zero and is not coincident with OWC", "fwl", "fwl_zero")],
        false_premise={"premise": "FWL and OWC coincide by definition",
                       "correction": "They need not coincide; FWL has zero capillary pressure",
                       "required_elements": ["explicit rejection", "correct distinction", "supporting citation"]})
    add("false_premise", "mixed", "well testing",
        "early wellbore storage에서는 derivative가 flat plateau이지 pressure와 unit-slope overlap은 아닌 거죠? 내부 type curve 근거로 바로잡아줘.",
        claims=[claim("Explicitly reject flat plateau during early storage", "storage_overlap"),
                claim("Early storage pressure and derivative overlap on unit slope", "storage_overlap"),
                claim("A constant derivative plateau appears at the middle-time onset", "derivative_plateau")],
        false_premise={"premise": "early wellbore storage has a flat derivative plateau",
                       "correction": "early pressure and derivative overlap at unit slope; later plateau is constant",
                       "required_elements": ["explicit rejection", "correct time/regime attribution", "supporting citation"]},
        visitor_style=True)
    add("false_premise", "ko", "gas lift",
        "가스 리프트는 tubing에 가스를 넣어 정수압 수두를 높이기 때문에 생산을 돕는다는 설명이 맞나요? 자료에 따라 교정해줘.",
        claims=[claim("Explicitly reject the raised-hydrostatic-head premise", "gaslift_gradient"),
                claim("Lift gas lowers the tubing hydrostatic head/flowing gradient", "gaslift_gradient")],
        false_premise={"premise": "gas lift raises hydrostatic head",
                       "correction": "gas injection reduces hydrostatic head/pressure gradient",
                       "required_elements": ["explicit rejection", "correct gradient direction", "supporting citation"]})

    # Four absent, named relations. These names are checked against the KB before sealing.
    add("unanswerable", "ko", "unsupported rock index",
        "내부 교재의 Zephyr-Q fracture index 식으로 X=17 psi에서 지수값을 계산해줘. 식이 없으면 수치를 만들지 마.",
        claims=[claim("State that no verified Zephyr-Q relation was found; do not compute a value")],
        unanswerable={"absent_marker": "Zephyr-Q", "reason": "No internal source defines this named relation",
                      "must_not_invent": ["formula", "coefficients", "numeric result"],
                      "minimum_safe_response": "Cannot verify the formula from internal material"})
    add("unanswerable", "en", "unsupported petrophysics index",
        "Can you compute the Lumen-Chi seepage coefficient for porosity 0.18 from our textbooks? If the equation is absent, explain the limit instead of guessing.",
        claims=[claim("State that no verified Lumen-Chi relation was found; do not compute a value")],
        unanswerable={"absent_marker": "Lumen-Chi", "reason": "No internal source defines this named coefficient",
                      "must_not_invent": ["formula", "coefficients", "numeric result"],
                      "minimum_safe_response": "Cannot verify the formula from internal material"})
    add("unanswerable", "mixed", "unsupported PVT correction",
        "Raven-Theta PVT correction을 SG=0.82에 적용해서 값 줘. 단, 교재에 definition이 없으면 없다고 알려줘.",
        claims=[claim("State that no verified Raven-Theta relation was found; do not compute a value")],
        unanswerable={"absent_marker": "Raven-Theta", "reason": "No internal source defines this named correction",
                      "must_not_invent": ["formula", "coefficients", "numeric result"],
                      "minimum_safe_response": "Cannot verify the formula from internal material"},
        visitor_style=True)
    add("unanswerable", "ko", "unsupported drilling index",
        "Delta-Omega drillstring resonance 지표를 교재 식으로 계산해줘. A=4가 입력이고 근거가 없으면 안전하게 멈춰줘.",
        claims=[claim("State that no verified Delta-Omega relation was found; do not compute a value")],
        unanswerable={"absent_marker": "Delta-Omega", "reason": "No internal source defines this named index",
                      "must_not_invent": ["formula", "coefficients", "numeric result"],
                      "minimum_safe_response": "Cannot verify the formula from internal material"})

    # Four intended missing-input interactions; their second turn must use the same run.
    add("resume", "ko", "PVT / API gravity",
        "원유의 API도를 내부 변환식으로 산출하고 싶어. SG를 아직 안 적었으니 필요한 값을 먼저 물어보고 이 작업을 이어줘.",
        follow_up="SG=0.894", claims=[claim("Use the sourced SG-to-API equation", "api_formula")],
        numbers=[number("API", 141.5/0.894-131.5, "°API", "141.5/SG-131.5", {"SG":0.894}, source_key="api_formula")],
        resume={"missing_variable": "SG", "required_clarification": "Ask for oil SG only",
                "same_run_required": True, "retained_source_keys": ["api_formula"]})
    add("resume", "en", "formation factor",
        "Use the sourced formation-factor relationship for F with a=1.1 and m=2.2. I can supply porosity after you ask for it.",
        follow_up="phi=0.25", claims=[claim("Use the sourced F=a/φ^m relation", "generic_f", support="source-layout interpretation")],
        numbers=[number("F", 1.1/0.25**2.2, "dimensionless", "a/phi^m", {"a":1.1,"m":2.2,"phi":0.25}, source_key="generic_f")],
        resume={"missing_variable": "phi", "required_clarification": "Ask for porosity only",
                "same_run_required": True, "retained_source_keys": ["generic_f"]})
    add("resume", "en", "pressure accounting",
        "Calculate P=A-B with A=95 psi. B is deliberately missing; ask me once and finish when I answer.",
        follow_up="B=37 psi", numbers=[number("P", 58, "psi", "A-B", {"A":95,"B":37})],
        resume={"missing_variable": "B", "required_clarification": "Ask for B pressure",
                "same_run_required": True, "retained_source_keys": []})
    add("resume", "en", "user-defined pressure ratio",
        "I define R=P/Q. P=84 psi and Q has not been provided. Request Q and then calculate R.",
        follow_up="Q=12 psi", numbers=[number("R", 7, "dimensionless", "P/Q", {"P":84,"Q":12})],
        resume={"missing_variable": "Q", "required_clarification": "Ask for Q pressure",
                "same_run_required": True, "retained_source_keys": []})

    return {"title": "Petroleum Engineering Agent Final Unseen V4",
            "status": "sealed_after_preflight_before_any_V4_model_execution",
            "frozen_product_sha": "62e5c36f3d66e25addc8a2c37b63af12e2636e78",
            "model": "qwen3:8b", "retrieval_mode": "hybrid", "web": False,
            "tasks": tasks}


def normalize_prompt(value: str) -> str:
    # Replacing numbers also catches same-wording/different-number copies.
    value = re.sub(r"\d+(?:\.\d+)?", "#", value.casefold())
    return "".join(character for character in value if character.isalnum() or character == "#")


def prior_prompt_texts() -> list[tuple[str, str]]:
    root = HERE.parents[1]
    paths = [path for path in root.rglob("*.json") if HERE not in path.parents
             and any(marker in path.name.casefold() for marker in
                     ("benchmark", "heldout", "catalog", "real_kb_dev", "conference_stress", "smoke"))]
    contents: list[tuple[str, object]] = []
    for path in paths:
        try:
            contents.append((str(path.relative_to(root)), json.loads(path.read_text(encoding="utf-8"))))
        except (UnicodeError, json.JSONDecodeError):
            continue
    for ref, path in (
        ("origin/eval/v21-2-final-unseen-v3", "evaluation/v21_2_final_unseen_v3/benchmark.json"),
        ("origin/eval/v21-2-final-unseen-v2", "evaluation/v21_2_final_unseen_v2/benchmark.json"),
        ("origin/feature/conference-demo-v23", "evaluation/v23_demo/real_kb_dev_v23b.json"),
        ("origin/feature/conference-demo-v23", "evaluation/v23_demo/conference_stress_v23b.json"),
    ):
        result = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=HERE.parents[1],
                                capture_output=True, text=True, encoding="utf-8", check=True)
        contents.append((f"{ref}:{path}", json.loads(result.stdout)))

    prompts: list[tuple[str, str]] = []
    def visit(value: object, origin: str) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, origin)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key.casefold() in {"message", "prompt", "question", "query", "user_message",
                                      "initial_message", "initial_prompt"} and isinstance(item, str):
                    if 15 <= len(item) <= 1200:
                        prompts.append((origin, item))
                elif isinstance(item, (dict, list)):
                    visit(item, origin)
    for origin, content in contents:
        visit(content, origin)
    return prompts


def audit_catalog(catalog: dict, sources: dict[str, dict]) -> dict:
    tasks = catalog["tasks"]
    if len(tasks) != 60:
        raise AssertionError(f"Expected exactly 60 tasks, got {len(tasks)}")
    categories = Counter(task["category"] for task in tasks)
    expected_categories = {"knowledge":12, "direct":8, "user_formula":8, "kb_formula":12,
                           "multi_goal":8, "false_premise":4, "unanswerable":4, "resume":4}
    if dict(categories) != expected_categories:
        raise AssertionError(f"Category distribution: {dict(categories)}")
    languages = Counter(task["language"] for task in tasks)
    if dict(languages) != {"ko":24, "en":24, "mixed":12}:
        raise AssertionError(f"Language distribution: {dict(languages)}")
    if sum(task["visitor_style"] for task in tasks) < 12:
        raise AssertionError("Need at least twelve visitor-style variations")
    if len({task["id"] for task in tasks}) != 60:
        raise AssertionError("Task ID collision")
    for task in tasks:
        gold = task["gold"]
        if not gold["required_goals"]:
            raise AssertionError(f"No required goals: {task['id']}")
        if task["category"] in {"knowledge", "kb_formula", "false_premise"} and not gold["source_spans"]:
            raise AssertionError(f"Missing KB support: {task['id']}")
        if task["category"] == "resume" and (not task["follow_up"] or not gold.get("resume")):
            raise AssertionError(f"Incomplete two-turn gold: {task['id']}")
        for source in gold["source_spans"]:
            if source["needle"].casefold() not in source["literal_span"].casefold():
                raise AssertionError(f"Nonliteral source span: {task['id']}")
        for numeric in gold["numeric_outputs"]:
            if numeric["requires_kb_formula"] and not numeric["formula_source_keys"]:
                raise AssertionError(f"Unsourced KB formula: {task['id']}")
            if numeric["tolerance"] <= 0 or numeric["unit"] == "":
                raise AssertionError(f"Invalid numerical gold: {task['id']}")

    # Audit invented relation labels against the entire read-only KB, not just retrieval.
    import chromadb
    sqlite = Path(os.environ["DATA_DIR"]).resolve() / "vector_db" / "chroma.sqlite3"
    collection = chromadb.PersistentClient(path=str(sqlite.parent)).get_collection("petroleum_knowledge")
    passages = collection.get(include=["documents"])["documents"]
    for task in tasks:
        absent = (task["gold"].get("unanswerable") or {}).get("absent_marker")
        if absent and any(absent.casefold() in text.casefold() for text in passages):
            raise AssertionError(f"Supposedly absent relation is present in KB: {absent}")

    prior = prior_prompt_texts()
    prior_normalized = {normalize_prompt(prompt): origin for origin, prompt in prior}
    overlaps = [(task["id"], prior_normalized[normalize_prompt(task["prompt"])])
                for task in tasks if normalize_prompt(task["prompt"]) in prior_normalized]
    if overlaps:
        raise AssertionError(f"Normalized prior-prompt overlaps: {overlaps}")
    if len({normalize_prompt(task["prompt"]) for task in tasks}) != 60:
        raise AssertionError("Within-V4 normalized prompt overlap")
    # Shortlist high lexical similarity for a human pre-seal check, without treating
    # related petroleum topics as exact duplicate prompts.
    older_catalogs = [(origin, prompt) for origin, prompt in prior
                      if "results" not in origin and "review" not in origin]
    near = []
    for task in tasks:
        normalized = normalize_prompt(task["prompt"])
        match = max(((SequenceMatcher(None, normalized, normalize_prompt(prompt)).ratio(), origin)
                     for origin, prompt in older_catalogs), default=(0.0, ""))
        if match[0] >= 0.83:
            near.append({"task_id": task["id"], "similarity": round(match[0], 3),
                         "prior_file": match[1]})
    source_pages = sorted({(item["document"], item["page"]) for item in sources.values()})
    return {"task_count": len(tasks), "categories": dict(categories), "languages": dict(languages),
            "visitor_style_count": sum(task["visitor_style"] for task in tasks),
            "prior_prompt_strings_checked": len(prior), "normalized_duplicate_count": 0,
            "possible_near_prompts": near, "source_key_count": len(sources),
            "source_document_count": len({name for name, _ in source_pages}),
            "source_pages": [{"document": name, "page": page} for name, page in source_pages],
            "absent_relation_names_checked": [task["gold"]["unanswerable"]["absent_marker"]
                                             for task in tasks if task["category"] == "unanswerable"],
            "chroma_chunks_after_audit": collection.count()}


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]
    if not (HERE / "PRECHECK.md").is_file():
        raise RuntimeError("Write PRECHECK.md before generating V4")
    if CATALOG.exists() or HASH.exists():
        raise RuntimeError("V4 catalog already sealed; refusing overwrite")
    if os.environ.get("RETRIEVAL_MODE") != "hybrid" or os.environ.get("WEB_FETCH_ENABLED") != "0":
        raise RuntimeError("V4 requires hybrid retrieval and WEB_FETCH_ENABLED=0")
    frozen = "62e5c36f3d66e25addc8a2c37b63af12e2636e78"
    product_diff = subprocess.run(["git", "diff", "--quiet", frozen, "HEAD", "--", "backend", "frontend"],
                                  cwd=HERE.parents[1], check=False)
    if product_diff.returncode != 0:
        raise RuntimeError("Product tree differs from frozen SHA")
    sources = read_sources()
    catalog = make_catalog(sources)
    audit = audit_catalog(catalog, sources)
    print(json.dumps(audit, ensure_ascii=False, indent=2), flush=True)
    if dry_run:
        return
    payload = (json.dumps(catalog, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    (HERE / "v4_catalog_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
    CATALOG.write_bytes(payload)
    HASH.write_text(f"{digest}  v4_catalog.json\n", encoding="ascii")
    print(f"SEALED V4 CATALOG SHA256 {digest}")


if __name__ == "__main__":
    main()
