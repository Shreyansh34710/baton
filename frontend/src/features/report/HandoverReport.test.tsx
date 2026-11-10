import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getEvidenceDetail } from "../../api/projects";
import type { AIEnrichmentItem, AnalysisResults, AnalysisStatusResponse, EvidenceDetail } from "../../types";
import { HandoverReport } from "./HandoverReport";

vi.mock("../../api/projects", () => ({
  getEvidenceDetail: vi.fn(),
}));

const evidenceReference = {
  evidence_id: "evidence-1", evidence_type: "issue", source_identifier: "12",
  source_url: "https://github.com/acme/widget/issues/12",
  retrieved_at: "2026-05-01T10:00:00Z", repository_commit_sha: "abcdef123456",
};

const categories = ["overview", "completed", "ongoing", "unfinished", "technical_decision", "contributor", "risk", "knowledge_gap"] as const;
const results: AnalysisResults = {
  analysis_id: "analysis-1", project_id: "project-1",
  findings: categories.map((category) => ({
    finding_id: `finding-${category}`, category, title: `${category} finding`,
    description: `Evidence-backed ${category} description.`,
    claim_type: category === "completed" ? "fact" : category === "overview" ? "unknown" : "inference",
    evidence_status: category === "completed" ? "source_verified" : "partially_verified",
    confidence: category === "completed" ? 0.94 : 0.62,
    evidence_ids: ["evidence-1"],
    recommended_next_action: category === "risk" ? "Review the issue." : null,
  })),
  evidence_references: [evidenceReference],
  first_48_hours_plan: [
    { task_id: "task-2h", timeframe: "first_2_hours", title: "Read setup docs", reason: "Understand local setup.", priority: "high", finding_ids: ["finding-overview"], evidence_ids: ["evidence-1"] },
    { task_id: "task-8h", timeframe: "first_8_hours", title: "Run the tests", reason: "Check current behavior.", priority: "medium", finding_ids: [], evidence_ids: [] },
    { task_id: "task-24h", timeframe: "first_24_hours", title: "Trace a feature", reason: "Understand the code path.", priority: "low", finding_ids: [], evidence_ids: [] },
    { task_id: "task-48h", timeframe: "first_48_hours", title: "Review open work", reason: "Pick up an unfinished item.", priority: "medium", finding_ids: [], evidence_ids: [] },
  ],
};

const aiItems: AIEnrichmentItem[] = [
  { enrichment_id: "ai-understanding", category: "project_understanding", title: "Likely project purpose", explanation: "A model-generated explanation for review.", claim_type: "inference", evidence_status: "partially_verified", confidence: 0.6, evidence_ids: ["evidence-1"], related_finding_ids: ["finding-overview"], plan_task_ids: [], recommended_action: null, human_review_status: "needs_review" },
  { enrichment_id: "ai-decision", category: "technical_decision", title: "Possible design choice", explanation: "A model-generated decision inference.", claim_type: "inference", evidence_status: "partially_verified", confidence: 0.55, evidence_ids: ["evidence-1"], related_finding_ids: ["finding-technical_decision"], plan_task_ids: [], recommended_action: "Ask a maintainer.", human_review_status: "needs_review" },
  { enrichment_id: "ai-risk", category: "risk", title: "Potential deployment risk", explanation: "A model-generated risk explanation.", claim_type: "inference", evidence_status: "partially_verified", confidence: 0.5, evidence_ids: ["evidence-1"], related_finding_ids: ["finding-risk"], plan_task_ids: [], recommended_action: "Inspect release configuration.", human_review_status: "needs_review" },
  { enrichment_id: "ai-gap", category: "knowledge_gap", title: "Clarify architecture rationale", explanation: "A model-generated knowledge gap.", claim_type: "unknown", evidence_status: "insufficient", confidence: 0.2, evidence_ids: [], related_finding_ids: [], plan_task_ids: [], recommended_action: null, human_review_status: "needs_review" },
  { enrichment_id: "ai-plan", category: "plan", title: "Map the main flow", explanation: "Add context to the first task.", claim_type: "inference", evidence_status: "partially_verified", confidence: 0.5, evidence_ids: ["evidence-1"], related_finding_ids: [], plan_task_ids: ["task-2h"], recommended_action: null, human_review_status: "needs_review" },
];

const analysis: AnalysisStatusResponse = {
  analysis_id: "analysis-1", project_id: "project-1", status: "completed", progress: 100,
  current_stage: "Analysis complete", created_at: "2026-05-01T09:00:00Z", updated_at: "2026-05-01T10:00:00Z",
  started_at: "2026-05-01T09:01:00Z", completed_at: "2026-05-01T10:00:00Z", error_details: null,
  ai_enrichment_status: "partial", ai_enrichment_progress: 100, ai_enrichment_error: null,
};

const repoDetail: EvidenceDetail = {
  ...evidenceReference, evidence_type: "repository", source_identifier: "repository",
  content: JSON.stringify({ full_name: "acme/widget", description: "A useful widget.", default_branch: "main" }),
  related_finding_ids: [],
};

