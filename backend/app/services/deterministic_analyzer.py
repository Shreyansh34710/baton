"""Rule-based, evidence-linked project analysis with no external model calls."""

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Analysis, AnalysisResult, Evidence


CATEGORIES = {
    "overview", "completed", "ongoing", "unfinished", "technical_decision",
    "contributor", "risk", "knowledge_gap",
}
TECHNOLOGIES = {
    ".py": "Python", ".pyi": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust",
    ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".scala": "Scala", ".cs": "C#", ".c": "C",
    ".cpp": "C++", ".sql": "SQL", ".html": "HTML", ".css": "CSS",
}
DECISION_PATTERN = re.compile(
    r"\b(?:we\s+(?:decided|chose)|decision\s*:|the decision is|we will use|"
    r"adopt(?:ing|ed)?|switch(?:ing|ed)? to|migrat(?:ing|ed)? to)\b",
    re.I,
)
INCOMPLETE_PATTERN = re.compile(
    r"\b(?:not implemented|planned|future work|incomplete|currently unsupported|"
    r"work in progress|\bTODO\b|\bFIXME\b)\b",
    re.I,
)
WIP_PATTERN = re.compile(r"\b(?:WIP|work in progress|currently working on|in progress)\b", re.I)
COMPLETION_PATTERN = re.compile(r"\b(?:feat(?:ure)?|add(?:ed)?|implement(?:ed)?|fix(?:ed)?|complete(?:d)?|release(?:d)?)\b", re.I)
DOCUMENTED_CAPABILITY_PATTERN = re.compile(r"\b(?:supports?|provides?|implements?|includes?|offers?)\b", re.I)
RECENT_DAYS = 30
LONG_OPEN_ISSUE_DAYS = 180
OLD_OPEN_PR_DAYS = 30


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(parts).encode("utf-8", "replace")
    return prefix + "_" + hashlib.sha256(raw).hexdigest()[:16]


def _json_content(evidence: Evidence) -> Any:
    try:
        return json.loads(evidence.content)
    except (TypeError, ValueError):
        return None


