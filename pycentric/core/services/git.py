"""
pycentric.core.services.git
============================
Thin facade over the git CLI.  All subprocess calls are here; UI never calls
subprocess directly.
"""

from __future__ import annotations
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitResult:
    command: str
    stdout: str
    stderr: str
    returncode: int

    @property
    def output(self) -> str:
        return (self.stdout + self.stderr).strip()

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class GitService:
    """Run git commands inside *repo_root*."""

    def __init__(self, repo_root: str | Path) -> None:
        self.root = Path(repo_root)

    def _run(self, *args: str, timeout: int = 15) -> GitResult:
        cmd = ["git", *args]
        try:
            r = subprocess.run(
                cmd, cwd=self.root,
                capture_output=True, text=True,
                timeout=timeout,
            )
            return GitResult(
                command=" ".join(cmd),
                stdout=r.stdout,
                stderr=r.stderr,
                returncode=r.returncode,
            )
        except FileNotFoundError:
            return GitResult(" ".join(cmd), "", "git not found in PATH.", 127)
        except subprocess.TimeoutExpired:
            return GitResult(" ".join(cmd), "", "Command timed out.", 124)
        except Exception as e:
            return GitResult(" ".join(cmd), "", str(e), 1)

    def status(self) -> GitResult:
        return self._run("status", "--short")

    def log(self, n: int = 20) -> GitResult:
        return self._run("log", "--oneline", f"-{n}")

    def diff(self) -> GitResult:
        return self._run("diff", "--stat")

    def pull(self) -> GitResult:
        return self._run("pull")

    def add_all(self) -> GitResult:
        return self._run("add", "-A")

    def commit(self, message: str) -> GitResult:
        return self._run("commit", "-m", message)

    def push(self) -> GitResult:
        return self._run("push")

    def is_repo(self) -> bool:
        return (self.root / ".git").exists()
