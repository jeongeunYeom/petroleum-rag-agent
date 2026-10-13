"""Author V3 only from the seeded, unused source-passage pool.

No evaluated-model output is read by this script. Run once before freeze.
"""

from __future__ import annotations

import ast
import json
import operator
from pathlib import Path

import fitz


HERE = Path(__file__).resolve().parent
POOL = json.loads((HERE / "source_pool.json").read_text(encoding="utf-8"))["candidates"]
RAW_PDF_DIR = Path(r"D:\petroleum-rag-agent\data\raw")
OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


def calculate(expression: str) -> float:
    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](walk(node.left), walk(node.right))
        raise ValueError(f"unsafe gold expression: {expression}")

    return walk(ast.parse(expression, mode="eval").body)


def numeric(name: str, expression: str, unit: str, tolerance: float) -> dict:
    return {
        "name": name,
        "expected_value": calculate(expression),
        "expected_unit": unit,
        "tolerance": tolerance,
        "deterministic_expression": expression,
    }


def source(doc_hint: str, page: int, anchor: str, length: int = 1000) -> dict:
    matches = [x for x in POOL if doc_hint in x["document"] and x["page"] == page]
    if len(matches) != 1:
        raise ValueError(f"source not uniquely sampled: {doc_hint} p{page}")
    candidate = matches[0]
    pdf_files = [p for p in RAW_PDF_DIR.glob("*.pdf") if p.name.endswith(candidate["document"])]
    if len(pdf_files) != 1:
        raise ValueError(f"raw PDF not unique: {candidate['document']}")
    with fitz.open(pdf_files[0]) as pdf:
        if page < 1 or page > len(pdf):
            raise ValueError(f"PDF page out of range: {candidate['document']} p{page}")
        passage = pdf[page - 1].get_text()
    start = passage.find(anchor)
    if start < 0:
        raise ValueError(f"anchor absent from raw PDF: {doc_hint} p{page}: {anchor}")
    return {
        "document": candidate["document"],
        "page": page,
        "exact_span": passage[start : start + length],
        "sampled_candidate_order": candidate["candidate_order"],
    }


def formula(ref: dict, literal: str) -> dict:
    if literal not in ref["exact_span"]:
        raise ValueError(f"formula absent from exact span: {literal}")
    return {
        "required": True,
        "document": ref["document"],
        "page": ref["page"],
        "exact_formula_span": literal,
    }


tasks: list[dict] = []


def add(
    category: str,
    domain: str,
    language: str,
    question: str,
    goals: list[str],
    claims: list[str],
    *,
    sources: list[dict] | None = None,
    numbers: list[dict] | None = None,
    formula_source: dict | None = None,
    missing: list[str] | None = None,
    forbidden: list[str] | None = None,
    multi_goal: bool = False,
    answerable: bool = True,
) -> None:
    tasks.append(
        {
            "task_id": f"V212V3-{len(tasks) + 1:03d}",
            "category": category,
            "domain": domain,
            "question_language": language,
            "question": question,
            "answerable": answerable,
            "multi_goal": multi_goal,
            "required_goals": goals,
            "required_claims": claims,
            "forbidden_claims": forbidden or [],
            "gold_sources": sources or [],
            "numeric_targets": numbers or [],
            "formula_source": formula_source or {"required": False},
            "missing_inputs": missing or [],
            "citation_required_for_agent": bool(sources),
        }
    )


