"""Create deterministic, fresh visitor-style V23 development prompts (not V4)."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    rows: list[dict] = []

    def add(category: str, message: str, **extra: object) -> None:
        rows.append({"id": f"ST{len(rows) + 1:03d}", "category": category,
                     "message": message, **extra})

    triples = [(34, 61, 29), (52, 78, 43), (87, 104, 56), (95, 41, 70),
               (123, 64, 89), (43, 36, 75), (132, 97, 84), (68, 54, 101),
               (71, 140, 63), (105, 88, 42)]
    direct_templates = [
        "Well A={a} stb/d, B={b} stb/d, C={c} stb/d. Add these rates.",
        "A={a} stb/d, B={b} stb/d, C={c} stb/d. 총 생산 유량은?",
        "A={a} psi, B={b} psi, C={c} psi. Calculate the average pressure.",
        "A={a} psi, B={b} psi, C={c} psi. 최댓값 얼마야?",
        "A={a} stb/d, B={b} stb/d, C={c} stb/d. Rank high to low.",
        "A={a} stb/d, B={b} stb/d, C={c} stb/d. What's the combined production?",
    ]
    for a, b, c in triples:
        for index, template in enumerate(direct_templates):
            expected = (a + b + c if index in {0, 1, 5} else
                        (a + b + c) / 3 if index == 2 else max(a, b, c) if index == 3 else None)
            add("direct", template.format(a=a, b=b, c=c), numeric=[expected] if expected is not None else [])

    pairs = [(8, 3), (16, 5), (25, 7), (36, 9), (44, 11),
             (56, 13), (63, 14), (72, 18)]
    formula_templates = [
        "A={a} psi, B={b} psi. My equation is R=A-B. Calculate R.",
        "A={a} psi, B={b} psi. 사용자 식 R=A+B를 계산해줘.",
        "A={a}, B={b}. I define Z=A*B+2. Evaluate Z.",
        "A={a}, B={b}. 식 W=(A+B)/B로 W 구해줘.",
        "A={a}, B={b}. Use my relation D=A/B and report D.",
    ]
    for a, b in pairs:
        for index, template in enumerate(formula_templates):
            expected = (a - b, a + b, a * b + 2, (a + b) / b, a / b)[index]
            add("user_formula", template.format(a=a, b=b), numeric=[expected])

    knowledge = [
        "How does a nonmagnetic collar help directional drilling surveys?",
        "What is water saturation in a clean reservoir rock?",
        "Which pressure difference defines capillary pressure at the oil-water interface?",
        "Why is a derivative curve used in a well-test type-curve match?",
        "What is the purpose of an appraisal well after discovery?",
        "Explain fractional flow in waterflood analysis using internal notes.",
        "How do sand and carbonate formation factors differ in the internal text?",
        "What causes magnetic interference in directional survey tools?",
        "Why do offshore development plans benefit from reservoir simulation?",
        "Describe resistivity-based water saturation in clean formations.",
    ]
    for message in knowledge:
        add("knowledge", message)
        add("knowledge", "내부 자료 근거로 설명해줘: " + message)
        add("knowledge", "Internal textbook only; give a concise cited answer. " + message)

    kb_cases = [
        ("API gravity", "SG", [0.84, 0.87, 0.91, 0.94]),
        ("carbonate formation factor F", "phi", [0.18, 0.21, 0.23, 0.27]),
        ("formation factor F with a=1 and m=2", "phi", [0.16, 0.19, 0.22, 0.26]),
        ("Rt from Ro=4 ohm-m", "Sw", [0.40, 0.50, 0.60, 0.80]),
        ("Po from Pf=1800 psi and Pc", "Pc", [20, 30, 40, 50]),
    ]
    for group, (target, symbol, values) in enumerate(kb_cases):
        for value in values:
            expected = (141.5 / value - 131.5 if group == 0 else 1 / value ** 2 if group in {1, 2}
                        else 4 / value ** 2 if group == 3 else 1800 + value)
            add("kb_formula", f"Find the internal textbook equation for {target}; {symbol}={value}. Calculate with a formula citation.",
                numeric=[round(expected, 2)])

    multi_templates = [
        "A={a} stb/d, B={b} stb/d, C={c} stb/d. Give total and mean.",
        "A={a} stb/d, B={b} stb/d, C={c} stb/d. 총합과 가장 높은 항목은?",
        "A={a} psi, B={b} psi, C={c} psi. Find mean and minimum.",
        "A={a} psi, B={b} psi, C={c} psi. 평균과 순위 알려줘.",
    ]
    for a, b, c in triples[:5]:
        for index, template in enumerate(multi_templates):
            expected = ([a + b + c, (a + b + c) / 3] if index == 0 else
                        [a + b + c, max(a, b, c)] if index == 1 else
                        [(a + b + c) / 3, min(a, b, c)] if index == 2 else
                        [(a + b + c) / 3])
            add("multi_goal", template.format(a=a, b=b, c=c), numeric=[round(number, 2) for number in expected])

    premises = [
        "Radial-flow pressure derivative must be unit slope like early wellbore storage, correct?",
        "A drilling kick means mud hydrostatic pressure is greater than formation pressure, right?",
        "Does formation factor increase as porosity increases in the clean-formation relation?",
    ]
    for premise in premises:
        for prefix in ("", "Check the internal evidence: ", "내부 교재를 보고 판단해줘: ",
                       "Please explicitly correct any wrong assumption: ", "근거 인용도 해줘: "):
            add("false_premise", prefix + premise)

    unrelated = ["오늘 서울 날씨 예보 알려줘.", "Summarize a chess opening for me.",
                 "Write a cake recipe.", "Recommend a new comedy movie.",
                 "Who won the football match yesterday?"]
    for item in unrelated:
        for prefix in ("", "Quick question: ", "아주 짧게 답해줘: "):
            add("out_of_domain", prefix + item)

    resume = [
        ("내부 교재의 SG-API 식으로 계산하고 싶어. SG가 필요하면 물어봐.", "SG=0.88"),
        ("A=27 psi. Find A-B, but B has not been supplied yet.", "B=9 psi"),
        ("My equation is Q=X+Y, X=11 psi. Ask for Y then continue.", "Y=4 psi"),
        ("Formation factor F를 교재 식으로 계산해줘. a=1, m=2만 우선 줄게.", "phi=0.2"),
        ("Calculate gas/oil ratio: gas=540 scf; oil amount is missing.", "oil=18 stb"),
    ]
    for message, reply in resume:
        add("resume", message, reply=reply)
        add("resume", "I need a sourced or calculated result. " + message, reply=reply)

    if len(rows) != 210 or len({row["message"] for row in rows}) != len(rows):
        raise RuntimeError("Stress prompt generation must produce 210 unique messages")
    output = HERE / "conference_stress.json"
    output.write_text(json.dumps({"status": "fresh_development_only_not_v4", "cases": rows},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated {len(rows)} development stress prompts: {output}")


if __name__ == "__main__":
    main()
