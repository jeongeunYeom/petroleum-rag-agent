"use client";

import { useCallback, useEffect, useState } from "react";
import {
  API_BASE,
  deleteDocument,
  type DocumentRecord,
} from "@/lib/api";

function cleanTitle(document: DocumentRecord) {
  return (document.title || document.filename).replace(/\.[^/.]+$/, "");
}

type DocumentInfoPanelProps = {
  refreshKey?: number;
  onDocumentsChanged?: () => void;
};

export function DocumentInfoPanel({
  refreshKey = 0,
  onDocumentsChanged,
}: DocumentInfoPanelProps) {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const response = await fetch(`${API_BASE}/documents`, { cache: "no-store" });
    if (response.ok) setDocuments(await response.json());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshKey]);

  const removeDocument = useCallback(
    async (document: DocumentRecord) => {
      const confirmed = window.confirm(
        `"${cleanTitle(document)}" 문서와 ChromaDB의 관련 청크 ${document.chunks}개를 모두 삭제할까요?\n\n이 작업은 되돌릴 수 없습니다.`,
      );
      if (!confirmed) return;

      setDeletingId(document.document_id);
      setError(null);
      try {
        await deleteDocument(document.document_id);
        setDocuments((current) =>
          current.filter(
            (item) => item.document_id !== document.document_id,
          ),
        );
        onDocumentsChanged?.();
      } catch (caught) {
        setError(
          caught instanceof Error
            ? caught.message
            : "문서를 삭제하지 못했습니다.",
        );
      } finally {
        setDeletingId(null);
      }
    },
    [onDocumentsChanged],
  );

  if (!documents.length) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-3 text-xs text-slate-500 shadow-sm">
        No indexed documents yet.
      </div>
    );
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-3 text-slate-900 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-bold">Recent Documents</h2>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-500">{documents.length}</span>
      </div>

      <div className="mt-3 max-h-80 space-y-1.5 overflow-y-auto pr-1">
        {documents.slice(0, 20).map((document) => (
          <article key={document.document_id} className="group rounded-xl px-2 py-2 text-xs hover:bg-slate-50">
            <div className="flex min-w-0 items-start gap-2">
              <span className="mt-0.5 shrink-0">📄</span>
              <div className="min-w-0 flex-1">
                <p
                  className="overflow-hidden break-words font-semibold text-slate-800"
                  style={{ display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2 }}
                  title={document.filename}
                >{document.title || document.filename}</p>
                <p className="mt-0.5 truncate text-[11px] text-slate-500" title={document.filename}>{document.pages} pages · {document.chunks} chunks</p>
              </div>
              <button
                type="button"
                onClick={() => void removeDocument(document)}
                disabled={deletingId !== null}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-400 opacity-70 transition hover:bg-red-50 hover:text-red-600 hover:opacity-100 focus:opacity-100 disabled:cursor-wait disabled:opacity-40 group-hover:opacity-100"
                aria-label={`${cleanTitle(document)} 문서 삭제`}
                title="문서와 관련 청크 삭제"
              >
                {deletingId === document.document_id ? (
                  <span className="text-[10px]">···</span>
                ) : (
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    className="h-4 w-4"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m3 0-1 13H7L6 7" />
                  </svg>
                )}
              </button>
            </div>
          </article>
        ))}
      </div>
      {error && (
        <p className="mt-2 rounded-lg bg-red-50 px-2 py-1.5 text-[11px] text-red-700">
          삭제 실패: {error}
        </p>
      )}
    </section>
  );
}