# Knowledge QA: every source is a selected unused English PDF passage.
s = source("Drilling_Engineering", 329, "The main cause for poor isolation", 1620)
add("knowledge_qa", "drilling_engineering", "ko", "시멘트 작업 뒤 층간 차단이 나쁜 주된 이유를 설명하고, 이를 줄일 수 있는 작업 두 가지를 내부 자료에 근거해 제시해줘.", ["Explain the dominant isolation failure mechanism", "Give two supported mitigations"], ["Mud channels persist when annular mud is not displaced, especially with poor casing centralization", "Centralizers and casing movement or mud conditioning improve displacement"], sources=[s], multi_goal=True)
s = source("Formation_Evaluation", 54, "Potassium 40 decays", 1400)
add("knowledge_qa", "petrophysics", "ko", "자연 감마선 스펙트럼에서 K-40과 U/Th 계열의 방출 양상이 왜 다른지, 이를 원소 추정에 어떻게 활용하는지 설명해줘.", ["Explain spectral distinction and interpretation"], ["K-40 emits a 1.46 MeV gamma ray directly", "U-238 and Th-232 daughter chains emit multiple energies, and spectral populations can infer parent abundance under secular equilibrium"], sources=[s])
s = source("Reservoir_Simulation", 87, "Defining the objectives is", 1370)
add("knowledge_qa", "reservoir_simulation", "en", "In a reservoir simulation study, why should the objective be framed as a decision rather than simply asking whether an intervention produces more oil?", ["Explain decision-oriented simulation objective"], ["An intervention may yield more oil yet be uneconomic; the decision should reflect economics or an explicit strategic purpose"], sources=[s])
s = source("Well_Test", 111, "The objectives of testing exploration", 2400)
add("knowledge_qa", "well_testing", "en", "During an appraisal drillstem test, what is the purpose of the initial short flow and what does the first shut-in establish? Explain both using the internal material.", ["Explain initial short flow", "Explain first shut-in"], ["The initial short flow relieves supercharging and establishes reservoir communication with negligible depletion", "The first buildup establishes initial reservoir pressure after stabilization"], sources=[s], multi_goal=True)
s = source("Reservoir Engineering", 637, "The MB equation is a tank model", 1800)
add("knowledge_qa", "reservoir_engineering", "ko", "물질수지식을 저류층에 적용할 때 압력과 생산 속도에 관한 핵심 가정·한계는 무엇이야?", ["State material-balance pressure/rate limits"], ["The tank model uses a representative average pressure rather than spatial pressure gradients", "Material balance has no time term and does not itself capture rate sensitivity"], sources=[s])
s = source("Production_Technology_I", 266, "The mixing of produced fluids", 2470)
add("knowledge_qa", "production_technology", "ko", "다층 동시 생산에서 층별 유체를 섞으면 어떤 운영상 제약이 생기며, 분리 생산은 제어 측면에서 무엇을 가능하게 하나?", ["Explain commingling limitation and segregated-control benefit"], ["Commingling can mix corrosive or sandy fluids and makes individual-zone control difficult", "Segregated depletion allows independent zone production control and monitoring"], sources=[s])
s = source("Production_Technology_II", 362, "TSO fracturing is now", 1740)
add("knowledge_qa", "production_technology", "en", "Why can tip-screenout fracturing help both sand control and near-wellbore damage bypass?", ["Explain two TSO applications"], ["A TSO fracture can reduce flow velocity for sand control", "A highly conductive fracture can bypass near-wellbore damage without requiring the damage type to be identified"], sources=[s])
s = source("Reservoir Engineering", 506, "The example above illustrates", 620)
add("knowledge_qa", "reservoir_engineering", "en", "What is gained by combining compositional phase-volume predictions with a black-oil description instead of relying only on empirical correlations?", ["Explain compositional/black-oil integration"], ["Compositional-derived phase volumes/properties can overcome limitations of a simple two-component black-oil model and avoid inappropriate empirical correlations"], sources=[s])

