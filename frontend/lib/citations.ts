export type CitationSource = {
  evidence_id: string;
  document?: string;
  title?: string | null;
  page?: number | null;
  excerpt?: string;
  passage?: string | null;
  snippet?: string;
  url?: string;
};

export function sourceForCitation(id: string, sources: CitationSource[]): CitationSource | undefined {
  return sources.find((source) => source.evidence_id === id);
}

export function markKnownCitations(content: string, sourceIds: Set<string>, sentinel: string): string {
  return content
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, index) => index % 2 ? part : part.replace(/\[([A-Z]+\d+)\]/g,
      (match, id: string) => sourceIds.has(id) ? `\`${sentinel}${id}\`` : match))
    .join("");
}
