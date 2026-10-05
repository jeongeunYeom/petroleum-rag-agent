# V3 pre-run input-contract audit — blocked before any Agent answer

Freeze commit: `092200d01c3cb74204913d42c2269e5696bed61d`. Product SHA: `f71896627cc77cd6df569bb3cd140289d3667fac`. No A/B task was run and no product output was viewed.

The 12 tasks pass structural checks (8/2/2; pipeline 6, end-to-end 2; 52 required numeric targets; 40 pipeline targets), all 11 source chunk locators exist in the real 18,976-chunk KB, and the independent arithmetic agrees with every frozen target. However, a read-only static extraction check using Agent v4's existing USERF and EFACT parsers found that the required inputs cannot reach the canonical plan:

| Task | Expected USERF extracted | Expected EFACT extracted |
|---|---:|---:|
| PY3-RE-01 | 0/20 | 0/0 |
| PY3-RE-02 | 0/21 | 0/0 |
| PY3-RE-03 | 0/10 | 0/0 |
| PY3-FE-04 | 0/14 | 0/0 |
| PY3-RE-05 | 0/4 | 0/1 |
| PY3-WT-06 | 0/24 | 0/0 |
| PY3-RE-07 | 0/0 | 1/23 |
| PY3-FE-08 | 0/0 | 0/9 |
| PY3-RE-09 | 0/2 | 0/0 |
| PY3-WT-10 | 0/2 | 0/0 |

The matching above is on numeric value **and unit**, avoiding runtime-ID assumptions. `UserFactRegistry` accepts a limited unit vocabulary and tuple headers only when every column has one of those units. The frozen tasks use unsupported units including `rb/STB`, `rb/scf`, `degR`, `degF`, `degAPI`, `ohm-m`, `g/cm3`, and `lb/ft3`; several structures therefore yield zero USERF records. `EvidenceFactRegistry` also requires a unit immediately adjacent to each value; the PDF tables generally put units in column headings, so their row cells are not eligible EFACTs. One end-to-end task additionally relies on dimensionless mole fractions, contrary to the request's prohibition on unsupported unitless evidence as core required inputs.

This is a **benchmark design invalidity**, not an observed Agent v4 failure. Running 24 expensive LLM tasks would not answer whether the supported canonical Python path works; it would mostly measure whether impossible required facts can be extracted. Because the benchmark was already frozen and the user explicitly forbade post-freeze task/source/GT/prompt changes, the run was stopped before task 1. A separately identified, pre-output replacement freeze is needed before a valid A/B evaluation can proceed. Do not silently edit or rerun this frozen version.