# Multi-claim reasoning: two to four atomic claims, each within its literal span.
s = source("Drilling_Engineering", 363, "Water based muds are relatively inexpensive", 2580)
add("multi_claim_reasoning", "drilling_engineering", "en", "Compare the cost advantage of water-based mud with its main shale-related risk, and distinguish the roles of active clay solids and inert barite.", ["Compare cost and shale risk", "Distinguish active and inert solids"], ["Water-based mud is relatively inexpensive because water is readily available", "Water hydration of shale clays can destabilize the borehole", "Clays are active solids while barite is inert"], sources=[s], multi_goal=True)
s = source("Formation_Evaluation", 43, "When using freshwater mud", 2100)
add("multi_claim_reasoning", "petrophysics", "ko", "담수 이수와 염수 이수에서 수층의 천부·심부 비저항 경향을 비교하고, 왜 비저항만으로 공극률을 확정하면 안 되는지 설명해줘.", ["Compare resistivity profiles", "Explain porosity inference limitation"], ["In freshwater mud, flushed-zone resistivity is higher than formation water and readings decline toward undisturbed water zone", "Salt-mud flushed zone is lower/similar resistivity to high-resistivity formation water", "Porosity requires acoustic, density, or neutron logs with lithology/fluid/environmental effects considered"], sources=[s], multi_goal=True)
s = source("Reservoir_Simulation", 264, "The effective permeability of simple", 2160)
add("multi_claim_reasoning", "reservoir_simulation", "ko", "거친 격자에서 투과도 upscaling이 언제 부정확해지고, 단상 upscaling을 2상 유동에 그대로 쓰면 어떤 문제가 생기나?", ["Explain two upscaling limitations"], ["Coarse-cell size near correlation length with large variance makes effective permeability upscaling inaccurate", "Single-phase upscaling can misrepresent two-phase flow, especially with large scale-up factor or permeability variance"], sources=[s])
s = source("Well_Test", 358, "In essence a WFT tool", 2100)
add("multi_claim_reasoning", "well_testing", "ko", "WFT가 측정하는 sand-face pressure를 원래 지층압과 동일시해도 될까? 저투과성 암석에서 supercharging과 mudcake 저항의 영향을 구분해 설명해줘.", ["Distinguish WFT measurement from undisturbed pressure"], ["WFT measures sand-face pressure, which can exceed undisturbed formation pressure under supercharging", "Supercharging is appreciable mainly in low-permeability formations", "Higher filter-cake resistance reduces filtrate loss and brings sand-face pressure closer to formation pressure"], sources=[s])
s = source("Reservoir Engineering", 382, "Once the boundaries are detected", 2110)
add("multi_claim_reasoning", "reservoir_engineering", "en", "If a producing well is off-center in a bounded reservoir, why can boundary effects arrive unevenly, and how can an image well represent the nearest sealing boundary?", ["Explain off-center boundary timing and image-well method"], ["An off-center well reaches some boundaries before others, so flow regimes coexist temporarily", "An imaginary well at twice the real-well-to-boundary distance with matching rate history represents the barrier through superposition"], sources=[s])
s = source("Production_Technology_I", 304, "The danger of stray", 2120)
add("multi_claim_reasoning", "production_technology", "en", "For wireline perforating, explain the separate risks from stray current and elevated temperature, and why gun length can require multiple trips.", ["Explain perforating operational constraints"], ["Stray current can detonate an armed gun until it reaches a safe depth or is checked after retrieval", "Explosives can detonate at high temperature and stability depends on exposure duration", "Lubricator length or cable tensile capacity limits gun length, so a longer interval can require multiple trips"], sources=[s])

# Six calculations requiring no governing KB formula.
add("direct_calculation", "drilling_engineering", "en", "Three mud batches are 80 bbl at 10.1 ppg, 120 bbl at 10.7 ppg, and 100 bbl at 11.2 ppg. What is their volume-weighted average density?", ["Calculate weighted mean density"], ["Volume-weighted density is about 10.71 ppg"], numbers=[numeric("weighted_density", "(80*10.1+120*10.7+100*11.2)/(80+120+100)", "ppg", 0.02)])
add("direct_calculation", "production_technology", "en", "A well's oil rate changes from 820 to 697 stb/d. What is the percentage decline relative to the initial rate?", ["Calculate rate decline"], ["The decline is 15%"], numbers=[numeric("decline", "(820-697)/820*100", "%", 0.2)])
add("direct_calculation", "well_testing", "en", "A test begins at 3650 psi, falls to 3265 psi while flowing, then recovers to 3590 psi after shut-in. Compute the flowing drawdown and the shut-in recovery from flowing pressure separately.", ["Calculate drawdown", "Calculate shut-in recovery"], ["Drawdown is 385 psi", "Recovery is 325 psi"], numbers=[numeric("drawdown", "3650-3265", "psi", 1), numeric("recovery", "3590-3265", "psi", 1)], multi_goal=True)
add("direct_calculation", "reservoir_engineering", "en", "A separator collects 960 bbl of water in 18 hours at a steady rate. What is the equivalent 24-hour water rate in bbl/day?", ["Convert time-normalized water rate"], ["Equivalent rate is 1280 bbl/day"], numbers=[numeric("daily_rate", "960/18*24", "bbl/day", 2)])
add("direct_calculation", "production_technology", "en", "Gas production is 1.35 million scf/day while oil production is 4500 stb/day. Compute the produced gas-to-oil ratio in scf/stb.", ["Calculate gas-to-oil ratio"], ["Gas-to-oil ratio is 300 scf/stb"], numbers=[numeric("gor", "1350000/4500", "scf/stb", 1)])
add("direct_calculation", "reservoir_simulation", "en", "Three injectors deliver 1900, 2250, and 1650 m3/day. What is their combined daily injection rate?", ["Sum injector rates"], ["Combined rate is 5800 m3/day"], numbers=[numeric("total_injection", "1900+2250+1650", "m3/day", 1)])

