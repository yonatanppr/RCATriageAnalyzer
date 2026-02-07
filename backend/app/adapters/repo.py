"""Local repository snippet fetcher."""

import subprocess
from pathlib import Path

from app.config import get_settings
from app.utils.hashing import stable_hash


class RepoSnippetFetcher:
    """Fetch lightweight repository snippets with ripgrep search."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def search_snippets(self, repo_local_path: str, keywords: list[str], limit: int = 5) -> list[dict]:
        repo_path = Path(repo_local_path)
        if not repo_path.exists() or not keywords:
            return []

        snippets: list[dict] = []
        for keyword in keywords[:limit]:
            try:
                proc = subprocess.run(
                    ["grep", "-RIn", "--exclude-dir=.git", keyword, str(repo_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError:
                return []

            for line in proc.stdout.splitlines()[:2]:
                parts = line.split(":", 2)
                if len(parts) < 3:
                    continue
                file_path = Path(parts[0])
                line_no = int(parts[1])
                content = self._extract_window(file_path, line_no)
                snippet_id = stable_hash(f"{file_path}:{line_no}:{keyword}")[:12]
                snippets.append(
                    {
                        "type": "repo_snippet",
                        "snippet_id": snippet_id,
                        "file_path": str(file_path),
                        "start_line": max(1, line_no - 10),
                        "end_line": line_no + 10,
                        "content": content,
                        "reason": f"keyword match: {keyword}",
                        "confidence": "low",
                    }
                )
                if len(snippets) >= limit:
                    return snippets
        return snippets

    def _extract_window(self, file_path: Path, line_no: int) -> str:
        try:
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return ""
        start = max(0, line_no - 11)
        end = min(len(lines), line_no + 10)
        return "\n".join(lines[start:end])

    def recent_commits(self, repo_local_path: str, limit: int = 5) -> list[dict]:
        repo_path = Path(repo_local_path)
        if not repo_path.exists():
            return []
        try:
            proc = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_path),
                    "log",
                    f"-n{max(1, limit)}",
                    "--pretty=format:%H|%an|%ad|%s",
                    "--date=iso",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return []

        commits: list[dict] = []
        for line in proc.stdout.splitlines():
            parts = line.split("|", 3)
            if len(parts) != 4:
                continue
            sha, author, date, subject = parts
            commits.append(
                {
                    "commit": sha,
                    "author": author,
                    "date": date,
                    "subject": subject,
                }
            )
        return commits

    def snippet_for_file_line(
        self,
        repo_local_path: str,
        relative_path: str,
        line_no: int,
        *,
        commit_sha: str | None = None,
    ) -> dict | None:
        repo_path = Path(repo_local_path)
        if not repo_path.exists():
            return None
        if commit_sha:
            content = self._extract_window_at_commit(repo_path, relative_path, line_no, commit_sha)
        else:
            file_path = repo_path / relative_path
            if not file_path.exists():
                return None
            content = self._extract_window(file_path, line_no)
        if not content:
            return None
        snippet_id = stable_hash(f"{relative_path}:{line_no}:{commit_sha or 'HEAD'}")[:12]
        return {
            "type": "repo_snippet",
            "snippet_id": snippet_id,
            "file_path": relative_path,
            "start_line": max(1, line_no - 10),
            "end_line": line_no + 10,
            "content": content,
            "reason": "stack-trace mapping",
            "commit_sha": commit_sha,
            "confidence": "high",
        }

    def _extract_window_at_commit(self, repo_path: Path, relative_path: str, line_no: int, commit_sha: str) -> str:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_path), "show", f"{commit_sha}:{relative_path}"],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return ""
        if proc.returncode != 0 or not proc.stdout:
            return ""
        lines = proc.stdout.splitlines()
        start = max(0, line_no - 11)
        end = min(len(lines), line_no + 10)
        return "\n".join(lines[start:end])