function renderReport(enrichmentStatus: "partial" | "failed" | "completed" = "partial", items = aiItems) {
  return render(<HandoverReport results={results} enrichment={{ status: enrichmentStatus, items }} analysis={analysis} repositoryUrl="https://github.com/acme/widget" repositoryEvidence={repoDetail} />);
}

describe("complete handover report", () => {
  beforeEach(() => {
    vi.mocked(getEvidenceDetail).mockReset();
    vi.mocked(getEvidenceDetail).mockResolvedValue({ ...evidenceReference, content: "Stored issue content", related_finding_ids: ["finding-risk"] });
  });

  it("renders project overview, metrics, repository information, and deterministic summary", () => {
    renderReport();
    expect(screen.getByRole("heading", { name: "acme/widget" })).toBeInTheDocument();
    expect(screen.getByText("A useful widget.")).toBeInTheDocument();
    expect(screen.getByText("main", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("Evidence").parentElement).toHaveTextContent("1");
    expect(screen.getByText("Risks").parentElement).toHaveTextContent("2");
    expect(screen.getAllByText("Evidence-backed overview description.")).toHaveLength(1);
    expect(screen.getByRole("link", { name: /open repository on github/i })).toHaveAttribute("target", "_blank");
  });

  it("shows work categories, decisions, contributor activity, risks, gaps, and the full timeline", () => {
    renderReport();
    for (const label of ["completed finding", "ongoing finding", "unfinished finding", "technical_decision finding", "contributor finding", "risk finding", "knowledge_gap finding"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("Recent commit evidence")).toBeInTheDocument();
    expect(screen.getByText("First 2 hours")).toBeInTheDocument();
    expect(screen.getByText("First 8 hours")).toBeInTheDocument();
    expect(screen.getByText("First 24 hours")).toBeInTheDocument();
    expect(screen.getAllByText("First 48 hours")).toHaveLength(2);
    expect(screen.getByLabelText("Mark Read setup docs complete")).toBeInTheDocument();
  });

  it("distinguishes AI inferences and human review, and still renders deterministic data when AI is unavailable", () => {
    renderReport("failed", []);
    expect(screen.getByText("AI enrichment: failed")).toBeInTheDocument();
    expect(screen.getByText("completed finding")).toBeInTheDocument();
    expect(screen.getByText(/No AI project explanation is available/)).toBeInTheDocument();
    expect(screen.getByText("Verified fact")).toBeInTheDocument();
  });

  it("opens the evidence drawer with source metadata, content, and related findings", async () => {
    renderReport();
    fireEvent.click(screen.getAllByRole("button", { name: /issue · 12/i })[0]);
    expect(await screen.findByRole("dialog", { name: /12/i })).toBeInTheDocument();
    expect(await screen.findByText("Stored issue content")).toBeInTheDocument();
    expect(screen.getByText("finding-risk", { selector: "li" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /github.com\/acme\/widget\/issues\/12/ })).toHaveAttribute("rel", "noopener noreferrer");
    fireEvent.click(screen.getByRole("button", { name: "Close evidence details" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("stores checklist completion in this browser and uses responsive report layout classes", () => {
    const { container } = renderReport();
    fireEvent.click(screen.getByLabelText("Mark Read setup docs complete"));
    expect(localStorage.getItem("baton-handover-plan:analysis-1")).toContain("task-2h");
    const classes = Array.from(container.querySelectorAll("[class]")).map((element) => String(element.className));
    expect(classes.some((value) => value.includes("lg:grid-cols-[220px_minmax(0,1fr)]"))).toBe(true);
    expect(classes.some((value) => value.includes("sm:grid-cols-4 lg:grid-cols-1"))).toBe(true);
  });

  it("filters findings by a search query", () => {
    renderReport();
    fireEvent.change(screen.getByLabelText("Search report findings"), { target: { value: "unfinished" } });
    expect(screen.getByText("unfinished finding")).toBeInTheDocument();
    expect(screen.queryByText("risk finding")).not.toBeInTheDocument();
  });

  it("filters categories and renders useful empty states", () => {
    const { rerender } = renderReport();
    fireEvent.change(screen.getByLabelText("Filter by category"), { target: { value: "risk" } });
    expect(screen.getByText("risk finding")).toBeInTheDocument();
    expect(screen.queryByText("completed finding")).not.toBeInTheDocument();

    const emptyResults: AnalysisResults = { ...results, findings: [], evidence_references: [], first_48_hours_plan: [] };
    rerender(<HandoverReport results={emptyResults} enrichment={{ status: "failed", items: [] }} analysis={analysis} repositoryUrl="https://github.com/acme/widget" repositoryEvidence={null} />);
    expect(screen.getByText(/No project summary was established/)).toBeInTheDocument();
    expect(screen.getByText(/No technical decisions were recovered/)).toBeInTheDocument();
    expect(screen.getByText(/No contributor signals were available/)).toBeInTheDocument();
    expect(screen.getAllByText(/No task was assigned to this interval/)).toHaveLength(4);
  });

  it("shows a recoverable error if evidence content cannot be loaded", async () => {
    vi.mocked(getEvidenceDetail).mockRejectedValueOnce(new Error("Could not retrieve evidence."));
    renderReport();
    fireEvent.click(screen.getAllByRole("button", { name: /issue · 12/i })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not retrieve evidence.");
  });
});