# Four calculations whose governing equations are explicitly user-provided.
add("user_formula", "petrophysics", "en", "Use the supplied relation phi_eff = phi_total * (1 - Vsh). With phi_total = 0.29 and Vsh = 0.18, calculate effective porosity as a fraction.", ["Calculate effective porosity from supplied formula"], ["Effective porosity is 0.2378"], numbers=[numeric("phi_eff", "0.29*(1-0.18)", "fraction", 0.002)])
add("user_formula", "drilling_engineering", "en", "For this hypothetical pump system only, use P_extra = C*q^2 with C = 0.012 psi/(gpm)^2 and q = 340 gpm. Calculate P_extra in psi.", ["Calculate supplied pump relation"], ["P_extra is 1387.2 psi"], numbers=[numeric("P_extra", "0.012*340**2", "psi", 2)])
add("user_formula", "reservoir_simulation", "en", "Use only this supplied score model: R(s) = 120 + 40*s - 10*s^2. Evaluate s = 0, 0.5, and 1.0, then report the best s and its score.", ["Evaluate supplied sweep and identify best"], ["Scores are 120, 137.5, and 150 at s=0,0.5,1", "Best s is 1.0 with score 150"], numbers=[numeric("score_s0", "120+40*0-10*0**2", "score", 0.1), numeric("score_s05", "120+40*0.5-10*0.5**2", "score", 0.1), numeric("score_s1", "120+40*1-10*1**2", "score", 0.1), numeric("best_s", "1", "dimensionless", 0.01)])
add("user_formula", "production_technology", "en", "For a trial separator, define efficiency eta = 100*q_actual/q_nominal. If actual throughput is 47.5 m3/h and nominal throughput is 62.0 m3/h, calculate eta in percent.", ["Calculate supplied efficiency"], ["Efficiency is about 76.61%"], numbers=[numeric("eta", "100*47.5/62.0", "%", 0.2)])