def _as_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _normalized_date(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def validate_findings(findings: Sequence[Dict[str, Any]], valid_evidence_ids: Iterable[str]) -> List[Dict[str, Any]]:
    """Remove unsupported citations and downgrade claims that lack valid sources."""
    allowed = set(valid_evidence_ids)
    validated: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for original in findings:
        item = dict(original)
        evidence_ids = list(dict.fromkeys(
            evidence_id for evidence_id in item.get("evidence_ids", [])
            if isinstance(evidence_id, str) and evidence_id in allowed
        ))
        item["evidence_ids"] = evidence_ids
        claim_type = item.get("claim_type")
        if claim_type in {"fact", "inference"} and not evidence_ids:
            item["claim_type"] = "unknown"
            item["evidence_status"] = "insufficient"
            item["confidence"] = 0.0
            item["description"] = "The available repository evidence does not establish this claim."
        elif claim_type == "fact":
            item["evidence_status"] = "source_verified"
            item["confidence"] = min(0.95, max(0.5, float(item.get("confidence", 0.8))))
        elif claim_type == "inference":
            item["evidence_status"] = "partially_verified"
            item["confidence"] = min(0.8, max(0.2, float(item.get("confidence", 0.55))))
        else:
            item["claim_type"] = "unknown"
            item["evidence_status"] = "insufficient"
            item["confidence"] = 0.0
            item["evidence_ids"] = evidence_ids
        if item.get("finding_id") not in seen:
            validated.append(item)
            seen.add(item.get("finding_id"))
    return validated


class DeterministicAnalyzer:
    """Analyze only the evidence rows attached to the supplied analysis."""

    def analyze(self, analysis_id: str, db: Session) -> Dict[str, Any]:
        analysis = db.get(Analysis, analysis_id)
        if analysis is None:
            raise ValueError("Analysis not found")
        evidence = db.scalars(
            select(Evidence).where(Evidence.analysis_id == analysis_id)
            .order_by(Evidence.evidence_type, Evidence.source_identifier, Evidence.id)
        ).all()
        valid_ids = {item.id for item in evidence}
        by_type: Dict[str, List[Evidence]] = defaultdict(list)
        for item in evidence:
            by_type[item.evidence_type].append(item)
        as_of = max(
            (_normalized_date(item.retrieved_at) for item in evidence if item.retrieved_at),
            default=datetime(1970, 1, 1, tzinfo=timezone.utc),
        )

        findings: List[Dict[str, Any]] = []

        def add(
            category: str,
            title: str,
            description: str,
            evidence_ids: Sequence[str],
            claim_type: str = "fact",
            confidence: float = 0.9,
            recommended: Optional[str] = None,
        ) -> Dict[str, Any]:
            unique_refs = list(dict.fromkeys(evidence_ids))
            finding = {
                "finding_id": _stable_id("finding", category, title, *unique_refs),
                "category": category,
                "title": title[:180],
                "description": description[:3000],
                "claim_type": claim_type,
                "evidence_status": "source_verified" if claim_type == "fact" else "partially_verified",
                "confidence": confidence,
                "evidence_ids": unique_refs,
                "recommended_next_action": recommended,
            }
            findings.append(finding)
            return finding

        repo_row = next(iter(by_type.get("repository", [])), None)
        repo_data = _json_content(repo_row) if repo_row else None
        if not isinstance(repo_data, dict):
            repo_data = {}
        repo_ids = [repo_row.id] if repo_row else []
        full_name = repo_data.get("full_name") if isinstance(repo_data.get("full_name"), str) else ""
        repository_name = full_name.rsplit("/", 1)[-1] if full_name else analysis.project.repository_url.rstrip("/").rsplit("/", 1)[-1]
        add("overview", "Project name", "The repository is identified as {}.".format(repository_name), repo_ids,
            "fact" if repo_ids else "unknown", 0.93 if repo_ids else 0.0)

        description = repo_data.get("description")
        if isinstance(description, str) and description.strip():
            add("overview", "Repository description", description.strip(), repo_ids, "fact", 0.95)
        else:
            add("overview", "Project description is unavailable",
                "The captured repository metadata does not contain a description.", repo_ids,
                "fact" if repo_ids else "unknown", 0.85 if repo_ids else 0.0,
                "Ask a maintainer to confirm the project's purpose.")

        readme_row = next(iter(by_type.get("readme", [])), None)
        tree_row = next(iter(by_type.get("tree", [])), None)
        tree_data = _json_content(tree_row) if tree_row else None
        tree_entries = (
            tree_data if isinstance(tree_data, list)
            else tree_data.get("entries", []) if isinstance(tree_data, dict) and isinstance(tree_data.get("entries"), list)
            else []
        )
        tree_truncated = isinstance(tree_data, dict) and tree_data.get("truncated") is True
        tree_available = not (isinstance(tree_data, dict) and tree_data.get("available") is False)
        tree_complete = tree_row is not None and isinstance(tree_entries, list) and not tree_truncated and tree_available
        tree_ids = [tree_row.id] if tree_row else []
        if readme_row:
            purpose = self._readme_summary(readme_row.content)
            if purpose:
                add("overview", "Documented project purpose", purpose, [readme_row.id], "inference", 0.62)
            else:
                add("overview", "Project purpose is unclear",
                    "README evidence is present, but its opening text does not establish a concise purpose.",
                    [readme_row.id], "unknown", 0.0,
                    "Ask a maintainer to explain the project's primary user and goal.")
        else:
            readme_in_tree = any(
                isinstance(entry, dict) and isinstance(entry.get("path"), str)
                and "/" not in entry["path"] and entry["path"].lower().startswith("readme")
                for entry in tree_entries
            )
            if tree_complete and not readme_in_tree:
                add("overview", "README not present in captured tree",
                    "The complete captured top-level tree contains no README file.", tree_ids,
                    "fact", 0.9, "Ask a maintainer for project purpose and setup guidance.")
            else:
                add("overview", "Project purpose is not established",
                    "The available evidence does not provide readable README purpose text.",
                    tree_ids, "unknown", 0.0,
                    "Ask a maintainer to explain the project's primary user and goal.")

        technologies = self._technologies(tree_entries)
        if technologies:
            add("overview", "Primary technologies",
                "The captured repository tree contains files indicating: {}. File extensions indicate usage, not architecture or importance.".format(", ".join(technologies)),
                tree_ids, "inference", 0.65)
        elif tree_available:
            add("overview", "Primary technologies are unclear",
                "No recognized language file types appear in the available tree evidence.",
                tree_ids, "unknown", 0.0,
                "Confirm the primary language and runtime with a maintainer.")
        else:
            add("overview", "Primary technologies are unknown",
                "The repository has no default branch, so no file tree was available to identify technologies.",
                tree_ids, "unknown", 0.0,
                "Add an initial commit and confirm the intended language and runtime.")

        issues = [self._item(item) for item in by_type.get("issue", [])]
        pulls = [self._item(item) for item in by_type.get("pull_request", [])]
        commits = [self._item(item) for item in by_type.get("commit", [])]
        recent_commit_rows = [
            (row, data) for row, data in zip(by_type.get("commit", []), commits)
            if self._recent_commit(data, as_of)
        ]
        open_issues = [(row, data) for row, data in zip(by_type.get("issue", []), issues) if data.get("state") == "open"]
        closed_issues = [(row, data) for row, data in zip(by_type.get("issue", []), issues) if data.get("state") == "closed"]
        open_pulls = [(row, data) for row, data in zip(by_type.get("pull_request", []), pulls) if data.get("state") == "open"]
        merged_pulls = [
            (row, data) for row, data in zip(by_type.get("pull_request", []), pulls)
            if data.get("merged_at")
        ]

        activity_refs = [row.id for group in (by_type.get("commit", []), by_type.get("issue", []), by_type.get("pull_request", [])) for row in group]
        if repo_row:
            activity_refs.append(repo_row.id)
        activity_description = "Captured evidence contains {} recent commit records, {} open issues, {} open pull requests.".format(
            len(commits), len(open_issues), len(open_pulls)
        )
        updated_at = _as_datetime(repo_data.get("updated_at"))
        if updated_at:
            activity_description += " Repository metadata reports its last update at {}.".format(updated_at.date().isoformat())
        add("overview", "Repository activity summary", activity_description,
            activity_refs, "fact" if activity_refs else "unknown", 0.9 if activity_refs else 0.0)

        # Completion signals describe recorded events; they do not certify full feature completion.
        for row, data in closed_issues:
            number = data.get("number", row.source_identifier)
            title = str(data.get("title") or "(untitled issue)")
            add("completed", "Issue #{} closed: {}".format(number, title),
                "GitHub records this issue as closed. Closure alone does not establish that the entire requested feature is complete.",
                [row.id], "fact", 0.84)
        for row, data in merged_pulls:
            number = data.get("number", row.source_identifier)
            title = str(data.get("title") or "(untitled pull request)")
            add("completed", "Pull request #{} merged: {}".format(number, title),
                "GitHub records this pull request as merged; this verifies the merge event, not the completeness of a feature.",
                [row.id], "fact", 0.92)
        for row, data in zip(by_type.get("commit", []), commits):
            message = data.get("message")
            if isinstance(message, str) and COMPLETION_PATTERN.search(message.splitlines()[0] if message else ""):
                add("completed", "Recorded change: {}".format(message.splitlines()[0][:140]),
                    "A recent commit records this change. The commit message alone does not prove a feature is complete.",
                    [row.id], "fact", 0.72)
        if readme_row:
            documented = 0
            for line in readme_row.content.splitlines():
                if DOCUMENTED_CAPABILITY_PATTERN.search(line):
                    add("completed", "Documented capability: {}".format(line.strip()[:130]),
                        "The README describes this capability; the documentation statement does not independently verify implementation or completeness.",
                        [readme_row.id], "inference", 0.5,
                        "Confirm the documented capability against current code and tests.")
                    documented += 1
                    if documented >= 5:
                        break

        # Open work is stated as current GitHub status; recency is computed from persisted timestamps.
        for row, data in open_pulls:
            number = data.get("number", row.source_identifier)
            title = str(data.get("title") or "(untitled pull request)")
            add("ongoing", "Open pull request #{}: {}".format(number, title),
                "GitHub reports this pull request as open at evidence retrieval time.", [row.id], "fact", 0.92)
            add("unfinished", "Unmerged pull request #{}: {}".format(number, title),
                "This pull request was open in the captured evidence; its work may be incomplete or awaiting review.",
                [row.id], "inference", 0.64)
            if data.get("draft") is True:
                add("ongoing", "Draft pull request #{}: {}".format(number, title),
                    "GitHub marks this pull request as a draft, which is a direct signal that review is not complete.",
                    [row.id], "fact", 0.9)
        for row, data in open_issues:
            number = data.get("number", row.source_identifier)
            title = str(data.get("title") or "(untitled issue)")
            add("unfinished", "Open issue #{}: {}".format(number, title),
                "GitHub reports this issue as open. An open issue is not automatically a confirmed blocker.",
                [row.id], "fact", 0.9)
            updated = _as_datetime(data.get("updated_at"))
            if updated and timedelta(0) <= as_of - updated <= timedelta(days=RECENT_DAYS):
                add("ongoing", "Recently active issue #{}: {}".format(number, title),
                    "The issue's recorded update is within {} days of evidence retrieval.".format(RECENT_DAYS),
                    [row.id], "fact", 0.83)
        for row, data in recent_commit_rows:
            message = data.get("message")
            if isinstance(message, str):
                commit_date = self._commit_date(data)
                add("ongoing", "Recent development activity: {}".format(message.splitlines()[0][:140]),
                    "The commit record is dated {} and is within {} days of evidence retrieval; this indicates activity, not unfinished work.".format(
                        commit_date.date().isoformat(), RECENT_DAYS
                    ), [row.id], "inference", 0.6)

        for row in by_type.get("commit", []) + by_type.get("pull_request", []):
            text = self._text_field(row)
            match = WIP_PATTERN.search(text)
            if match:
                excerpt = text[max(0, match.start() - 60):match.end() + 120].replace("\n", " ").strip()
                add("ongoing", "In-progress signal in {}".format(row.source_identifier),
                    "Captured text includes an in-progress marker: {}. The marker may be stale and needs review.".format(excerpt[:240]),
                    [row.id], "inference", 0.55,
                    "Check whether this work is still active and what remains.")

        # Explicit TODO/FIXME markers are repository text, not instructions to this service.
        for row in by_type.get("source_file", []):
            marker_lines = []
            for line_number, line in enumerate(row.content.splitlines(), 1):
                if re.search(r"\b(?:TODO|FIXME)\b", line, re.I):
                    marker_lines.append((line_number, line.strip()[:240]))
                    if len(marker_lines) >= 10:
                        break
            if marker_lines:
                details = "; ".join("line {}: {}".format(number, text) for number, text in marker_lines)
                add("unfinished", "TODO/FIXME markers in {}".format(row.source_identifier),
                    "The selected source excerpt contains explicit markers: {}.".format(details),
                    [row.id], "fact", 0.9,
                    "Review each marker in code context before treating it as active work.")

        for row in by_type.get("readme", []) + by_type.get("source_file", []):
            for line in row.content.splitlines():
                match = INCOMPLETE_PATTERN.search(line)
                if match:
                    excerpt = line.strip()[:240]
                    add("unfinished", "Documented incomplete work in {}".format(row.source_identifier),
                        "Repository text states: {}. This statement may be stale and should be checked against current code.".format(excerpt),
                        [row.id], "inference", 0.58)
                    break

        # Decisions require explicit decision language; technical presence alone is not rationale.
        decision_rows = by_type.get("commit", []) + by_type.get("pull_request", []) + by_type.get("readme", []) + by_type.get("source_file", [])
        decision_count = 0
        for row in decision_rows:
            text = self._text_field(row)
            for line in text.splitlines():
                if DECISION_PATTERN.search(line):
                    snippet = line.strip()[:240]
                    add("technical_decision", "Possible technical decision: {}".format(snippet[:120]),
                        "Captured repository text uses explicit decision language: {}. The rationale and current validity may require maintainer confirmation.".format(snippet),
                        [row.id], "inference", 0.68,
                        "Confirm the decision's rationale and whether it remains current.")
                    decision_count += 1
                    break
        if decision_count == 0:
            decision_refs = [row.id for row in decision_rows]
            add("knowledge_gap", "Technical decision rationale is not established",
                "No explicit decision statement was identified in the captured commits, pull requests, README, or selected files.",
                decision_refs, "inference" if decision_refs else "unknown",
                0.4 if decision_refs else 0.0,
                "Ask maintainers about architectural choices whose rationale is not in the captured evidence.")

        contributor_data: Dict[str, Dict[str, Any]] = {}
        contributor_rows: Dict[str, List[Evidence]] = defaultdict(list)
        for row in by_type.get("contributor", []):
            data = _json_content(row)
            if isinstance(data, dict) and isinstance(data.get("login"), str):
                contributor_data[data["login"]] = data
                contributor_rows[data["login"]].append(row)
        for row, data in zip(by_type.get("pull_request", []), pulls):
            login = data.get("user")
            if isinstance(login, str) and login:
                contributor_rows[login].append(row)
        for row, data in zip(by_type.get("commit", []), commits):
            login = data.get("author_login")
            if isinstance(login, str) and login:
                contributor_rows[login].append(row)
        for login in sorted(set(contributor_data) | set(contributor_rows), key=str.lower):
            data = contributor_data.get(login, {})
            refs = [row.id for row in contributor_rows.get(login, [])]
            count = data.get("contributions")
            description_text = "GitHub identifies {} as a contributor".format(login)
            if isinstance(count, int):
                description_text += " with {} reported contributions.".format(count)
            if any(row.evidence_type == "pull_request" for row in contributor_rows.get(login, [])):
                description_text += " Captured pull request evidence also shows recent participation."
            if any(row.evidence_type == "commit" for row in contributor_rows.get(login, [])):
                description_text += " Captured commit evidence also lists this account as an author."
            description_text += " This is an activity signal, not proof of component ownership."
            add("contributor", "Contributor activity: {}".format(login), description_text,
                refs, "fact" if refs else "unknown", 0.88 if refs else 0.0)

        self._add_risks(add, as_of, repo_data, repo_row, open_issues, open_pulls,
                        by_type.get("contributor", []), tree_row, tree_data, tree_entries)
        self._add_knowledge_gaps(add, readme_row, tree_row, tree_data, tree_entries,
                                 open_issues, open_pulls)

        findings = validate_findings(findings, valid_ids)
        findings.sort(key=lambda item: (item["category"], item["title"].lower(), item["finding_id"]))
        finding_ids = {item["finding_id"] for item in findings}
        evidence_map = {item.id: item for item in evidence}
        plan = self._plan(findings, evidence_map)
        for task in plan:
            task["finding_ids"] = [value for value in task["finding_ids"] if value in finding_ids]
            task["evidence_ids"] = [value for value in task["evidence_ids"] if value in valid_ids]

        evidence_references = [
            {
                "evidence_id": item.id,
                "evidence_type": item.evidence_type,
                "source_identifier": item.source_identifier,
                "source_url": item.source_url,
                "retrieved_at": _normalized_date(item.retrieved_at).isoformat() if item.retrieved_at else None,
                "repository_commit_sha": item.repository_commit_sha,
            }
            for item in evidence
        ]
        return {
            "analysis_id": analysis.id,
            "project_id": analysis.project_id,
            "findings": findings,
            "evidence_references": evidence_references,
            "first_48_hours_plan": plan,
        }

    @staticmethod
    def _item(row: Evidence) -> Dict[str, Any]:
        data = _json_content(row)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _text_field(row: Evidence) -> str:
        if row.evidence_type == "commit":
            data = _json_content(row)
            return data.get("message", "") if isinstance(data, dict) else ""
        data = _json_content(row)
        if isinstance(data, dict):
            return "\n".join(str(data.get(key) or "") for key in ("title", "body"))
        return row.content

    @staticmethod
    def _commit_date(data: Dict[str, Any]) -> Optional[datetime]:
        commit = data.get("commit") if isinstance(data.get("commit"), dict) else {}
        author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
        top_author = data.get("author") if isinstance(data.get("author"), dict) else {}
        return _as_datetime(author.get("date")) or _as_datetime(top_author.get("date")) or _as_datetime(data.get("author_date"))

    @classmethod
    def _recent_commit(cls, data: Dict[str, Any], as_of: datetime) -> bool:
        commit_date = cls._commit_date(data)
        return bool(commit_date and timedelta(0) <= as_of - commit_date <= timedelta(days=RECENT_DAYS))

    @staticmethod
    def _readme_summary(content: str) -> str:
        candidates = []
        fenced = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fenced = not fenced
                continue
            if fenced or not stripped or stripped.startswith("#") or stripped.startswith("<"):
                continue
            if stripped.startswith(("[!", "![", "<img", "<a ")):
                continue
            clean = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", stripped)
            clean = re.sub(r"[`*_]", "", clean)
            candidates.append(clean)
            if len(" ".join(candidates)) >= 500:
                break
        return " ".join(candidates)[:600]

    @staticmethod
    def _technologies(tree_entries: Sequence[Any]) -> List[str]:
        counts: Counter = Counter()
        for entry in tree_entries:
            if not isinstance(entry, dict) or entry.get("type") != "blob":
                continue
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            lowered = path.lower()
            if "/test/" in lowered or "/tests/" in lowered or "/vendor/" in lowered:
                continue
            extension = "." + lowered.rsplit(".", 1)[-1] if "." in lowered.rsplit("/", 1)[-1] else ""
            technology = TECHNOLOGIES.get(extension)
            if technology:
                counts[technology] += 1
        return [name for name, _count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:8]]

    @staticmethod
    def _add_risks(add, as_of, repo_data, repo_row, open_issues, open_pulls,
                   contributor_rows, tree_row, tree_data, tree_entries) -> None:
        for row, data in open_issues:
            created = _as_datetime(data.get("created_at"))
            labels = {str(label).lower() for label in data.get("labels", []) if isinstance(label, str)}
            if created and as_of - created >= timedelta(days=LONG_OPEN_ISSUE_DAYS):
                add("risk", "Long-standing open issue #{}".format(data.get("number", row.source_identifier)),
                    "This issue was open and at least {} days old at evidence retrieval. It may be stale; age does not make it a confirmed blocker.".format(LONG_OPEN_ISSUE_DAYS),
                    [row.id], "inference", 0.64, "Confirm whether the issue remains relevant and assign an owner if needed.")
            if labels.intersection({"blocker", "blocked", "critical"}):
                add("risk", "Open issue carries a blocker-related label: #{}".format(data.get("number", row.source_identifier)),
                    "GitHub labels this open issue as {}. The label is a reported signal and needs maintainer confirmation.".format(", ".join(sorted(labels.intersection({"blocker", "blocked", "critical"})))),
                    [row.id], "inference", 0.7, "Confirm impact, current status, and an owner.")
        for row, data in open_pulls:
            updated = _as_datetime(data.get("updated_at"))
            if updated and as_of - updated >= timedelta(days=OLD_OPEN_PR_DAYS):
                add("risk", "Unresolved pull request #{}".format(data.get("number", row.source_identifier)),
                    "This pull request remained open and had no update for at least {} days at evidence retrieval.".format(OLD_OPEN_PR_DAYS),
                    [row.id], "inference", 0.65, "Check whether the change is still wanted and identify the next reviewer.")
        updated_at = _as_datetime(repo_data.get("updated_at"))
        if repo_row and updated_at and as_of - updated_at >= timedelta(days=180):
            add("risk", "Repository metadata may be stale",
                "The repository's reported last-update date is more than 180 days before evidence retrieval.",
                [repo_row.id], "inference", 0.6, "Confirm whether the project is still actively maintained.")
        contributor_values = []
        for row in contributor_rows:
            data = _json_content(row)
            if isinstance(data, dict) and isinstance(data.get("contributions"), int):
                contributor_values.append((row.id, data["contributions"]))
        total = sum(value for _ref, value in contributor_values)
        if total >= 10 and len(contributor_values) >= 3:
            top_ref, top_count = max(contributor_values, key=lambda pair: pair[1])
            if top_count / total >= 0.8:
                add("risk", "Contribution activity is concentrated",
                    "The highest reported contributor accounts for at least 80% of the captured contributor total. This may indicate continuity risk; it does not establish ownership.",
                    [ref for ref, _count in contributor_values], "inference", 0.62,
                    "Document critical areas and confirm backup maintainers.")
        tree_truncated = isinstance(tree_data, dict) and tree_data.get("truncated") is True
        tree_complete = (
            tree_row is not None and isinstance(tree_entries, list) and not tree_truncated
            and not (isinstance(tree_data, dict) and tree_data.get("available") is False)
        )
        if tree_complete:
            has_tests = any(
                isinstance(entry, dict) and isinstance(entry.get("path"), str)
                and re.search(r"(^|/)(tests?|specs?)(/|$)|\.(test|spec)\.", entry["path"], re.I)
                for entry in tree_entries
            )
            if not has_tests:
                add("risk", "No tests appear in the captured tree",
                    "No common test directory or test/spec filename appears in the captured tree. The tree is capped, so tests may exist outside the captured entries.",
                    [tree_row.id], "inference", 0.48,
                    "Check the full repository for test suites before changing code.")

    @staticmethod
    def _add_knowledge_gaps(add, readme_row, tree_row, tree_data, tree_entries,
                             open_issues, open_pulls) -> None:
        if readme_row:
            has_setup = bool(re.search(r"\b(install|installation|setup|getting started|quick ?start|run locally|usage)\b", readme_row.content, re.I))
            if not has_setup:
                add("knowledge_gap", "Setup instructions are not evident in the README",
                    "The captured README does not contain common setup or run instruction terms; this search is heuristic.",
                    [readme_row.id], "inference", 0.5,
                    "Ask a maintainer for the supported local setup and test commands.")
        entries = [entry for entry in tree_entries if isinstance(entry, dict) and isinstance(entry.get("path"), str)]
        complete = tree_row is not None and isinstance(tree_entries, list) and not (isinstance(tree_data, dict) and (tree_data.get("truncated") is True or tree_data.get("available") is False))
        if not readme_row and tree_row:
            readme_in_tree = any(
                "/" not in entry["path"] and entry["path"].lower().startswith("readme")
                for entry in entries
            )
            if complete and not readme_in_tree:
                add("knowledge_gap", "Project purpose and setup documentation are missing",
                    "The complete captured tree has no top-level README, so purpose and setup cannot be established from README evidence.",
                    [tree_row.id], "inference", 0.7,
                    "Ask a maintainer for project purpose, supported setup, and test commands.")
            else:
                add("knowledge_gap", "README content is unavailable",
                    "The captured evidence does not establish README contents; this may reflect tree truncation or an unreadable/omitted file.",
                    [tree_row.id], "unknown", 0.0,
                    "Ask a maintainer for project purpose and setup instructions.")
        architecture_docs = [entry for entry in entries if re.search(r"(^|/)(architecture|design)(\.|/|$)", entry["path"], re.I)]
        if complete and not architecture_docs:
            add("knowledge_gap", "No architecture document appears in the captured tree",
                "The captured tree does not show a common architecture or design document path.",
                [tree_row.id], "inference", 0.5,
                "Ask maintainers to explain major components and important data flows.")
        if complete:
            unassigned = [(row, data) for row, data in open_issues + open_pulls if not data.get("assignees")]
            if unassigned:
                refs = [row.id for row, _data in unassigned]
                add("knowledge_gap", "Ownership is unclear for open work",
                    "{} captured open issue or pull request records have no listed assignees.".format(len(unassigned)),
                    refs, "inference", 0.58,
                    "Confirm who will own the open work before taking it over.")

    @staticmethod
    def _plan(findings: Sequence[Dict[str, Any]], evidence_map: Dict[str, Evidence]) -> List[Dict[str, Any]]:
        by_category: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for finding in findings:
            by_category[finding["category"]].append(finding)
        candidates = [
            ("first_2_hours", "Review repository purpose and setup", "Start with the captured project overview and verify the documented setup path.",
             by_category["overview"] + by_category["knowledge_gap"], "high"),
            ("first_8_hours", "Reproduce current development and test workflow", "Validate the repository's documented commands and inspect active work before changing code.",
             by_category["ongoing"] + by_category["unfinished"] + [item for item in by_category["risk"] if "tests" in item["title"].lower()], "high"),
            ("first_24_hours", "Review recent changes and confirm completion status", "Compare recorded closures, merges, and commit messages with the current code and tests.",
             by_category["completed"] + by_category["technical_decision"], "medium"),
            ("first_48_hours", "Clarify ownership, risks, and undocumented decisions", "Resolve the highest-impact evidence-backed gaps with maintainers.",
             by_category["risk"] + by_category["knowledge_gap"], "medium"),
        ]
        result = []
        for timeframe, title, reason, related, priority in candidates:
            related = [item for item in related if item.get("evidence_ids")]
            if not related:
                continue
            finding_ids = list(dict.fromkeys(item["finding_id"] for item in related))[:20]
            evidence_ids = list(dict.fromkeys(
                evidence_id for item in related for evidence_id in item["evidence_ids"]
            ))[:50]
            task_id = _stable_id("task", timeframe, title, *finding_ids)
            result.append({
                "task_id": task_id,
                "timeframe": timeframe,
                "title": title,
                "reason": reason,
                "priority": priority,
                "finding_ids": finding_ids,
                "evidence_ids": evidence_ids,
            })
        return result
