import { useCallback, useRef, useState } from "react";

import { getAIEnrichment, getAnalysisResults, getEvidenceDetail } from "../api/projects";
import { AppHeader } from "../components/AppHeader";
import { RepositoryUrlForm } from "../features/repository/RepositoryUrlForm";
import { AnalysisStatusPanel } from "../features/repository/AnalysisStatusPanel";
import { HandoverReport } from "../features/report/HandoverReport";
import type { AIEnrichmentResponse, AIEnrichmentStatus, AnalysisResults, AnalysisStatusResponse, EvidenceDetail, ProjectAnalysisCreated } from "../types";

interface ReportData {
  results: AnalysisResults;
  enrichment: Pick<AIEnrichmentResponse, "status" | "items">;
  repositoryEvidence: EvidenceDetail | null;
}

const LAST_ANALYSIS_KEY = "baton:last-analysis";

interface SavedSubmission {
  created: ProjectAnalysisCreated;
  repositoryUrl: string;
}

function readSavedSubmission(): SavedSubmission | null {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(LAST_ANALYSIS_KEY) ?? "null");
    if (!saved || typeof saved !== "object") return null;
    const item = saved as Record<string, unknown>;
    if (typeof item.project_id !== "string" || typeof item.analysis_id !== "string" || typeof item.repository_url !== "string") return null;
    const url = new URL(item.repository_url);
    if (url.protocol !== "https:" || url.hostname !== "github.com" || url.username || url.password || !/^\/[A-Za-z0-9-]+\/[A-Za-z0-9_.-]+\/?$/.test(url.pathname)) return null;
    return {
      created: { project_id: item.project_id, analysis_id: item.analysis_id, status: "queued" },
      repositoryUrl: item.repository_url,
    };
  } catch { return null; }
}

export function DashboardPage() {
  const [submission, setSubmission] = useState<SavedSubmission | null>(readSavedSubmission);
  const created = submission?.created ?? null;
  const repositoryUrl = submission?.repositoryUrl ?? "";
  const [analysisStatus, setAnalysisStatus] = useState<AnalysisStatusResponse | null>(null);
  const [report, setReport] = useState<ReportData | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const loadedAnalysis = useRef<string | null>(null);
  const activeAnalysis = useRef<string | null>(submission?.created.analysis_id ?? null);

  const loadReport = useCallback(async (analysis: AnalysisStatusResponse) => {
    if (analysis.status !== "completed" || loadedAnalysis.current === analysis.analysis_id) return;
    loadedAnalysis.current = analysis.analysis_id;
    setReportLoading(true);
    setReportError(null);
    try {
      const results = await getAnalysisResults(analysis.analysis_id);
      if (activeAnalysis.current !== analysis.analysis_id) return;
      const [enrichmentResult, repositoryResult] = await Promise.allSettled([
        getAIEnrichment(analysis.analysis_id),
        (() => {
          const repositoryEvidence = results.evidence_references.find((item) => item.evidence_type === "repository");
          return repositoryEvidence ? getEvidenceDetail(analysis.analysis_id, repositoryEvidence.evidence_id) : Promise.resolve(null);
        })(),
      ]);
      const aiStatus: AIEnrichmentStatus = enrichmentResult.status === "fulfilled"
        ? enrichmentResult.value.status : analysis.ai_enrichment_status ?? "not_started";
      if (activeAnalysis.current !== analysis.analysis_id) return;
      setReport({
        results,
        enrichment: {
          status: aiStatus,
          items: enrichmentResult.status === "fulfilled" ? enrichmentResult.value.items : [],
        },
        repositoryEvidence: repositoryResult.status === "fulfilled" ? repositoryResult.value : null,
      });
    } catch (error) {
      if (activeAnalysis.current === analysis.analysis_id) setReportError(error instanceof Error ? error.message : "Could not load the handover report.");
    } finally {
      if (activeAnalysis.current === analysis.analysis_id) setReportLoading(false);
    }
  }, []);

  const handleCreated = useCallback((result: ProjectAnalysisCreated, submittedUrl: string) => {
    loadedAnalysis.current = null;
    activeAnalysis.current = result.analysis_id;
    const saved = { created: result, repositoryUrl: submittedUrl };
    setSubmission(saved);
    try {
      localStorage.setItem(LAST_ANALYSIS_KEY, JSON.stringify({
        project_id: result.project_id, analysis_id: result.analysis_id, repository_url: submittedUrl,
      }));
    } catch { /* persistence is best effort; the current session remains usable */ }
    setAnalysisStatus(null);
    setReport(null);
    setReportLoading(false);
    setReportError(null);
  }, []);

  const handleStatusUpdate = useCallback((analysis: AnalysisStatusResponse) => {
    setAnalysisStatus(analysis);
    if (analysis.status === "completed") void loadReport(analysis);
  }, [loadReport]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-6 py-16 sm:py-24">
        <section className="max-w-4xl">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">Project knowledge handover</p>
          <h1 className="mt-4 text-4xl font-bold tracking-tight text-white sm:text-5xl">Understand a project before you inherit it.</h1>
          <p className="mt-5 max-w-2xl text-lg leading-8 text-slate-400">
            BATON turns repository evidence into a clear handover for the next developer.
          </p>
          <RepositoryUrlForm onCreated={handleCreated} showStatusPanel={false} />
        </section>
        {created && <AnalysisStatusPanel projectId={created.project_id} analysisId={created.analysis_id} initialStatus={created.status} onStatusUpdate={handleStatusUpdate} />}
        {reportLoading && <section className="mt-8 rounded-xl border border-slate-800 bg-slate-900/60 p-6" role="status" aria-label="Loading handover report"><div className="h-5 w-52 animate-pulse rounded bg-slate-700"/><div className="mt-4 h-24 animate-pulse rounded bg-slate-800"/><p className="mt-4 text-sm text-slate-400">Loading the completed report…</p></section>}
        {reportError && <section className="mt-8 rounded-xl border border-rose-400/30 bg-rose-400/5 p-5" role="alert"><h2 className="font-semibold text-rose-200">Report could not be loaded</h2><p className="mt-2 text-sm text-slate-300">{reportError}</p><button type="button" onClick={() => { if (analysisStatus) { loadedAnalysis.current = null; void loadReport(analysisStatus); } }} className="mt-4 rounded-md border border-rose-300/30 px-3 py-2 text-sm text-rose-100 hover:bg-rose-400/10">Retry loading report</button></section>}
        {report && created && analysisStatus && <HandoverReport results={report.results} enrichment={report.enrichment} analysis={analysisStatus} repositoryUrl={repositoryUrl} repositoryEvidence={report.repositoryEvidence} />}
        {!created && <section className="mt-14 rounded-2xl border border-dashed border-slate-700 bg-slate-900/40 p-8 sm:p-12" aria-labelledby="empty-state-title"><div className="max-w-xl"><p className="text-sm font-semibold text-cyan-300">Start a repository handover</p><h2 id="empty-state-title" className="mt-3 text-2xl font-semibold text-white">Your evidence-backed report will appear here.</h2><p className="mt-3 leading-7 text-slate-400">Submit a public GitHub repository to collect evidence, review project work and decisions, and plan your first two days.</p></div></section>}
      </main>
    </div>
  );
}
