import { useEffect, useState } from "react";

import { getAnalysis } from "../../api/projects";
import type { AIEnrichmentStatus, AnalysisStatus, AnalysisStatusResponse } from "../../types";

interface AnalysisStatusPanelProps {
  projectId: string;
  analysisId: string;
  initialStatus: AnalysisStatus;
  onStatusUpdate?: (analysis: AnalysisStatusResponse) => void;
}

const terminalStatuses: AnalysisStatus[] = ["completed", "failed"];
const statusLabels: Record<AnalysisStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
};
const enrichmentLabels: Record<AIEnrichmentStatus, string> = {
  not_started: "Not started",
  running: "Running",
  completed: "Completed",
  partial: "Partial; review needed",
  failed: "Unavailable",
};

export function AnalysisStatusPanel({ projectId, analysisId, initialStatus, onStatusUpdate }: AnalysisStatusPanelProps) {
  const [analysis, setAnalysis] = useState<AnalysisStatusResponse | null>(null);
  const [status, setStatus] = useState<AnalysisStatus>(initialStatus);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function poll() {
      try {
        const next = await getAnalysis(analysisId);
        if (cancelled) return;
        setAnalysis(next);
        setStatus(next.status);
        onStatusUpdate?.(next);
        setRefreshError(null);
        if (!terminalStatuses.includes(next.status)) {
          timer = window.setTimeout(poll, 2000);
        }
      } catch (error) {
        if (cancelled) return;
        setRefreshError(error instanceof Error ? error.message : "Could not refresh analysis status.");
        timer = window.setTimeout(poll, 5000);
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [analysisId]);

  return (
    <section className="mt-6 rounded-xl border border-cyan-400/30 bg-slate-900 p-5" aria-labelledby="analysis-status-title">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="analysis-status-title" className="text-lg font-semibold text-white">Analysis {statusLabels[status].toLowerCase()}</h2>
          <p className="mt-1 text-sm text-slate-400">Analysis ID: <span className="font-mono text-slate-200">{analysisId}</span></p>
          <p className="mt-1 text-sm text-slate-400">Project ID: <span className="font-mono text-slate-200">{projectId}</span></p>
          {analysis && (
            <div className="mt-3" aria-live="polite">
              <div className="flex justify-between text-sm text-slate-300">
                <span>AI enrichment: {enrichmentLabels[analysis.ai_enrichment_status ?? "not_started"]}</span>
                <span>{analysis.ai_enrichment_progress ?? 0}%</span>
              </div>
              <progress
                className="mt-2 h-2 w-full accent-violet-400"
                value={analysis.ai_enrichment_progress ?? 0}
                max={100}
                aria-label="AI enrichment progress"
              />
            </div>
          )}
        </div>
        <span className="rounded-full border border-cyan-300/30 px-3 py-1 text-sm text-cyan-200" role="status">
          {statusLabels[status]}
        </span>
      </div>

      {analysis && (
        <div className="mt-5">
          <div className="flex justify-between text-sm text-slate-300">
            <span>{analysis.current_stage}</span>
            <span>{analysis.progress}%</span>
          </div>
          <progress className="mt-2 h-2 w-full accent-cyan-400" value={analysis.progress} max={100} aria-label="Analysis progress" />
          {analysis.error_details && (
            <p className="mt-3 text-sm text-rose-300" role="alert">
              {analysis.error_details.message} ({analysis.error_details.code})
            </p>
          )}
          {analysis.ai_enrichment_error && (
            <p className="mt-3 text-sm text-amber-300" role="status">
              {analysis.status === "completed"
                ? "Deterministic analysis is ready; AI enrichment is partial or unavailable. "
                : "AI enrichment: "}
              {analysis.ai_enrichment_error.message} ({analysis.ai_enrichment_error.code})
            </p>
          )}
          {analysis.ai_enrichment_status === "partial" && !analysis.ai_enrichment_error && (
            <p className="mt-3 text-sm text-amber-300" role="status">
              Deterministic results are preserved. Some AI output was downgraded or omitted and requires human review.
            </p>
          )}
        </div>
      )}
      {refreshError && <p className="mt-3 text-sm text-amber-300" role="status">Status refresh failed: {refreshError}. Retrying.</p>}
    </section>
  );
}
