# Scoring audit

## Reviewer limitations retained without rescoring

- The frozen conservative aggregation requires both `hallucination_free=true` and no listed `material_errors`. Contradictory flag/list pairs are therefore scored as failures. Raw judgments are retained.
- Incorrect refusal/insufficiency statements and requests for already supplied operands were often classified as material errors. Most Agent failures on this metric are NOT demonstrated fabricated engineering facts. P19 also references an internal formula trace instead of only the visible answer. Do not use the complement as a fabrication rate; expert review is advised before a publication claim about hallucination.
- P11 numeric units were treated as inherited from the question/trace; P15's correct scalar did not receive full method-claim coverage. No post-hoc score override or additional judge invocation was performed.
- All figures/CSVs reproduce these recorded judgments, not an independent human review.

Single-reviewer AI-assisted semantic adjudication; deterministic all-claim, tolerance and denominator checks applied afterward. No response edits or model reruns. Raw judge labels and extracted numeric quotes are retained.

| Task | System | Claim scores | Numeric checks | Adjudication |
|---|---|---|---|---|
| P01 | chatgpt | [1, 1] | [] | Answer states that a gas anchor separates free gas from produced liquid before pump entry and that the gas goes into the tubing/casing annulus (described as annulus) to flow upward away from the pump, matching both required claims. |
| P01 | agent | [0, 0] | [] | Answer refuses despite attached evidence containing relevant support, so it does not satisfy either required claim. |
| P02 | chatgpt | [1, 1] | [] | Correctly identifies gel strength as the static gelling/thixotropic property that suspends cuttings when circulation stops, and distinguishes this from surface removal by mechanical solids-control equipment such as shale shakers/desanders/desilters. |
| P02 | agent | [1, 1] | [] | States that thixotropic mud properties keep cuttings suspended during circulation stops and that drilled solids are removed at surface by mechanical devices including shale shakers, desanders, and desilters. |
| P03 | chatgpt | [1, 1, 1] | [] | Answer correctly distinguishes squeeze cementing as later remedial work done by forcing cement into problem areas under pressure, and includes the two required remedial purposes: sealing water-producing zones and repairing casing leaks. |
| P03 | agent | [0, 0, 0] | [] | Answer refuses despite attached evidence explicitly supporting all required claims, so it fails the task and contradicts available evidence. |
| P04 | chatgpt | [0.5, 1, 0] | [] | Answer captures gas dissolution and destructive bubbles, but misses the explicit claims that compatibility requires testing and that rapid depressurisation should be avoided; it substitutes broader/extra advice. |
| P04 | agent | [0, 0, 0] | [] | Response refuses despite directly relevant attached evidence that answers all required claims. |
| P05 | chatgpt | [1, 1] | [] | States NPSHA must be greater than or equal to NPSHR and explains that if not met, cavitation occurs; this satisfies both required claims. Extra effects listed are ordinary engineering consequences, not contradictions. |
| P05 | agent | [1, 1] | [] | Directly states the required NPSHA ≥ NPSHR relationship and the consequence of cavitation or flashing if not met. Additional definitions are supported by cited evidence and do not conflict. |
| P06 | agent | [0, 0] | [] | Answer is an incorrect refusal despite attached evidence directly supporting both required claims. |
| P06 | chatgpt | [0.5, 0.5] | [] | Answer correctly explains that more emulsified water and fine solids increase viscosity, but it does not fully state the source-specific claims that properly emulsified water behaves like a solid and that fine drilled solids raise PV, YP, and gel strength. |
| P07 | chatgpt | [1, 1, 1] | [] | Answer explicitly gives the inverse capillary-pressure/pore-radius relationship, states water remains on grain surfaces and in smallest pores in water-wet rock, and correctly concludes fine/silty sand retains more interstitial water than coarse sand. |
| P07 | agent | [1, 0, 0.5] | [] | Answer correctly states smaller pores give higher capillary pressure and that silty fine sand has smaller pores, but it omits the required water-wet mechanism that water coats rock surfaces and occupies the smallest pores, and only implies rather than fully explains higher retained interstitial water. |
| P08 | agent | [0, 0, 0] | [] | Answer is a refusal/unsupported insufficiency statement and does not address any required claim, despite relevant evidence existing in the task sources. |
| P08 | chatgpt | [1, 1, 0.5] | [] | Correctly explains that poor cleaning/balling can prevent ROP gains from added WOB and links hydraulic horsepower to pressure drop and flow. It mentions nozzle adjustment and flow increase, but does not explicitly note the tradeoff with annular velocity or the source-supported extended/additional nozzle cleaning changes. |
| P09 | chatgpt | [1, 1, 0.5] | [] | Correctly explains that entrained air is counted in the surface density reading and that compression downhole raises actual density. But it does not state the required severe-foaming mechanism of pump cavitation causing loss of hydrostatic pressure, instead adding unsupported consequences. |
| P09 | agent | [1, 1, 1] | [] | Directly covers all required claims: entrained air is included in the surface measurement, air compresses downhole so actual density is higher, and severe foaming can cause pump cavitation and loss of hydrostatic pressure. |
| P10 | agent | [0, 0, 0] | [] | Answer does not address the conceptual question despite attached evidence explicitly covering grid-size sensitivity, pseudos, and fine-vs-coarse relative permeability usage. |
| P10 | chatgpt | [0.5, 0.5, 1] | [] | Answer correctly distinguishes fine-grid rock relative permeability from coarse-grid pseudo properties, but it does not explicitly state the source-specific linkage to numerical dispersion and layering. |
| P11 | chatgpt | [1, 1] | [True, True] | Answer explicitly gives both required results with correct arithmetic and units, with no contradictions. |
| P11 | agent | [1, 1] | [True, True] | Answer reports both required numeric outputs correctly; trace shows all four inputs were used in sum and mean calculation. |
| P12 | agent | [0, 0] | [False, False] | Did not compute either requested quantity and instead asked for unnecessary additional information. |
| P12 | chatgpt | [1, 1] | [True, True] | Correctly sorted the seven lengths, identified the 4th value as the median, and computed 33 minus 14 for the range. |
| P13 | agent | [0] | [False] | Did not provide the requested ratio; refused despite sufficient inputs in the question. |
| P13 | chatgpt | [1] | [True] | Correctly computes captured divided by flared as 12 and states the equivalent ratio 12:1. |
| P14 | agent | [0, 0] | [False, False] | Answer is a refusal stating sources did not support an answer; it does not compute the requested values and does not contradict facts. |
| P14 | chatgpt | [1, 1] | [True, True] | Correctly adds cartridges and labour, subtracts the credit, then computes overrun relative to the $2000 budget as 3%. |
| P15 | agent | [0.5, 1] | [True] | Reports the correct final value, but the answer text does not actually show application of the supplied relation or the operands; trace indicates calculation occurred, so partial credit on the method claim. |
| P15 | chatgpt | [1, 1] | [True] | Shows the supplied formula, substitutes all three operands, and computes the correct dimensionless result 8.75. |
| P16 | chatgpt | [1, 1] | [True] | Uses the provided quadratic formula with both supplied inputs 4.6 and 5.8, and computes the final dimensionless result 10.26 within tolerance. |
| P16 | agent | [0, 0] | [False] | Incorrectly asks for a value that was already provided, so it neither applies the supplied formula nor gives the required numeric result. |
| P17 | agent | [0, 0] | [False] | Did not use the supplied formula or coefficients and failed to provide the requested numeric result. |
| P17 | chatgpt | [1, 1] | [True] | Applies the exact provided relation with all given coefficients and computes the correct dimensionless result 5.6. |
| P18 | chatgpt | [1, 1] | [True] | States the correct HHP relation, substitutes 2850 psi and 420 gpm, and gives hydraulic output ≈698.4 hp while explicitly distinguishing it from shaft input power. |
| P18 | agent | [0, 0] | [False] | Refuses despite sufficient inputs being present, so it neither states the formula nor computes the hydraulic output. |
| P19 | chatgpt | [1, 1] | [True] | Answer states the round-trip relation depth = v×t/2 and correctly computes 410×3.8/2 = 779 m. |
| P19 | agent | [0, 0] | [False] | No usable answer was provided; the trace shows refusal/blocking and an incorrect subtraction formula instead of half sound-speed times travel time. |
| P20 | chatgpt | [1, 1] | [True] | Answer states the correct relationship equivalent to Pcirc = Psurf - Pbit and correctly computes 3125 - 1170 = 1955 psi. |
| P20 | agent | [0, 0] | [False] | Answer does not provide the required formula or the calculated circulating-system pressure loss, despite sufficient given data. |
| P21 | chatgpt | [1, 1, 1] | [] | Answer explicitly rejects the premise and correctly explains that invasion can change pore-fluid salinity, which can change resistivity even if water saturation is unchanged. Extra mention of fluid distribution is general engineering elaboration, not a contradiction. |
| P21 | agent | [1, 0.5, 0.5] | [] | Answer rejects the premise, but it does not clearly state the key Heriot-Watt mechanism that filtrate can change salinity; instead it relies on broader invasion/resistivity citations and overstates the conclusion as always changing resistivity. |
| P22 | chatgpt | [1, 1, 1] | [] | Answer explicitly says the statement is incorrect and correctly states that invert oil-emulsion mud is oil-continuous with water/brine droplets dispersed in oil. |
| P22 | agent | [1, 1, 1] | [] | Answer rejects the premise and correctly identifies oil as the continuous phase and water as the dispersed droplet phase, consistent with the attached drilling reference. |
| P23 | chatgpt | [1, 1, 1] | [] | Answer explicitly says an exact aromatic concentration cannot be determined, asks for elastomer compound and temperature, and requests fluid composition plus manufacturer/test compatibility data rather than inventing a limit. |
| P23 | agent | [0.5, 0, 0] | [] | Response is a generic refusal. It does not identify the missing engineering inputs the task asked for, despite attached evidence indicating compatibility testing is needed for aromatic crude with PCP elastomers. |
| P24 | chatgpt | [1, 1, 1] | [] | Explicitly states the exact minimum level cannot be determined from the given information and lists the specific pump, elevation/datum, pressure, liquid property, flow, and suction-loss inputs needed to evaluate NPSHA versus NPSHR. |
| P24 | agent | [1, 0, 0] | [] | Correctly gives no invented number, but fails the core request to explain the specific data needed and incorrectly claims the sources did not establish inputs. |
