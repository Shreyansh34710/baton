import { API_BASE_URL } from "./config";
import type {
  AIEnrichmentResponse, AnalysisResults, AnalysisStatusResponse,
  EvidenceDetail, ProjectAnalysisCreated,
} from "../types";

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string | { msg?: string }[] };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      return body.detail.map((item) => item.msg ?? "Invalid request").join(" ");
    }
  } catch {
    // Use the status-based fallback below when the body isn't JSON.
  }
  return `Request failed (${response.status}).`;
}

export async function createProject(repositoryUrl: string): Promise<ProjectAnalysisCreated> {
  const response = await fetch(`${API_BASE_URL}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repository_url: repositoryUrl }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as ProjectAnalysisCreated;
}

export async function getAnalysis(analysisId: string): Promise<AnalysisStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/analyses/${encodeURIComponent(analysisId)}`);
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as AnalysisStatusResponse;
}

export async function getAnalysisResults(analysisId: string): Promise<AnalysisResults> {
  const response = await fetch(`${API_BASE_URL}/analyses/${encodeURIComponent(analysisId)}/results`);
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as AnalysisResults;
}

export async function getAIEnrichment(analysisId: string): Promise<AIEnrichmentResponse> {
  const response = await fetch(`${API_BASE_URL}/analyses/${encodeURIComponent(analysisId)}/ai-enrichment`);
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as AIEnrichmentResponse;
}

export async function getEvidenceDetail(analysisId: string, evidenceId: string): Promise<EvidenceDetail> {
  const response = await fetch(
    `${API_BASE_URL}/analyses/${encodeURIComponent(analysisId)}/evidence/${encodeURIComponent(evidenceId)}`,
  );
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as EvidenceDetail;
}