# Six independent KB-formula pages, checked against the raw PDFs.
s = source("Drilling_Engineering", 281, "Fbuoy = Pe (Ao - Ai)", 220)
add("kb_formula", "drilling_engineering", "en", "For an open-ended casing, use the internal textbook relation for buoyancy force. With external pressure Pe = 2400 psi, outside area Ao = 18.0 in2, and inside area Ai = 12.5 in2, calculate Fbuoy in lbf and cite the actual equation source.", ["Find the literal open-ended casing equation and calculate force"], ["The source formula is Fbuoy = Pe(Ao - Ai)", "Fbuoy is 13200 lbf"], sources=[s], numbers=[numeric("Fbuoy", "2400*(18.0-12.5)", "lbf", 20)], formula_source=formula(s, "Fbuoy = Pe (Ao - Ai)"))
s = source("Production_Technology_II", 330, "ISIP = FPP -", 410)
add("kb_formula", "production_technology", "ko", "내부 교재의 minifrac 압력 관계식으로 ISIP를 계산해줘. FPP=5700 psi, 천공 압력손실=180 psi, 균열 마찰손실=125 psi야. 실제 식의 출처도 제시해줘.", ["Find literal ISIP equation and calculate"], ["ISIP subtracts perforation and fracture-friction drops from FPP", "ISIP is 5395 psi"], sources=[s], numbers=[numeric("ISIP", "5700-180-125", "psi", 5)], formula_source=formula(s, "ISIP = FPP - ∆Pperforations - ∆Pfracture friction"))
s = source("Reservoir Engineering", 749, "If we express the volume of the pores", 570)
add("kb_formula", "reservoir_engineering", "ko", "내부 교재에서 이동 가능한 원유 체적 식을 찾아 계산해줘. PV=180만 bbl, 잔류유 포화도 Sor=0.23, 불감수 포화도 Swc=0.19야. Sor가 커지면 계산 체적이 어떻게 변하는지도 설명해줘.", ["Find literal MOV equation and calculate", "Interpret Sor effect"], ["MOV=(1-Sor-Swc)PV and equals 1,044,000 bbl", "Increasing Sor decreases MOV at fixed PV and Swc"], sources=[s], numbers=[numeric("MOV", "(1-0.23-0.19)*1800000", "bbl", 1000)], formula_source=formula(s, "MOV = (1- Sor - Swc) PV"), multi_goal=True)
s = source("Formation_Evaluation", 112, "Bulk density ρb =", 165)
add("kb_formula", "petrophysics", "ko", "내부 formation evaluation 자료에 있는 electron-density 보정식을 사용해 ρe=2.42 g/cm3일 때 bulk density ρb를 계산하고 식이 적힌 페이지를 인용해줘.", ["Find literal bulk-density equation and calculate"], ["The source formula is rho_b=1.0704 rho_e - 0.1883", "Bulk density is about 2.4021 g/cm3"], sources=[s], numbers=[numeric("rho_b", "1.0704*2.42-0.1883", "g/cm3", 0.01)], formula_source=formula(s, "Bulk density ρb = 1.0704 ρe - 0.1883"))
s = source("Reservoir_Simulation", 359, "for spherical particles, Ss=6/Dp", 115)
add("kb_formula", "reservoir_simulation", "en", "Find the internal textbook's specific-surface relation for spherical grains. For grain diameter Dp = 0.0002 m, calculate Ss in 1/m and cite the literal equation span.", ["Find literal spherical-grain equation and calculate"], ["Ss=6/Dp for spherical particles", "Ss is 30000 1/m"], sources=[s], numbers=[numeric("Ss", "6/0.0002", "1/m", 100)], formula_source=formula(s, "Ss=6/Dp"))
s = source("Production_Technology_I", 7, "PR  = ∆PSYSTEM + PSEP", 220)
add("kb_formula", "production_technology", "en", "According to the internal production-system pressure-balance relation, what reservoir pressure PR is needed if total system pressure loss is 1740 psi and separator pressure is 160 psi? Cite the formula span.", ["Find literal pressure-balance equation and calculate"], ["PR equals system pressure loss plus separator pressure", "PR is 1900 psi"], sources=[s], numbers=[numeric("PR", "1740+160", "psi", 5)], formula_source=formula(s, "PR  = ∆PSYSTEM + PSEP"))

# False premises in three different domains.
s = source("Drilling_Engineering", 162, "The magnitude of the pressure in the pores", 1320)
add("false_premise", "drilling_engineering", "ko", "시추 중 시추공 압력을 지층 파쇄압보다 높게 유지해야 유체 손실을 막는다는 설명이 맞지? 내부 자료를 기준으로 바로잡아줘.", ["Explicitly reject and correct premise with support"], ["Borehole pressure should not exceed fracture pressure; exceeding it risks fracture and drilling-fluid losses", "Borehole pressure should not fall below formation pore pressure"], sources=[s], forbidden=["Borehole pressure should be maintained above fracture pressure"])
s = source("Formation_Evaluation", 87, "During the drilling of the well", 640)
add("false_premise", "petrophysics", "en", "Once a mudcake develops, it increases the rate of further mud-filtrate invasion into a permeable formation, correct? Use the internal source to assess this premise.", ["Explicitly reject and correct premise with support"], ["Low-permeability mudcake considerably reduces further filtrate invasion"], sources=[s], forbidden=["Mudcake increases further invasion"])
s = source("Reservoir_Simulation", 310, "We can now use this discussion", 1000)
add("false_premise", "reservoir_simulation", "en", "A flat plateau on a capillary-pressure curve means the rock has a very broad pore-size distribution, right? Correct me if the internal material says otherwise.", ["Explicitly reject and correct premise with support"], ["A flat plateau suggests relatively homogeneous pore size; steeper curves indicate greater pore-size variance"], sources=[s], forbidden=["Flat capillary plateau proves broad pore-size variance"])

