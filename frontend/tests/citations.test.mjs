import assert from "node:assert/strict";
import test from "node:test";

import { markKnownCitations, sourceForCitation } from "../lib/citations.ts";

test("citation IDs resolve only to exact run sources", () => {
  const sources = [
    { evidence_id: "KB1", document: "Heriot-Watt.pdf", page: 90, excerpt: "actual excerpt" },
    { evidence_id: "KB2", document: "Other.pdf", page: 12, excerpt: "different excerpt" },
  ];
  assert.deepEqual(sourceForCitation("KB1", sources), sources[0]);
  assert.equal(sourceForCitation("KB3", sources), undefined);
});

test("only known citations become chips; code and unknown IDs stay untouched", () => {
  const content = "Answer [KB1] [KB9] and `[KB1]`\n```text\n[KB1]\n```";
  assert.equal(markKnownCitations(content, new Set(["KB1"]), "CITE:"),
    "Answer `CITE:KB1` [KB9] and `[KB1]`\n```text\n[KB1]\n```");
});
