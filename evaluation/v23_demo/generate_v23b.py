"""Generate fresh, development-only V23B probes; never a sealed benchmark."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> None:
    cases: list[dict] = []
    resumes: list[dict] = []

    def add(category: str, message: str, *, resume: bool = False, **expected: object) -> None:
        bucket = resumes if resume else cases
        initials = {"knowledge": "K", "direct": "D", "user_formula": "U", "kb_formula": "F",
                    "multi_goal": "M", "false_premise": "P", "unanswerable": "N", "resume": "R"}
        index = 1 + sum(row["category"] == category for row in bucket)
        bucket.append({"id": f"VB-{initials[category]}{index:02d}", "category": category,
                       "message": message, **expected})

    knowledge = [
        ("In the internal drilling notes, explain how nonmagnetic collars protect directional survey readings.", ["magnetic", "survey"]),
        ("교재에서 물 포화도가 공극 체적 중 무엇을 나타내는지 밝혀줘.", ["saturation", "pore"]),
        ("Compare the carbonate and sand formation-factor expressions in the formation-evaluation material.", ["carbonate", "sand"]),
        ("Well-test 자료에서 압력만 맞추는 type-curve 방법에 derivative를 더한 이유를 찾아줘.", ["derivative", "type curve"]),
        ("What can an appraisal well establish about the oil-water contact after discovery? Cite the source.", ["appraisal", "contact"]),
        ("Explain how fractional flow informs a waterflood interpretation, using the internal text.", ["fractional flow", "water"]),
        ("Oil-water capillary pressure: which two phase pressures does the cited definition relate?", ["capillary", "pressure"]),
        ("Why must a magnetic directional survey avoid ordinary steel near its sensor? Internal material only.", ["magnetic", "survey"]),
        ("Explain the textbook's reason for using simulation while offshore development choices narrow.", ["simulation", "offshore"]),
        ("Formation Evaluation 근거로 porosity와 formation factor 사이의 관계를 짧게 설명해줘.", ["porosity", "factor"]),
    ]
    for question, terms in knowledge:
        add("knowledge", question, support_terms=terms)

    direct = [
        ("Well A=137 stb/d, B=83 stb/d, C=59 stb/d. Report their combined rate.", [279]),
        ("Production fell from 830 stb/d to 664 stb/d. What percentage decrease occurred?", [20]),
        ("Gas=2840 scf, oil=71 stb. Give the gas-to-oil volume ratio.", [40]),
        ("P_A=47 psi, P_B=18 psi. Calculate P_A-P_B.", [29]),
        ("A=117 stb/d, B=132 stb/d, C=93 stb/d. 이 유량의 평균은?", [114]),
        ("Readings A=2940 psi, B=2710 psi, C=3020 psi. Give both extrema.", [3020, 2710]),
        ("line1=56 stb/d, line2=69 stb/d, line3=82 stb/d. 합계를 구해줘.", [207]),
        ("A pressure rose from 1600 to 1840 psi. What percent increase is that?", [15]),
        ("Produced gas=2128 scf and oil=56 stb. Calculate gas/oil ratio.", [38]),
        ("A=27 psi, B=54 psi, C=36 psi. Give the mean and descending order.", [39]),
    ]
    for question, values in direct:
        add("direct", question, numeric=values)

    user_formulas = [
        ("A=38 psi, B=9 psi. Given my expression Delta=A-B, report Delta.", [29]),
        ("x=6 dimensionless, y=8 dimensionless. My relation Q=x*y+3; compute Q.", [51]),
        ("a=7 m, b=5 m. Use my expression L=2*(a+b) and report L.", [24]),
        ("q=14 stb/d and t=6 day. 사용자 식 V=q*t로 계산해줘.", [84]),
        ("P=405 psi, F=81 psi. The given formula is R=P/F; evaluate R.", [5]),
        ("x=3, y=4. From my equation Z=(x+y)**2, find Z.", [49]),
        ("rho=27 kg/m3, V=8 m3. My equation mass=rho*V; calculate mass.", [216]),
        ("s=0.25 dimensionless. Apply R=100+24*s-8*s^2 as supplied and evaluate R.", [105.5]),
    ]
    for question, values in user_formulas:
        add("user_formula", question, numeric=values)

    def formula(message: str, value: float, target: str, doc: str, page: int, marker: str) -> None:
        add("kb_formula", message, numeric=[round(value, 2)], target=target,
            source_document=doc, source_page=page, formula_marker=marker)

    reservoir, formation = "Reservoir Engineering", "Formation_Evaluation"
    formula("Apply the sourced Reservoir Engineering SG-to-API relation to SG=0.876.",
            141.5/.876-131.5, "API", reservoir, 90, "API = (141.5 / SG) -131.5")
    formula("내부 교재의 SG-API 식으로 SG=0.912 원유의 API도를 구해줘.",
            141.5/.912-131.5, "API", reservoir, 90, "API = (141.5 / SG) -131.5")
    formula("Find the textbook formation-factor relation and evaluate F at phi=0.24, a=1, m=2.",
            1/.24**2, "F", formation, 164, "F = a/fm")
    formula("Formation factor F를 내부 식으로 산출해줘. phi=0.30, a=1, m=2.",
            1/.30**2, "F", formation, 164, "F = a/fm")
    formula("For carbonate rock, use its literal formation-factor equation at phi=0.205 to find F.",
            1/.205**2, "F", formation, 165, "F = 1/φ2")
    formula("Apply the cited Humble sand relation for formation factor with phi=0.285.",
            .62/.285**2.15, "F", formation, 165, "F = 0.62/φ2.15")
    formula("Pf=1975 psi, Pc=55 psi. Obtain Po from the internal overburden relation and cite it.",
            2030, "Po", reservoir, 242, "Po = Pf + Pc")
    formula("Textbook GOR equation: use V1=84 scf, V2=42 scf and L2=7 stb; cite the formula.",
            18, "GOR", reservoir, 559, "GOR = (V1+V2) / L2")
    formula("Use the sourced saturation equation to calculate Rt for Ro=5 ohm-m, Sw=0.5.",
            20, "Rt", formation, 167, "Rt = Ro/Sw")
    formula("SG=0.956. Verify the internal oil API-gravity relation and calculate its result.",
            141.5/.956-131.5, "API", reservoir, 90, "API = (141.5 / SG) -131.5")

    multi = [
        ("A=46 stb/d, B=82 stb/d, C=52 stb/d. Give total, average, and descending rank.", [180, 60]),
        ("A=2350 psi, B=2490 psi, C=2200 psi. Report highest, lowest, and mean.", [2490, 2200, 2346.67]),
        ("Rate changes from 720 to 540 stb/d. State the absolute and percentage declines.", [180, 25]),
        ("gas=2016 scf, oil=63 stb. Calculate their ratio and name the larger input volume.", [32]),
        ("교재를 근거로 Monel collar가 directional survey에서 하는 일과 필요한 물성을 둘 다 설명해줘.", []),
        ("Compare the cited carbonate and sand formation-factor equations and their porosity exponents.", []),
    ]
    for question, values in multi:
        add("multi_goal", question, numeric=values)

    premises = [
        ("Pressure derivative on radial flow must rise with unit slope and overlay pressure, correct? Check the well-test notes.", ["no", "not", "incorrect", "false"], ["radial", "storage"]),
        ("If mud hydrostatic pressure is above formation pressure, that causes a kick, doesn't it? Cite drilling evidence.", ["no", "not", "incorrect", "false"], ["mud", "formation"]),
        ("The sourced formation-factor relation says F grows as porosity increases; is this true?", ["no", "not", "incorrect", "false"], ["porosity", "factor"]),
    ]
    for question, rejects, terms in premises:
        add("false_premise", question, reject_terms=rejects, support_terms=terms)

    for question in [
        "Search for the invented Nu-Theta permeability coupling and evaluate Theta from Nu=19 psi; do not assume an equation.",
        "Calculate my fictional lunar-fluid index LFI=?? from A=3 psi, only if a literal KB equation exists.",
        "내부 문헌에 없는 Quark-Omega 생성식을 찾아 Q=8에서 Omega를 계산해줘. 식 추측 금지.",
    ]:
        add("unanswerable", question, no_calculation=True)

    pending = [
        ("Internal SG-to-API relation으로 계산하고 싶은데 비중을 아직 주지 않았어.", "SG=0.89", [round(141.5/.89-131.5, 2)]),
        ("A=43 psi. Determine A-B after I supply B.", "B=17 psi", [26]),
        ("My relation Q=X+Y and X=14 psi; ask for the absent variable before solving Q.", "Y=5 psi", [19]),
        ("교재의 formation-factor F 관계식을 써줘. a=1, m=2만 알고 있어.", "phi=0.25", [16]),
        ("Gas volume=690 scf; determine GOR when I provide the oil volume.", "oil=23 stb", [30]),
        ("For the internal formation-factor equation, I know a=1 and m=2 but porosity is still missing.", "phi=0.20", [25]),
        ("A=67 stb/d. I need the total A+B and will send B next.", "B=31 stb/d", [98]),
        ("The supplied equation is Y=K+H; K=22 psi, H is not known yet. Ask for H.", "H=8 psi", [30]),
        ("Get F from the internal porosity relation. phi=0.25 and m=2 are known; ask if a is needed.", "a=1", [16]),
        ("I want the gas/oil ratio with gas=1032 scf. The oil amount will follow.", "oil=24 stb", [43]),
    ]
    for question, reply, values in pending:
        add("resume", question, resume=True, reply=reply, numeric=values)

    distribution = Counter(row["category"] for row in cases)
    assert distribution == {"knowledge": 10, "direct": 10, "user_formula": 8, "kb_formula": 10,
                            "multi_goal": 6, "false_premise": 3, "unanswerable": 3}
    assert len(cases) == 50 and len(resumes) == 10
    (HERE / "real_kb_dev_v23b.json").write_text(json.dumps({
        "status": "development_only_not_unseen", "model": "qwen3:8b", "web": False,
        "cases": cases, "resume_probes": resumes}, ensure_ascii=False, indent=2), encoding="utf-8")

    stress: list[dict] = []

    def stress_add(category: str, message: str, **expected: object) -> None:
        stress.append({"id": f"VBST{len(stress)+1:03d}", "category": category,
                       "message": message, **expected})

    triples = [(39, 72, 51), (64, 93, 48), (118, 76, 99), (53, 81, 67),
               (142, 95, 73), (37, 106, 58), (87, 124, 69), (111, 62, 84)]
    direct_forms = [
        ("A={a} stb/d, B={b} stb/d, C={c} stb/d. What is their total?", lambda a,b,c: [a+b+c]),
        ("A={a} stb/d, B={b} stb/d, C={c} stb/d. 전체 평균을 내줘.", lambda a,b,c: [round((a+b+c)/3,2)]),
        ("A={a} psi, B={b} psi, C={c} psi. Which reading is largest?", lambda a,b,c: [max(a,b,c)]),
        ("A={a} psi, B={b} psi, C={c} psi. Tell me the smallest value.", lambda a,b,c: [min(a,b,c)]),
        ("A={a} stb/d, B={b} stb/d, C={c} stb/d. 내림차순으로 정렬해줘.", lambda a,b,c: []),
    ]
    for a,b,c in triples:
        for template, expected in direct_forms:
            stress_add("direct", template.format(a=a,b=b,c=c), numeric=expected(a,b,c))

    pairs = [(13,4),(21,8),(29,6),(42,7),(55,12),(68,17)]
    user_forms = [
        ("A={a} psi, B={b} psi. Given R=A-B, determine R.", lambda a,b: a-b),
        ("A={a} psi, B={b} psi. User expression R=A+B; R을 구해줘.", lambda a,b: a+b),
        ("A={a}, B={b}. My model Z=A*B+3; calculate Z.", lambda a,b: a*b+3),
        ("A={a}, B={b}. Apply W=(A+B)/B and return W.", lambda a,b: (a+b)/b),
        ("A={a}, B={b}. My relation D=A/B; report D.", lambda a,b: a/b),
    ]
    for a,b in pairs:
        for template, expected in user_forms:
            stress_add("user_formula", template.format(a=a,b=b), numeric=[round(expected(a,b),2)])

    knowledge_roots = [row[0] for row in knowledge[:7]]
    knowledge_prefixes = ["", "Use only the local textbook: ", "Please give a short cited explanation: ",
                          "한 문단으로 근거를 포함해 설명해줘: ", "Focus on the exact source relation: "]
    for question in knowledge_roots:
        for prefix in knowledge_prefixes:
            stress_add("knowledge", prefix + question)

    kb_roots = [
        ("Use the literal SG/API conversion from the internal text; SG={v}. Calculate API.",
         [.851,.879,.906,.933,.961], lambda v: 141.5/v-131.5),
        ("Internal carbonate formation-factor relation: phi={v}. Determine F with citation.",
         [.185,.225,.245,.295,.325], lambda v: 1/v**2),
        ("Apply the cited formation-factor equation with a=1, m=2 and phi={v}; calculate F.",
         [.175,.215,.265,.315,.345], lambda v: 1/v**2),
        ("From the sourced Rt/Ro/Sw relation, Ro=5 ohm-m and Sw={v}; calculate Rt.",
         [.42,.52,.62,.72,.82], lambda v: 5/v**2),
        ("Pf=1800 psi, Pc={v} psi. Find the internal pressure equation for Po, then calculate Po.",
         [25,35,45,65,75], lambda v: 1800+v),
        ("Use the cited GOR volume equation with V1={v} scf, V2=32 scf, L2=8 stb. Find GOR.",
         [48,56,64,72,80], lambda v: (v+32)/8),
    ]
    for template, values, expected in kb_roots:
        for value in values:
            stress_add("kb_formula", template.format(v=value), numeric=[round(expected(value),2)])

    multi_forms = [
        ("A={a} stb/d, B={b} stb/d, C={c} stb/d. Return both total and highest item.", lambda a,b,c:[a+b+c,max(a,b,c)]),
        ("A={a} psi, B={b} psi, C={c} psi. Mean plus smallest reading, please.", lambda a,b,c:[round((a+b+c)/3,2),min(a,b,c)]),
        ("A={a} stb/d, B={b} stb/d, C={c} stb/d. 합계와 순위를 함께 알려줘.", lambda a,b,c:[a+b+c]),
        ("A={a} psi, B={b} psi, C={c} psi. Report maximum, minimum and average.", lambda a,b,c:[max(a,b,c),min(a,b,c),round((a+b+c)/3,2)]),
        ("A={a} stb/d, B={b} stb/d, C={c} stb/d. Average and highest item?", lambda a,b,c:[round((a+b+c)/3,2),max(a,b,c)]),
    ]
    for a,b,c in triples[:6]:
        for template, expected in multi_forms:
            stress_add("multi_goal", template.format(a=a,b=b,c=c), numeric=expected(a,b,c))

    premise_roots = [row[0] for row in premises] + [
        "In a fixed bulk volume, greater porosity means a smaller pore volume, yes? Check the definition."]
    for question in premise_roots:
        for prefix in ["", "Check this against internal sources: ", "Explicitly correct my premise: ",
                       "Cite the literal source relation: ", "근거와 대조해서 답해줘: "]:
            stress_add("false_premise", prefix + question)

    resume_roots = pending[:5]
    for question, reply, _ in resume_roots:
        for prefix in ["", "Please continue the same research run after my reply. ",
                       "Only ask for necessary missing information. "]:
            stress_add("resume", prefix + question, reply=reply)

    ood = ["Suggest a dinner recipe.", "Who won the basketball match yesterday?",
           "Write a film review.", "Find tomorrow's local weather forecast.",
           "Give me advice about choosing a guitar."]
    for question in ood:
        for prefix in ["", "Quick request: ", "친절히 답해줘: ", "One sentence only: "]:
            stress_add("out_of_domain", prefix + question)

    counts = Counter(row["category"] for row in stress)
    assert counts == {"direct": 40, "user_formula": 30, "knowledge": 35, "kb_formula": 30,
                      "multi_goal": 30, "false_premise": 20, "resume": 15, "out_of_domain": 20}
    assert len(stress) == 220 and len({row["message"] for row in stress}) == 220
    (HERE / "conference_stress_v23b.json").write_text(json.dumps({
        "status": "development_only_not_v4", "cases": stress}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated {len(cases)} real-KB, {len(resumes)} resume and {len(stress)} stress development prompts")


if __name__ == "__main__":
    main()