# Genuinely underdetermined: a specific missing input must be named, not guessed.
s = source("Drilling_Engineering", 281, "Fbuoy = Pe (Ao - Ai)", 220)
add("unanswerable", "drilling_engineering", "en", "Using the internal open-ended casing relation, calculate buoyancy force for Pe=2100 psi and Ao=19.0 in2. I have not measured the inside area.", ["Identify missing inside area and request it without a numeric force"], ["Ai is required by Fbuoy=Pe(Ao-Ai); no unique force can be computed without Ai"], sources=[s], missing=["inside area Ai in in2"], forbidden=["An invented inside area or numeric buoyancy force"], answerable=False)
s = source("Reservoir Engineering", 749, "If we express the volume of the pores", 570)
add("unanswerable", "reservoir_engineering", "ko", "내부 교재 식으로 movable oil volume을 구해줘. PV는 92만 bbl이고 Swc는 0.21이지만 Sor 측정값은 아직 없어.", ["Identify missing residual-oil saturation without fabricating MOV"], ["Sor is required by MOV=(1-Sor-Swc)PV and is missing"], sources=[s], missing=["residual-oil saturation Sor"], forbidden=["Invented Sor or numeric movable-oil volume"], answerable=False)
s = source("Formation_Evaluation", 112, "Bulk density ρb =", 165)
add("unanswerable", "petrophysics", "en", "Use the internal electron-density correction to determine bulk density. I can provide the calibration relation but have no measured electron density for this sample.", ["Identify missing electron-density measurement without numeric output"], ["The relation requires rho_e; without a measured rho_e there is no unique rho_b"], sources=[s], missing=["measured electron density rho_e"], forbidden=["Invented electron density or numeric bulk density"], answerable=False)


resume = [
    {
        "probe_id": "V212V3-R01",
        "domain": "drilling_engineering",
        "turn1": "Use the internal open-ended casing buoyancy relation with Pe=1950 psi and Ao=17.5 in2. Calculate Fbuoy, but I do not yet have Ai.",
        "turn2": "Ai is 11.0 in2.",
        "missing_input": "Ai",
        "gold_sources": [source("Drilling_Engineering", 281, "Fbuoy = Pe (Ao - Ai)", 220)],
        "numeric_target": numeric("Fbuoy", "1950*(17.5-11.0)", "lbf", 20),
    },
    {
        "probe_id": "V212V3-R02",
        "domain": "production_technology",
        "turn1": "Find the minifrac ISIP relation in the internal notes. FPP is 6200 psi and perforation pressure loss is 210 psi, but the fracture-friction loss has not been measured yet. Calculate ISIP when possible.",
        "turn2": "The fracture-friction pressure loss is 135 psi.",
        "missing_input": "fracture-friction pressure loss",
        "gold_sources": [source("Production_Technology_II", 330, "ISIP = FPP -", 410)],
        "numeric_target": numeric("ISIP", "6200-210-135", "psi", 5),
    },
    {
        "probe_id": "V212V3-R03",
        "domain": "reservoir_engineering",
        "turn1": "Using the internal movable-oil-volume relation, calculate MOV for PV=1.1 million bbl and Swc=0.16. I still need to provide Sor.",
        "turn2": "Sor is 0.28.",
        "missing_input": "Sor",
        "gold_sources": [source("Reservoir Engineering", 749, "If we express the volume of the pores", 570)],
        "numeric_target": numeric("MOV", "(1-0.28-0.16)*1100000", "bbl", 1000),
    },
    {
        "probe_id": "V212V3-R04",
        "domain": "petrophysics",
        "turn1": "Use the bulk-density/electron-density relation from the internal formation-evaluation notes, but I do not have electron density yet. What is needed to calculate rho_b?",
        "turn2": "The measured electron density rho_e is 2.31 g/cm3.",
        "missing_input": "rho_e",
        "gold_sources": [source("Formation_Evaluation", 112, "Bulk density ρb =", 165)],
        "numeric_target": numeric("rho_b", "1.0704*2.31-0.1883", "g/cm3", 0.01),
    },
]


def main() -> None:
    payload = {"primary_tasks": tasks, "resume_probes": resume}
    (HERE / "benchmark.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print({"primary_tasks": len(tasks), "resume_probes": len(resume)})


if __name__ == "__main__":
    main()
