import { useEffect, useState } from "react";

import { getEvidenceDetail } from "../../api/projects";
import type { EvidenceDetail, EvidenceReference } from "../../types";

interface EvidenceDrawerProps {
  analysisId: string;
  evidence: EvidenceReference | null;
  onClose: () => void;
}

function safeGitHubUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && (url.hostname === "github.com" || url.hostname === "www.github.com")
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function EvidenceDrawer({ analysisId, evidence, onClose }: EvidenceDrawerProps) {
  const [detail, setDetail] = useState<EvidenceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);
    if (!evidence) return () => { cancelled = true; };
    setLoading(true);
    getEvidenceDetail(analysisId, evidence.evidence_id)
      .then((result) => { if (!cancelled) setDetail(result); })
      .catch((requestError: unknown) => {
        if (!cancelled) setError(requestError instanceof Error ? requestError.message : "Could not load evidence.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [analysisId, evidence]);

  useEffect(() => {
    if (!evidence) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [evidence, onClose]);

  if (!evidence) return null;
  const externalUrl = safeGitHubUrl(evidence.source_url);
  let sourceTitle = evidence.source_identifier;
  if (detail) {
    try {
      const value: unknown = JSON.parse(detail.content);
      if (value && typeof value === "object" && !Array.isArray(value)) {
        const fields = value as Record<string, unknown>;
        const title = fields.title ?? fields.message ?? fields.full_name;
        if (typeof title === "string" && title.trim()) sourceTitle = title;
      }
    } catch { /* raw text uses its source identifier as the available title */ }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <aside className="h-full w-full max-w-2xl overflow-y-auto border-l border-slate-700 bg-slate-950 p-5 shadow-2xl sm:p-8" role="dialog" aria-modal="true" aria-labelledby="evidence-title">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-cyan-300">Source evidence</p>
            <h2 id="evidence-title" className="mt-2 text-xl font-semibold text-white">{sourceTitle}</h2>
            <p className="mt-1 text-sm text-slate-400">{evidence.evidence_type.replace(/_/g, " ")}</p>
          </div>
          <button type="button" autoFocus className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800" onClick={onClose} aria-label="Close evidence details">Close</button>
        </div>
        <dl className="mt-6 grid gap-4 border-y border-slate-800 py-5 text-sm sm:grid-cols-2">
          <div><dt className="text-slate-500">Retrieved</dt><dd className="mt-1 text-slate-200">{new Date(evidence.retrieved_at).toLocaleString()}</dd></div>
          <div><dt className="text-slate-500">Commit SHA</dt><dd className="mt-1 break-all font-mono text-slate-200">{evidence.repository_commit_sha ?? "Not available"}</dd></div>
          <div className="sm:col-span-2"><dt className="text-slate-500">Source URL</dt><dd className="mt-1 break-all">{externalUrl ? <a className="text-cyan-300 underline" href={externalUrl} target="_blank" rel="noopener noreferrer">{externalUrl}</a> : <span className="text-slate-300">No safe GitHub link available.</span>}</dd></div>
        </dl>
        <section className="mt-6" aria-labelledby="stored-content-title">
          <h3 id="stored-content-title" className="text-sm font-semibold text-white">Stored content</h3>
          {loading && <p className="mt-3 text-sm text-slate-400" role="status">Loading evidence…</p>}
          {error && <p className="mt-3 text-sm text-rose-300" role="alert">{error}</p>}
          {detail && <pre className="mt-3 max-h-[55vh] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-slate-800 bg-slate-900 p-4 font-mono text-xs leading-6 text-slate-200">{detail.content}</pre>}
        </section>
        <section className="mt-6" aria-labelledby="related-findings-title">
          <h3 id="related-findings-title" className="text-sm font-semibold text-white">Related findings</h3>
          {detail?.related_finding_ids.length ? <ul className="mt-2 list-inside list-disc text-sm text-slate-300">{detail.related_finding_ids.map((id) => <li key={id} className="font-mono">{id}</li>)}</ul> : <p className="mt-2 text-sm text-slate-400">No deterministic finding references this evidence.</p>}
        </section>
      </aside>
    </div>
  );
}
