# V21.2 product freeze

- Branch: `fix/v21-2-goal-completeness`
- Product SHA: `f5182b8ae2907452e1c53373055e66c5182c9b90`
- Base: `72a43487cbcc4c2d63529a78ebdd578c7e916e77`
- Targeted V21/V21.1/V21.2: 139 passed. Full backend: 1,693 passed. Frontend: 23 passed; build succeeded.
- The same 14 development prompts were run once with local `qwen3:8b`, hybrid retrieval and the unchanged 12-document/18,976-chunk KB. Under the [predeclared V21.2 acceptance](V21_2_PREDECLARED_ACCEPTANCE.md), 13 achieved and F3 safely stopped; no unexpected failures. The old runner's two-CALC C2 flag remains false and has not been rewritten.
- C2: one validated ECD calculation plus a literal cited hydrostatic relation, required goals `G1=MET`, `G2=MET`, final status ACHIEVED, no unsupported citation or numeric claim.
- A final comparison-only guard and its synthetic tests were added after the 14-case run. None of those 14 parsed a comparison/ranking RequiredGoal, so that guard was not exercised in the observed smoke; the full backend suite passed afterward. This provenance of the test sequence is disclosed rather than claiming a second smoke run.
- This is a development-tested product freeze, not a new unseen evaluation. Product code must not change after the observed old-24 regression starts.
