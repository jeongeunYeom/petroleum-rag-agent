// Add frontend presentation snapshots to the fresh development smoke, never to frozen runs.
import { readFileSync, writeFileSync } from "node:fs";
import { displayAnswer, displayUnit, displayValue, outputLabel } from "../lib/goalResultPresentation.ts";

const path = process.argv[2];
if (!path || !path.endsWith("goal_execution_v8_ux_smoke.json")) {
  throw new Error("Pass the new v8 UX smoke JSON path only");
}
const report = JSON.parse(readFileSync(path, "utf8"));
for (const item of report.cases) {
  const computations = (item.computations || []).map((source) => ({
    computation_id: source.id,
    validation_passed: source.valid,
    source_input_ids: source.inputs || [],
    input_facts: [],
    output_manifest: source.manifest || {},
  }));
  item.presentation = {
    displayed_answer: displayAnswer(item.answer || "", computations),
    outputs: computations.filter((computation) => computation.validation_passed).flatMap((computation) =>
      Object.entries(computation.output_manifest).map(([output_id, output]) => ({
        computation_id: computation.computation_id, output_id,
        raw_value: output.value, raw_unit: output.unit ?? null,
        display_label: outputLabel(output), display_value: displayValue(output, computation),
        display_unit: displayUnit(output, computation),
      }))),
  };
}
writeFileSync(path, JSON.stringify(report, null, 2) + "\n", "utf8");
