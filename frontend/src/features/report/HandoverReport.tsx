import { useEffect, useMemo, useState } from "react";

import type {
  AIEnrichmentItem, AIEnrichmentStatus, AnalysisResults, AnalysisStatusResponse,
  EvidenceDetail, EvidenceReference, Finding, OnboardingTask,
} from "../../types";
import { EvidenceDrawer } from "./EvidenceDrawer";

interface HandoverReportProps {
  results: AnalysisResults;
  enrichment: { status: AIEnrichmentStatus; items: AIEnrichmentItem[] };
  analysis: AnalysisStatusResponse;
  repositoryUrl: string;
  repositoryEvidence: EvidenceDetail | null;
}

const navigation = [
  ["overview", "Overview"], ["understanding", "Project understanding"],
  ["work", "Work status"], ["decisions", "Technical decisions"],
  ["contributors", "Contributors"], ["risks", "Risks & blockers"],
  ["gaps", "Knowledge gaps"], ["plan", "First 48 hours"],
] as const;

const timeframeLabels: Record<OnboardingTask["timeframe"], string> = {
  first_2_hours: "First 2 hours", first_8_hours: "First 8 hours",
  first_24_hours: "First 24 hours", first_48_hours: "First 48 hours",
};

const claimLabels: Record<Finding["claim_type"], string> = {
  fact: "Verified fact", inference: "Deterministic inference", unknown: "Unknown / insufficient",
};

function evidenceStatusLabel(status: Finding["evidence_status"]): string {
  return status === "source_verified" ? "Source verified"
    : status === "partially_verified" ? "Partially supported"
      : status === "insufficient" ? "Insufficient support" : "Not applicable";
}

function GitHubLink({ url, children }: { url: string; children: React.ReactNode }) {
  let safeUrl: string | null = null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:" && parsed.hostname === "github.com") safeUrl = parsed.href;
  } catch { /* malformed source URLs stay plain text */ }
  return safeUrl ? <a href={safeUrl} target="_blank" rel="noopener noreferrer" className="text-cyan-300 underline decoration-cyan-300/40 underline-offset-4 hover:text-cyan-200">{children}</a> : <span>{children}</span>;
}

