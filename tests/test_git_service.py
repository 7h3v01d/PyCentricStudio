"""Tests for GitService (non-repo path returns graceful errors)."""
import tempfile
from pathlib import Path
from pycentric.core.services.git import GitService


def test_is_repo_false_for_empty_dir():
    with tempfile.TemporaryDirectory() as td:
        svc = GitService(td)
        assert svc.is_repo() is False


def test_status_non_repo_returns_result():
    with tempfile.TemporaryDirectory() as td:
        svc = GitService(td)
        result = svc.status()
        # Should return a result with non-zero exit or an error message, not raise
        assert result is not None
        assert isinstance(result.output, str)


def test_git_service_root():
    with tempfile.TemporaryDirectory() as td:
        svc = GitService(td)
        assert svc.root == Path(td)
