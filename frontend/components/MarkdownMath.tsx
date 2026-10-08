"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { markKnownCitations, sourceForCitation, type CitationSource } from "@/lib/citations";

type MarkdownMathProps = {
  content: string;
  sources?: CitationSource[];
};

function CitationChip({ source }: { source: CitationSource }) {
  const [pinned, setPinned] = useState(false);
  const [position, setPosition] = useState<{ left: number; top?: number; bottom?: number }>({ left: 12, top: 12 });
  const name = source.document || source.title || source.url || "근거";
  const excerpt = source.excerpt || source.passage || source.snippet || "원문 발췌 없음";
  const place = (button: HTMLButtonElement) => {
    const rect = button.getBoundingClientRect();
    const width = Math.min(448, window.innerWidth - 24);
    const left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12));
    setPosition(window.innerHeight - rect.bottom >= 320
      ? { left, top: rect.bottom + 8 }
      : { left, bottom: window.innerHeight - rect.top + 8 });
  };

  return (
    <span className="group relative mx-0.5 inline-flex align-baseline">
      <button
        type="button"
        onClick={(event) => { place(event.currentTarget); setPinned((value) => !value); }}
        onMouseEnter={(event) => place(event.currentTarget)}
        onFocus={(event) => place(event.currentTarget)}
        aria-expanded={pinned}
        aria-label={`${source.evidence_id} 근거 보기`}
        className="rounded-md border border-violet-100 bg-violet-50 px-1.5 py-0.5 text-[10px] font-semibold leading-4 text-violet-500 hover:border-violet-200 hover:text-violet-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300"
      >[{source.evidence_id}]</button>
      <span
        role="tooltip"
        style={position}
        className={`fixed z-30 max-h-72 w-[min(28rem,calc(100vw-3rem))] overflow-y-auto rounded-xl border border-violet-100 bg-white p-3 text-left text-xs font-normal leading-5 text-slate-700 shadow-xl ${pinned ? "block" : "hidden group-hover:block group-focus-within:block"}`}
      >
        <span className="block font-bold text-violet-700">{source.evidence_id}</span>
        <span className="mt-1 block break-words">문서명: {name}</span>
        {source.page != null && <span className="block">페이지: {source.page}</span>}
        <span className="mt-2 block font-semibold">관련 내용:</span>
        <span className="block whitespace-pre-wrap break-words">{excerpt}</span>
      </span>
    </span>
  );
}

const CITATION_SENTINEL = "__AI_BRAIN_CITATION__";

const INLINE_CITATION_PATTERN =
  /\[([^\]\n]+?)(?:,\s*|\s+)p\.?\s*(\d+)(?::c\d+)?(?:\s+chunk\s+[^\]]+)?\]/gi;

function cleanCitationDocument(value: string): string {
  return value
    .trim()
    .replace(/^[0-9a-f]{64}_/i, "")
    .replace(/\.pdf$/i, "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ");
}

function formatInlineCitations(content: string): string {
  return content.replace(
    INLINE_CITATION_PATTERN,
    (_match, rawDocument: string, page: string) => {
      const document = cleanCitationDocument(rawDocument);
      const label = `${document} · p.${page}`;

      return `\`${CITATION_SENTINEL}${label}\``;
    },
  );
}

export function MarkdownMath({ content, sources = [] }: MarkdownMathProps) {
  const formattedContent = markKnownCitations(
    formatInlineCitations(content), new Set(sources.map((source) => source.evidence_id)), CITATION_SENTINEL,
  );

  return (
    <div className="min-w-0 text-sm leading-7 text-slate-700">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        skipHtml
        components={{
          p: ({ children }) => (
            <p className="mb-3 last:mb-0">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="mb-3 list-disc space-y-1 pl-5">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-3 list-decimal space-y-1 pl-5">
              {children}
            </ol>
          ),
          li: ({ children }) => <li>{children}</li>,
          code: ({ children, className }) => {
            const isBlock = Boolean(className);
            const value = String(children).replace(/\n$/, "");

            if (!isBlock && value.startsWith(CITATION_SENTINEL)) {
              const label = value.slice(CITATION_SENTINEL.length);
              const source = sourceForCitation(label, sources);
              if (source) return <CitationChip source={source} />;
              return (
                <span className="mx-0.5 inline text-[11px] font-normal leading-5 text-slate-400" aria-label="문서 출처">
                  [{label}]
                </span>
              );
            }

            return isBlock ? (
              <pre className="mb-3 overflow-x-auto rounded-xl bg-slate-950 p-3 text-xs text-slate-100">
                <code className={className}>{children}</code>
              </pre>
            ) : (
              <code className="rounded bg-slate-100 px-1 py-0.5 text-[0.9em]">
                {children}
              </code>
            );
          },
        }}
      >
        {formattedContent}
      </ReactMarkdown>
    </div>
  );
}
