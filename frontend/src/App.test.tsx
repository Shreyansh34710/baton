import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("BATON project lifecycle", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    localStorage.clear();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the Milestone 1 dashboard and submits a repository successfully", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ project_id: "project-1", analysis_id: "analysis-1", status: "queued" }, 201))
      .mockResolvedValueOnce(jsonResponse({
        project_id: "project-1", analysis_id: "analysis-1", status: "running",
        progress: 96, current_stage: "Analyzing repository evidence", created_at: "2026-01-01T00:00:00",
        updated_at: "2026-01-01T00:00:01", started_at: "2026-01-01T00:00:01",
        completed_at: null, error_details: null,
        ai_enrichment_status: "running", ai_enrichment_progress: 25, ai_enrichment_error: null,
      }));
    render(<App />);

    expect(screen.getByRole("heading", { name: /understand a project/i })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/public github repository url/i), {
      target: { value: "https://github.com/example/project" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analyze repository/i }));

    expect(await screen.findByText("analysis-1")).toBeInTheDocument();
    expect(await screen.findByText("Analyzing repository evidence")).toBeInTheDocument();
    expect(await screen.findByText("AI enrichment: Running")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /AI enrichment progress/i })).toHaveAttribute("value", "25");
    expect(screen.getByRole("progressbar", { name: /analysis progress/i })).toHaveAttribute("value", "96");
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8000/api/v1/projects");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      repository_url: "https://github.com/example/project",
    });
  });

  it("shows backend validation errors when project creation fails", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      detail: [{ msg: "Use a GitHub repository URL like https://github.com/owner/repository." }],
    }, 422));
    render(<App />);
    fireEvent.change(screen.getByLabelText(/public github repository url/i), {
      target: { value: "https://example.com/owner/project" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analyze repository/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/GitHub repository URL/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows failed analysis status and its error details", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ project_id: "project-2", analysis_id: "analysis-2", status: "queued" }, 201))
      .mockResolvedValueOnce(jsonResponse({
        project_id: "project-2", analysis_id: "analysis-2", status: "failed",
        progress: 45, current_stage: "Analysis failed",
        created_at: "2026-01-01T00:00:00", updated_at: "2026-01-01T00:00:01",
        started_at: "2026-01-01T00:00:01", completed_at: "2026-01-01T00:00:02",
        error_details: { code: "github_rate_limited", message: "GitHub's public API rate limit was reached. Please retry later." },
        ai_enrichment_status: "not_started", ai_enrichment_progress: 0, ai_enrichment_error: null,
      }));
    render(<App />);
    fireEvent.change(screen.getByLabelText(/public github repository url/i), {
      target: { value: "https://github.com/example/project" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analyze repository/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/GitHub's public API rate limit was reached/);
    expect(screen.getByText("Failed")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("shows partial completion when deterministic analysis succeeds but Ollama fails", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ project_id: "project-3", analysis_id: "analysis-3", status: "queued" }, 201))
      .mockResolvedValueOnce(jsonResponse({
        project_id: "project-3", analysis_id: "analysis-3", status: "completed",
        progress: 100, current_stage: "Deterministic analysis complete; AI unavailable",
        created_at: "2026-01-01T00:00:00", updated_at: "2026-01-01T00:00:01",
        started_at: "2026-01-01T00:00:01", completed_at: "2026-01-01T00:00:02",
        error_details: null, ai_enrichment_status: "failed", ai_enrichment_progress: 25,
        ai_enrichment_error: { code: "ollama_unavailable", message: "The local Ollama service is unavailable. Deterministic results are still available." },
      }));
    render(<App />);
    fireEvent.change(screen.getByLabelText(/public github repository url/i), {
      target: { value: "https://github.com/example/project" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analyze repository/i }));

    expect(await screen.findByText("AI enrichment: Unavailable")).toBeInTheDocument();
    expect(await screen.findByText(/Deterministic analysis is ready; AI enrichment is partial or unavailable/)).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("loads the actual deterministic report and enrichment after analysis completes", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ project_id: "project-report", analysis_id: "analysis-report", status: "queued" }, 201))
      .mockResolvedValueOnce(jsonResponse({
        project_id: "project-report", analysis_id: "analysis-report", status: "completed",
        progress: 100, current_stage: "Analysis complete", created_at: "2026-01-01T00:00:00",
        updated_at: "2026-01-01T00:00:01", started_at: "2026-01-01T00:00:01",
        completed_at: "2026-01-01T00:00:02", error_details: null,
        ai_enrichment_status: "failed", ai_enrichment_progress: 100,
        ai_enrichment_error: { code: "ollama_unavailable", message: "Local model unavailable." },
      }))
      .mockResolvedValueOnce(jsonResponse({
        analysis_id: "analysis-report", project_id: "project-report",
        findings: [{ finding_id: "finding-1", category: "overview", title: "Purpose", description: "Actual persisted finding.", claim_type: "inference", evidence_status: "partially_verified", confidence: 0.6, evidence_ids: [], recommended_next_action: null }],
        evidence_references: [{ evidence_id: "repo-1", evidence_type: "repository", source_identifier: "repository", source_url: "https://github.com/octo/project", retrieved_at: "2026-01-01T00:00:00Z", repository_commit_sha: null }],
        first_48_hours_plan: [],
      }))
      .mockResolvedValueOnce(jsonResponse({ analysis_id: "analysis-report", status: "failed", progress: 100, items: [], rejected_item_count: 0, error_details: null }))
      .mockResolvedValueOnce(jsonResponse({ evidence_id: "repo-1", evidence_type: "repository", source_identifier: "repository", source_url: "https://github.com/octo/project", retrieved_at: "2026-01-01T00:00:00Z", repository_commit_sha: null, content: JSON.stringify({ full_name: "octo/project", description: "Loaded from stored GitHub metadata", default_branch: "main" }), related_finding_ids: [] }));

    render(<App />);
    fireEvent.change(screen.getByLabelText(/public github repository url/i), { target: { value: "https://github.com/octo/project" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze repository/i }));

    expect(await screen.findByTestId("handover-report")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "octo/project" })).toBeInTheDocument();
    expect(screen.getByText("Loaded from stored GitHub metadata")).toBeInTheDocument();
    expect(screen.getAllByText("Actual persisted finding.")).toHaveLength(1);
    expect(screen.getByText("AI enrichment: failed")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
  });

  it("shows a recoverable report error when persisted results cannot be fetched", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ project_id: "project-error", analysis_id: "analysis-error", status: "queued" }, 201))
      .mockResolvedValueOnce(jsonResponse({
        project_id: "project-error", analysis_id: "analysis-error", status: "completed",
        progress: 100, current_stage: "Analysis complete", created_at: "2026-01-01T00:00:00",
        updated_at: "2026-01-01T00:00:01", started_at: "2026-01-01T00:00:01",
        completed_at: "2026-01-01T00:00:02", error_details: null,
        ai_enrichment_status: "completed", ai_enrichment_progress: 100, ai_enrichment_error: null,
      }))
      .mockResolvedValueOnce(jsonResponse({ detail: "Analysis results are not available yet." }, 409));
    render(<App />);
    fireEvent.change(screen.getByLabelText(/public github repository url/i), { target: { value: "https://github.com/octo/error" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze repository/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Analysis results are not available yet.");
    expect(screen.getByRole("button", { name: "Retry loading report" })).toBeInTheDocument();
  });

  it("restores the last report after a page refresh without creating another project", async () => {
    localStorage.setItem("baton:last-analysis", JSON.stringify({
      project_id: "project-restored", analysis_id: "analysis-restored",
      repository_url: "https://github.com/octo/restored",
    }));
    fetchMock
      .mockResolvedValueOnce(jsonResponse({
        project_id: "project-restored", analysis_id: "analysis-restored", status: "completed",
        progress: 100, current_stage: "Analysis complete", created_at: "2026-01-01T00:00:00",
        updated_at: "2026-01-01T00:00:01", started_at: "2026-01-01T00:00:01",
        completed_at: "2026-01-01T00:00:02", error_details: null,
        ai_enrichment_status: "failed", ai_enrichment_progress: 100,
        ai_enrichment_error: { code: "ollama_unavailable", message: "Unavailable." },
      }))
      .mockResolvedValueOnce(jsonResponse({
        analysis_id: "analysis-restored", project_id: "project-restored", findings: [],
        evidence_references: [], first_48_hours_plan: [],
      }))
      .mockResolvedValueOnce(jsonResponse({ analysis_id: "analysis-restored", status: "failed", progress: 100, items: [], rejected_item_count: 0, error_details: null }));

    render(<App />);
    expect(await screen.findByTestId("handover-report")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "octo/restored" })).toBeInTheDocument();
    expect(screen.getByText(/No project summary was established/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/projects"))).toBe(false);
  });
});
