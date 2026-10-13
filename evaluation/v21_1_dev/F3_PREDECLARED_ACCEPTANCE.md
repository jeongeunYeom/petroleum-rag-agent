# F3 acceptance declared before the v21.1 smoke rerun

Outcome class: **EXPECTED_SAFE_STOP**, not an achieved calculation.

The existing F3 prompt supplies absolute permeability and viscosity. The retrieved production-KB phase-mobility relation requires phase/relative permeability, which is not supplied or derivable from those two values alone. Accept F3 only if the run stops or asks for the genuinely missing source/input, executes no unsupported calculation, does not substitute absolute permeability for relative permeability, and explains that the required relation or input is unverified. A numeric mobility answer without that provenance fails.

The F3 prompt, values, source corpus, and evaluator will not be changed for this rerun. No other smoke case receives a safe-stop exception without a pre-execution physical justification.
