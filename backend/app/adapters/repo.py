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
