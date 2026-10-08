import type { Computation, GoalResearchRun } from "./goalResearchApi";

type Output = Computation["output_manifest"][string];

const LABELS: Record<string, string> = {
  api: "API Gravity", api_gravity: "API Gravity", mean: "평균", ranking: "순위",
  leader_ids: "최상위 조건", best_parameter: "최적 조건", best_result: "최적 결과",
  worst_parameter: "최저 조건", worst_result: "최저 결과", mean_result: "평균 결과",
  range_result: "결과 범위", coefficient_of_variation: "변동계수",
};

export function clampIterations(value: string, fallback: number): number {
  if (!value.trim()) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.min(8, Math.max(1, Math.trunc(parsed))) : fallback;
}

export function formatNumber(value: number, fixedDecimals?: number): string {
  if (!Number.isFinite(value)) return String(value);
  if (fixedDecimals !== undefined) return value.toFixed(fixedDecimals);
  if (value !== 0 && Math.abs(value) < 0.0001) return value.toPrecision(4);
  return new Intl.NumberFormat("ko-KR", {
    maximumFractionDigits: Math.abs(value) < 1 ? 4 : 2,
  }).format(value);
}

function semanticName(output: Output): string {
  return output.name.replace(/^default_/i, "").replace(/^case_\d+_/i, "").toLowerCase();
}

export function outputLabel(output: Output): string {
  const name = semanticName(output);
  return LABELS[name] || name.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function displayUnit(output: Output, computation: Computation): string | null {
  if (output.semantic_type && output.semantic_type !== "numeric") return null;
  const name = semanticName(output);
  if (name === "api" || name === "api_gravity") return "°API";
  if (name === "coefficient_of_variation" || name === "percent_change") return "%";
  if (name === "ratio" || name === "specific_gravity" || name === "sg") return null;
  const raw = output.unit?.trim();
  if (raw && !/^(dimensionless|unitless)$/i.test(raw)) return raw === "percent" ? "%" : raw;
  if (/^(mean|median|range|sum|minimum|maximum|rms|std_population|std_sample)$/.test(name)) {
    const participating = computation.input_facts.filter((fact) =>
      !output.source_fact_ids?.length || output.source_fact_ids.some((id) =>
        id === fact.evidence_id || id === fact.canonical_fact_id));
    const units = [...new Set(participating.map((fact) => fact.unit).filter(
      (unit): unit is string => Boolean(unit && !/^(dimensionless|unitless)$/i.test(unit))))];
    if (participating.length > 0 && units.length === 1 && participating.every((fact) => fact.unit === units[0])) {
      return units[0];
    }
  }
  return null;
}

export function displayValue(output: Output, computation: Computation): string {
  if (Array.isArray(output.value)) {
    return output.value.join(semanticName(output) === "ranking" ? " > " : ", ");
  }
  if (typeof output.value !== "number") return String(output.value);
  const unit = displayUnit(output, computation);
  return `${formatNumber(output.value)}${unit ? ` ${unit}` : ""}`;
}

export function simulationTable(computation: Computation) {
  if (!computation.validation_passed) return null;
  const manifest = computation.output_manifest;
  const rows = Object.keys(manifest).filter((key) => /^OUT_CASE_\d+$/.test(key)).sort().map((key) => {
    const parameter = manifest[key.replace("OUT_CASE_", "OUT_PARAMETER_")];
    const result = manifest[key];
    return parameter && typeof parameter.value === "number" && typeof result.value === "number"
      ? { parameter, result } : null;
  });
  if (!rows.length || rows.some((row) => !row)) return null;
  const first = rows[0]!;
  return {
    parameterLabel: outputLabel(first.parameter),
    resultLabel: outputLabel(first.result),
    rows: rows as { parameter: Output; result: Output }[],
  };
}

export function evidenceCounts(run: GoalResearchRun) {
  const validated = run.computations.filter((item) => item.validation_passed);
  return {
    userInputs: new Set(validated.flatMap((item) => item.source_input_ids)).size,
    calculations: validated.length,
  };
}

export function displayAnswer(answer: string, computations: Computation[]): string {
  let result = answer;
  for (const computation of computations.filter((item) => item.validation_passed)) {
    for (const output of Object.values(computation.output_manifest)) {
      if (typeof output.value !== "number") continue;
      const raw = String(output.value);
      if (!/\.\d{5,}/.test(raw)) continue;
      const unit = displayUnit(output, computation);
      const escaped = raw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const pattern = new RegExp(`(^|[^\\d.])${escaped}${unit && output.unit === "dimensionless" ? "(?:\\s+dimensionless)?" : ""}(?![\\d.])`, "gm");
      result = result.replace(pattern, (_match, prefix: string) =>
        `${prefix}${formatNumber(output.value as number)}${unit && output.unit === "dimensionless" ? ` ${unit}` : ""}`);
    }
  }
  return result.replace(/\bdefault_API_gravity\b/g, "API Gravity")
    .replace(/(\[CALC\d+\])(?:\s*\[USERF\d+\])+/g, "$1")
    .replace(/\[USERF\d+\](?:\s*\[USERF\d+\])*/g, "[사용자 입력]")
    .replace(/\[EFACT\d+\]/g, "[자료 수치]")
    .replace(/\[FORMULA\d+\]/g, "[자료 수식]");
}