function Badge({ children, tone = "slate" }: { children: React.ReactNode; tone?: "slate" | "cyan" | "violet" | "amber" }) {
  const styles = {
    slate: "border-slate-700 bg-slate-900 text-slate-300",
    cyan: "border-cyan-400/30 bg-cyan-400/10 text-cyan-200",
    violet: "border-violet-400/30 bg-violet-400/10 text-violet-200",
    amber: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  };
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs ${styles[tone]}`}>{children}</span>;
}

function SectionHeading({ id, eyebrow, children, count }: { id: string; eyebrow: string; children: React.ReactNode; count?: number }) {
  return <div className="mb-5 flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">{eyebrow}</p><h2 id={id} className="mt-2 text-2xl font-semibold tracking-tight text-white">{children}</h2></div>{count !== undefined && <Badge>{count} items</Badge>}</div>;
}

function EvidenceButtons({ ids, references, onSelect }: { ids: string[]; references: Map<string, EvidenceReference>; onSelect: (item: EvidenceReference) => void }) {
  const available = ids.map((id) => references.get(id)).filter((item): item is EvidenceReference => Boolean(item));
  if (!available.length) return <p className="mt-3 text-xs text-slate-500">No linked evidence was recorded.</p>;
  return <div className="mt-3 flex flex-wrap gap-2" aria-label="Supporting evidence">{available.map((item) => <button type="button" key={item.evidence_id} onClick={() => onSelect(item)} className="max-w-full rounded-md border border-slate-700 px-2.5 py-1.5 text-left text-xs text-cyan-200 hover:border-cyan-400/50 hover:bg-slate-800"><span className="font-medium">{item.evidence_type}</span><span className="text-slate-400"> · {item.source_identifier}</span></button>)}</div>;
}

function FindingCard({ finding, references, onEvidence }: { finding: Finding; references: Map<string, EvidenceReference>; onEvidence: (item: EvidenceReference) => void }) {
  const claimLabel = finding.category === "technical_decision"
    ? finding.claim_type === "fact" ? "Explicit in source" : finding.claim_type === "inference" ? "Inferred decision" : "Decision unclear"
    : claimLabels[finding.claim_type];
  return <article className="rounded-xl border border-slate-800 bg-slate-900/70 p-5">
    <div className="flex flex-wrap items-start justify-between gap-3"><h3 className="text-base font-semibold text-white">{finding.title}</h3><div className="flex flex-wrap gap-2"><Badge tone={finding.claim_type === "fact" ? "cyan" : finding.claim_type === "inference" ? "violet" : "amber"}>{claimLabel}</Badge><Badge>{evidenceStatusLabel(finding.evidence_status)}</Badge></div></div>
    <p className="mt-3 whitespace-pre-line text-sm leading-6 text-slate-300">{finding.description}</p>
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400"><span>Confidence {Math.round(finding.confidence * 100)}%</span><span>{finding.claim_type === "fact" ? "Human review status not tracked" : "Human review recommended"}</span></div>
    {finding.recommended_next_action && <p className="mt-3 border-l-2 border-cyan-400/50 pl-3 text-sm text-slate-300"><span className="font-medium text-slate-100">Next:</span> {finding.recommended_next_action}</p>}
    <EvidenceButtons ids={finding.evidence_ids} references={references} onSelect={onEvidence} />
  </article>;
}

function AIItemCard({ item, references, onEvidence }: { item: AIEnrichmentItem; references: Map<string, EvidenceReference>; onEvidence: (item: EvidenceReference) => void }) {
  return <article className="rounded-xl border border-violet-400/20 bg-violet-400/[0.04] p-5">
    <div className="flex flex-wrap items-start justify-between gap-3"><h3 className="text-base font-semibold text-white">{item.title}</h3><div className="flex flex-wrap gap-2"><Badge tone="violet">AI-generated {item.claim_type}</Badge><Badge tone="amber">Needs human review</Badge></div></div>
    <p className="mt-3 whitespace-pre-line text-sm leading-6 text-slate-300">{item.explanation}</p>
    <p className="mt-3 text-xs text-slate-400">Confidence {Math.round(item.confidence * 100)}% · {evidenceStatusLabel(item.evidence_status)}</p>
    {item.recommended_action && <p className="mt-3 border-l-2 border-violet-400/50 pl-3 text-sm text-slate-300"><span className="font-medium text-slate-100">Suggested investigation:</span> {item.recommended_action}</p>}
    <EvidenceButtons ids={item.evidence_ids} references={references} onSelect={onEvidence} />
  </article>;
}

function readRepositoryMetadata(evidence: EvidenceDetail | null): Record<string, unknown> {
  if (!evidence) return {};
  try {
    const parsed: unknown = JSON.parse(evidence.content);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch { return {}; }
}

export function HandoverReport({ results, enrichment, analysis, repositoryUrl, repositoryEvidence }: HandoverReportProps) {
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<Finding["category"] | "all">("all");
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceReference | null>(null);
  const repository = readRepositoryMetadata(repositoryEvidence);
  const references = useMemo(() => new Map(results.evidence_references.map((item) => [item.evidence_id, item])), [results.evidence_references]);
  const metadataFullName = typeof repository.full_name === "string" ? repository.full_name : null;
  const [fallbackOwner = "Unknown owner", fallbackName = "GitHub repository"] = repositoryUrl.replace(/\/$/, "").split("/").slice(-2);
  const repositoryName = metadataFullName ?? `${fallbackOwner}/${fallbackName}`;
  const summary = results.findings.find((item) => item.category === "overview");
  const categoryItems = (category: Finding["category"]) => results.findings.filter((item) => item.category === category);
  const searchMatches = (item: Finding | AIEnrichmentItem) => `${item.title} ${"description" in item ? item.description : item.explanation}`.toLowerCase().includes(query.trim().toLowerCase());
  const filteredFindings = results.findings.filter((item) => searchMatches(item) && (categoryFilter === "all" || item.category === categoryFilter));
  const filteredAI = enrichment.items.filter((item) => searchMatches(item) && (categoryFilter === "all"
    || (categoryFilter === "overview" && item.category === "project_understanding")
    || (categoryFilter === "technical_decision" && item.category === "technical_decision")
    || (categoryFilter === "risk" && item.category === "risk")
    || (categoryFilter === "knowledge_gap" && item.category === "knowledge_gap")
    || (categoryFilter === "completed" || categoryFilter === "ongoing" || categoryFilter === "unfinished") && item.category === "work_status" && item.related_finding_ids.some((id) => results.findings.some((finding) => finding.finding_id === id && finding.category === categoryFilter))));
  const projectAI = filteredAI.filter((item) => item.category === "project_understanding");
  const findingsFor = (category: Finding["category"]) => filteredFindings.filter((item) => item.category === category);
  const aiFor = (category: AIEnrichmentItem["category"]) => filteredAI.filter((item) => item.category === category);
  const aiWorkFor = (category: "completed" | "ongoing" | "unfinished") => aiFor("work_status").filter((item) => item.related_finding_ids.some((id) => results.findings.some((finding) => finding.finding_id === id && finding.category === category)));
  const unclassifiedAIWork = aiFor("work_status").filter((item) => !item.related_finding_ids.some((id) => results.findings.some((finding) => finding.finding_id === id && ["completed", "ongoing", "unfinished"].includes(finding.category))));
  const contributorFindings = categoryItems("contributor");
  const commitEvidence = results.evidence_references.filter((item) => item.evidence_type === "commit");
  const pullRequestEvidence = results.evidence_references.filter((item) => item.evidence_type === "pull_request");
  const sourceFiles = results.evidence_references.filter((item) => item.evidence_type === "source_file");
  const technologyIndicators = [
    ["Python", /\.pyi?$|pyproject\.toml$|requirements\.txt$/i],
    ["TypeScript", /\.tsx?$|tsconfig\.json$/i],
    ["JavaScript", /\.jsx?$|package\.json$/i],
    ["Go", /\.go$|go\.mod$/i], ["Rust", /\.rs$|cargo\.toml$/i],
    ["Java", /\.java$|pom\.xml$|build\.gradle$/i],
    ["C#", /\.cs$|\.csproj$/i], ["Ruby", /\.rb$|gemfile$/i],
  ].filter(([, pattern]) => sourceFiles.some((item) => (pattern as RegExp).test(item.source_identifier))).map(([name]) => name as string);
  const checklistKey = `baton-handover-plan:${results.analysis_id}`;
  const [completedTasks, setCompletedTasks] = useState<string[]>(() => {
    try {
      const stored: unknown = JSON.parse(localStorage.getItem(checklistKey) ?? "[]");
      return Array.isArray(stored) && stored.every((item) => typeof item === "string") ? stored : [];
    } catch { return []; }
  });
  useEffect(() => { try { localStorage.setItem(checklistKey, JSON.stringify(completedTasks)); } catch { /* browser storage may be disabled */ } }, [checklistKey, completedTasks]);

  function toggleTask(taskId: string) {
    setCompletedTasks((current) => current.includes(taskId) ? current.filter((id) => id !== taskId) : [...current, taskId]);
  }

  const metrics = [
    ["Evidence", results.evidence_references.length], ["Findings", results.findings.length + enrichment.items.length],
    ["Risks", categoryItems("risk").length + aiFor("risk").length], ["Contributors", contributorFindings.length],
  ] as const;

  return <div className="mt-10 border-t border-slate-800 pt-8" data-testid="handover-report">
    <div className="grid gap-8 lg:grid-cols-[220px_minmax(0,1fr)]">
      <aside className="lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:self-start">
        <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-500">Report sections</p>
        <nav aria-label="Report sections" className="grid grid-cols-2 gap-1 sm:grid-cols-4 lg:grid-cols-1">{navigation.map(([id, label]) => <a key={id} href={`#report-${id}`} className="rounded-md px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 hover:text-white">{label}</a>)}</nav>
      </aside>

      <div className="min-w-0 space-y-12">
        <section aria-label="Report search and filters" className="rounded-xl border border-slate-800 bg-slate-900/50 p-4"><div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_220px]"><div><label htmlFor="report-search" className="text-sm font-medium text-slate-200">Search report findings</label><input id="report-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search titles and explanations" className="mt-2 min-h-11 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 text-sm text-white placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none"/></div><div><label htmlFor="report-category-filter" className="text-sm font-medium text-slate-200">Filter by category</label><select id="report-category-filter" value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value as Finding["category"] | "all")} className="mt-2 min-h-11 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 text-sm text-white focus:border-cyan-400 focus:outline-none"><option value="all">All categories</option>{(["overview", "completed", "ongoing", "unfinished", "technical_decision", "contributor", "risk", "knowledge_gap"] as const).map((category) => <option key={category} value={category}>{category.replace(/_/g, " ")}</option>)}</select></div></div><p className="mt-2 text-xs text-slate-500">{query || categoryFilter !== "all" ? `${filteredFindings.length + filteredAI.length} matching findings.` : "Search across deterministic findings and AI explanations."}</p></section>
        <section id="report-overview" aria-labelledby="report-overview-heading" className="scroll-mt-6">
          <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Developer handover report</p><h1 id="report-overview-heading" className="mt-2 break-words text-3xl font-semibold tracking-tight text-white">{repositoryName}</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">{typeof repository.description === "string" && repository.description ? repository.description : "No repository description was collected."}</p></div><Badge tone={enrichment.status === "completed" ? "cyan" : enrichment.status === "failed" ? "amber" : "violet"}>AI enrichment: {enrichment.status.replace(/_/g, " ")}</Badge></div>
          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm text-slate-400"><GitHubLink url={repositoryUrl}>Open repository on GitHub ↗</GitHubLink><span>Default branch: <strong className="font-medium text-slate-200">{typeof repository.default_branch === "string" ? repository.default_branch : "Not available"}</strong></span><span>Completed: {analysis.completed_at ? new Date(analysis.completed_at).toLocaleString() : "Not recorded"}</span></div>
          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">{metrics.map(([label, value]) => <div key={label} className="rounded-xl border border-slate-800 bg-slate-900/70 p-4"><p className="text-xs text-slate-400">{label}</p><p className="mt-1 text-2xl font-semibold text-white">{value}</p></div>)}</div>
          <div className="mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-5"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-base font-semibold text-white">Project summary</h2><Badge tone="cyan">Deterministic summary</Badge></div>{summary ? <p className="mt-3 whitespace-pre-line text-sm leading-6 text-slate-300">{summary.description}</p> : <p className="mt-3 text-sm text-slate-400">No project summary was established from the collected evidence.</p>}<div className="mt-3 flex flex-wrap gap-2">{[...new Set(commitEvidence.map((item) => item.repository_commit_sha).filter(Boolean))].slice(0, 3).map((sha) => <Badge key={sha as string}>Commit {String(sha).slice(0, 8)}</Badge>)}</div></div>
          <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="text-sm font-semibold text-white">Technology indicators</h2><p className="mt-1 text-xs text-slate-400">Based on file types in the bounded source-file sample; this is not a dependency inventory.</p>{technologyIndicators.length ? <div className="mt-3 flex flex-wrap gap-2">{technologyIndicators.map((technology) => <Badge key={technology}>{technology}</Badge>)}</div> : <p className="mt-3 text-sm text-slate-400">No primary technology could be identified from the collected source-file paths.</p>}</div>
        </section>

        <section id="report-understanding" aria-labelledby="understanding-heading" className="scroll-mt-6">
          <SectionHeading id="understanding-heading" eyebrow="Context">Project understanding</SectionHeading>
          <div className="space-y-3">{projectAI.length ? projectAI.map((item) => <AIItemCard key={item.enrichment_id} item={item} references={references} onEvidence={setSelectedEvidence} />) : <p className="rounded-xl border border-slate-800 bg-slate-900/50 p-5 text-sm text-slate-400">No AI project explanation is available. The deterministic overview remains above. Technologies and architecture are not inferred without supporting findings.</p>}</div>
        </section>

        <section id="report-work" aria-labelledby="work-heading" className="scroll-mt-6">
          <SectionHeading id="work-heading" eyebrow="Delivery">Work status</SectionHeading>
          <div className="grid gap-6 xl:grid-cols-3">{(["completed", "ongoing", "unfinished"] as const).map((category) => <div key={category}><h3 className="mb-3 text-sm font-semibold capitalize text-slate-200">{category} work</h3><div className="space-y-3">{findingsFor(category).map((item) => <FindingCard key={item.finding_id} finding={item} references={references} onEvidence={setSelectedEvidence} />)}{aiWorkFor(category).map((item) => <AIItemCard key={item.enrichment_id} item={item} references={references} onEvidence={setSelectedEvidence} />)}{!findingsFor(category).length && !aiWorkFor(category).length && <p className="rounded-xl border border-dashed border-slate-800 p-4 text-sm text-slate-500">No {category} work was identified in the captured evidence.</p>}</div></div>)}</div>
          {unclassifiedAIWork.map((item) => <div className="mt-4" key={item.enrichment_id}><p className="mb-2 text-xs font-medium text-amber-200">AI work interpretation; status not classified</p><AIItemCard item={item} references={references} onEvidence={setSelectedEvidence} /></div>)}
        </section>

        <section id="report-decisions" aria-labelledby="decisions-heading" className="scroll-mt-6">
          <SectionHeading id="decisions-heading" eyebrow="Design record" count={findingsFor("technical_decision").length + aiFor("technical_decision").length}>Technical decisions</SectionHeading>
          <div className="space-y-3">{findingsFor("technical_decision").map((item) => <FindingCard key={item.finding_id} finding={item} references={references} onEvidence={setSelectedEvidence} />)}{aiFor("technical_decision").map((item) => <AIItemCard key={item.enrichment_id} item={item} references={references} onEvidence={setSelectedEvidence} />)}{!findingsFor("technical_decision").length && !aiFor("technical_decision").length && <p className="rounded-xl border border-dashed border-slate-800 p-5 text-sm text-slate-400">No technical decisions were recovered. This does not imply that no decisions were made.</p>}</div>
        </section>

        <section id="report-contributors" aria-labelledby="contributors-heading" className="scroll-mt-6">
          <SectionHeading id="contributors-heading" eyebrow="People and activity" count={contributorFindings.length}>Contributor activity</SectionHeading>
          <p className="mb-4 text-sm text-slate-400">Activity signals do not establish formal ownership.</p>
          <div className="space-y-3">{findingsFor("contributor").map((item) => <FindingCard key={item.finding_id} finding={item} references={references} onEvidence={setSelectedEvidence} />)}{!findingsFor("contributor").length && <p className="rounded-xl border border-dashed border-slate-800 p-5 text-sm text-slate-400">No contributor signals were available.</p>}</div>
          <div className="mt-5 rounded-xl border border-slate-800 bg-slate-900/60 p-5"><h3 className="text-sm font-semibold text-white">Recent commit evidence</h3><p className="mt-1 text-xs text-slate-400">{commitEvidence.length} commit records were collected.</p><div className="mt-3 flex flex-wrap gap-2">{commitEvidence.slice(0, 12).map((item) => <button key={item.evidence_id} type="button" onClick={() => setSelectedEvidence(item)} className="rounded-md border border-slate-700 px-2.5 py-1.5 text-xs text-cyan-200 hover:bg-slate-800">{item.source_identifier}</button>)}</div></div>
          <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/60 p-5"><h3 className="text-sm font-semibold text-white">Pull-request evidence</h3><p className="mt-1 text-xs text-slate-400">{pullRequestEvidence.length} pull-request records were collected.</p><div className="mt-3 flex flex-wrap gap-2">{pullRequestEvidence.slice(0, 12).map((item) => <button key={item.evidence_id} type="button" onClick={() => setSelectedEvidence(item)} className="rounded-md border border-slate-700 px-2.5 py-1.5 text-xs text-cyan-200 hover:bg-slate-800">{item.source_identifier}</button>)}</div></div>
        </section>

        <section id="report-risks" aria-labelledby="risks-heading" className="scroll-mt-6">
          <SectionHeading id="risks-heading" eyebrow="Review carefully" count={findingsFor("risk").length + aiFor("risk").length}>Risks and blockers</SectionHeading>
          <div className="space-y-3">{findingsFor("risk").map((item) => <FindingCard key={item.finding_id} finding={item} references={references} onEvidence={setSelectedEvidence} />)}{aiFor("risk").map((item) => <AIItemCard key={item.enrichment_id} item={item} references={references} onEvidence={setSelectedEvidence} />)}{!findingsFor("risk").length && !aiFor("risk").length && <p className="rounded-xl border border-dashed border-slate-800 p-5 text-sm text-slate-400">No risks were identified in the available evidence. This is not a guarantee that the project has no risks.</p>}</div>
        </section>

        <section id="report-gaps" aria-labelledby="gaps-heading" className="scroll-mt-6">
          <SectionHeading id="gaps-heading" eyebrow="What remains unclear" count={findingsFor("knowledge_gap").length + aiFor("knowledge_gap").length}>Knowledge gaps</SectionHeading>
          <div className="space-y-3">{findingsFor("knowledge_gap").map((item) => <FindingCard key={item.finding_id} finding={item} references={references} onEvidence={setSelectedEvidence} />)}{aiFor("knowledge_gap").map((item) => <AIItemCard key={item.enrichment_id} item={item} references={references} onEvidence={setSelectedEvidence} />)}{!findingsFor("knowledge_gap").length && !aiFor("knowledge_gap").length && <p className="rounded-xl border border-dashed border-slate-800 p-5 text-sm text-slate-400">No knowledge gaps were reported.</p>}</div>
        </section>

        <section id="report-plan" aria-labelledby="plan-heading" className="scroll-mt-6">
          <SectionHeading id="plan-heading" eyebrow="Suggested onboarding" count={results.first_48_hours_plan.length}>First-48-Hours Plan</SectionHeading>
          <p className="mb-4 text-xs text-slate-500">Checklist state is saved in this browser only; it is not sent to BATON.</p>
          <div className="space-y-6">{(["first_2_hours", "first_8_hours", "first_24_hours", "first_48_hours"] as const).map((timeframe) => {
            const tasks = results.first_48_hours_plan.filter((task) => task.timeframe === timeframe && `${task.title} ${task.reason}`.toLowerCase().includes(query.trim().toLowerCase()));
            const aiTasks = aiFor("plan").filter((item) => item.plan_task_ids.some((id) => tasks.some((task) => task.task_id === id)));
            return <div key={timeframe}><h3 className="mb-3 text-sm font-semibold text-cyan-200">{timeframeLabels[timeframe]}</h3><div className="space-y-3">{tasks.map((task) => <TaskCard key={task.task_id} task={task} checked={completedTasks.includes(task.task_id)} onToggle={() => toggleTask(task.task_id)} references={references} onEvidence={setSelectedEvidence} />)}{aiTasks.map((item) => <AIItemCard key={item.enrichment_id} item={item} references={references} onEvidence={setSelectedEvidence} />)}{!tasks.length && !aiTasks.length && <p className="rounded-lg border border-dashed border-slate-800 p-4 text-sm text-slate-500">No task was assigned to this interval.</p>}</div></div>;
          })}{aiFor("plan").filter((item) => !item.plan_task_ids.some((id) => results.first_48_hours_plan.some((task) => task.task_id === id))).map((item) => <div key={item.enrichment_id}><p className="mb-2 text-xs font-medium text-amber-200">AI plan suggestion without a linked deterministic task</p><AIItemCard item={item} references={references} onEvidence={setSelectedEvidence} /></div>)}</div>
        </section>
      </div>
    </div>
    <EvidenceDrawer analysisId={results.analysis_id} evidence={selectedEvidence} onClose={() => setSelectedEvidence(null)} />
  </div>;
}

function TaskCard({ task, checked, onToggle, references, onEvidence }: { task: OnboardingTask; checked: boolean; onToggle: () => void; references: Map<string, EvidenceReference>; onEvidence: (item: EvidenceReference) => void }) {
  return <article className={`rounded-xl border p-5 ${checked ? "border-emerald-400/30 bg-emerald-400/[0.04]" : "border-slate-800 bg-slate-900/70"}`}><div className="flex items-start gap-3"><input type="checkbox" checked={checked} onChange={onToggle} aria-label={`Mark ${task.title} complete`} className="mt-1 h-4 w-4 accent-cyan-400"/><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center justify-between gap-2"><h4 className={`font-semibold ${checked ? "text-slate-400 line-through" : "text-white"}`}>{task.title}</h4><Badge tone={task.priority === "high" ? "amber" : "slate"}>{task.priority} priority</Badge></div><p className="mt-2 text-sm leading-6 text-slate-300">{task.reason}</p><EvidenceButtons ids={task.evidence_ids} references={references} onSelect={onEvidence}/>{task.finding_ids.length > 0 && <p className="mt-3 text-xs text-slate-500">Related finding IDs: {task.finding_ids.join(", ")}</p>}</div></div></article>;
}
