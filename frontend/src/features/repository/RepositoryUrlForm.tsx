import { FormEvent, useState } from "react";

import { createProject } from "../../api/projects";
import type { ProjectAnalysisCreated } from "../../types";
import { AnalysisStatusPanel } from "./AnalysisStatusPanel";

interface RepositoryUrlFormProps {
  onCreated?: (created: ProjectAnalysisCreated, repositoryUrl: string) => void;
  showStatusPanel?: boolean;
}

export function RepositoryUrlForm({ onCreated, showStatusPanel = true }: RepositoryUrlFormProps) {
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [created, setCreated] = useState<ProjectAnalysisCreated | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setCreated(null);
    setIsSubmitting(true);
    try {
      const result = await createProject(repositoryUrl.trim());
      setCreated(result);
      onCreated?.(result, repositoryUrl.trim());
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not create the project.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className="mt-8" onSubmit={handleSubmit} noValidate>
      <label className="mb-2 block text-sm font-medium text-slate-200" htmlFor="repository-url">
        Public GitHub repository URL
      </label>
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          id="repository-url"
          className="min-h-12 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-4 text-slate-100 outline-none placeholder:text-slate-500 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"
          type="url"
          value={repositoryUrl}
          onChange={(event) => setRepositoryUrl(event.target.value)}
          placeholder="https://github.com/owner/repository"
          autoComplete="url"
          required
        />
        <button className="min-h-12 rounded-lg bg-cyan-400 px-5 font-semibold text-slate-950 transition hover:bg-cyan-300 focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-slate-950 disabled:cursor-wait disabled:opacity-60" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Creating project…" : "Analyze repository"}
        </button>
      </div>
      {error && <p className="mt-3 text-sm text-rose-300" role="alert">{error}</p>}
      {showStatusPanel && created && (
        <AnalysisStatusPanel
          projectId={created.project_id}
          analysisId={created.analysis_id}
          initialStatus={created.status}
        />
      )}
    </form>
  );
}
