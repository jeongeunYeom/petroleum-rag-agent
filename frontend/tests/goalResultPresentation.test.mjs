import assert from "node:assert/strict";
import test from "node:test";

import {
  clampIterations, displayAnswer, displayUnit, displayValue, evidenceCounts,
  formatNumber, simulationTable,
} from "../lib/goalResultPresentation.ts";

const computation = (manifest, unit = "stb/d") => ({
  computation_id: "CALC1", validation_passed: true, output_manifest: manifest,
  source_input_ids: ["USERF1", "USERF2", "USERF1"],
  input_facts: [
    { name: "A_rate", value: 187, unit, evidence_id: "USERF1" },
    { name: "B_rate", value: 234, unit, evidence_id: "USERF2" },
  ],
});

test("iteration entry clamps on submission and preserves a valid fallback", () => {
  assert.equal(clampIterations("0", 4), 1);
  assert.equal(clampIterations("-1", 4), 1);
  assert.equal(clampIterations("9", 4), 8);
  assert.equal(clampIterations("100", 4), 8);
  assert.equal(clampIterations("abc", 4), 4);
  assert.equal(clampIterations("", 4), 4);
  assert.equal(clampIterations("5", 4), 5);
});

test("engineering units use semantic quantity and participating input units", () => {
  const mean = { name: "mean", value: 194.66666666666666, unit: null, semantic_type: "numeric", source_fact_ids: ["USERF1", "USERF2"] };
  const pressure = computation({ OUT_range: { name: "range", value: 47, unit: null, semantic_type: "numeric" } }, "psi");
  assert.equal(displayUnit(mean, computation({ OUT_mean: mean })), "stb/d");
  assert.equal(displayUnit(pressure.output_manifest.OUT_range, pressure), "psi");
  assert.equal(displayUnit({ name: "ranking", value: ["B", "A"], semantic_type: "ranking" }, pressure), null);
  assert.equal(displayUnit({ name: "coefficient_of_variation", value: 12, unit: "percent", semantic_type: "numeric" }, pressure), "%");
  assert.equal(displayUnit({ name: "default_API_gravity", value: 22.639433551198238, unit: "dimensionless", semantic_type: "numeric" }, pressure), "°API");
  assert.equal(displayUnit({ name: "specific_gravity", value: 0.918, unit: "dimensionless", semantic_type: "numeric" }, pressure), null);
});

test("numeric noise is display-only and repeated USERF citations are grouped", () => {
  const raw = 22.639433551198238;
  const output = { name: "default_API_gravity", value: raw, unit: "dimensionless", semantic_type: "numeric" };
  const calc = computation({ OUT_default_API_gravity: output });
  assert.equal(displayValue(output, calc), "22.64 °API");
  assert.equal(formatNumber(194.66666666666666), "194.67");
  assert.equal(formatNumber(0.30000000000000004), "0.3");
  assert.equal(displayAnswer("default_API_gravity: 22.639433551198238 dimensionless [CALC1] [USERF1] [USERF2] [KB1]", [calc]),
    "API Gravity: 22.64 °API [CALC1] [KB1]");
  assert.equal(output.value, raw);
});

test("simulation table and evidence counts come from validated manifests", () => {
  const calc = computation({
    OUT_PARAMETER_001: { name: "case_1_porosity", value: 0.1, unit: null },
    OUT_CASE_001: { name: "case_1_score", value: 15, unit: null },
    OUT_PARAMETER_002: { name: "case_2_porosity", value: 0.3, unit: null },
    OUT_CASE_002: { name: "case_2_score", value: 25, unit: null },
  });
  const table = simulationTable(calc);
  assert.equal(table?.parameterLabel, "Porosity");
  assert.equal(table?.resultLabel, "Score");
  assert.deepEqual(table?.rows.map((row) => row.result.value), [15, 25]);
  assert.deepEqual(evidenceCounts({ computations: [calc, { ...calc, validation_passed: false }] }),
    { userInputs: 2, calculations: 1 });
});
