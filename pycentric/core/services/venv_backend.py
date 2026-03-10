"""
pycentric.core.services.venv_backend
=====================================
Virtual environment management backend.
Pure Python — no Qt imports. Designed to be called from background threads.

Replaces the original venv_manager_backend.py with:
  - No dependency on pipdeptree or dependency_scanner (optional extras)
  - Dependency tree built via `pip show` (always available)
  - PyPI info via urllib (no aiohttp required)
  - Outdated package detection via `pip list --outdated`
  - PyPI search via JSON API
  - All methods are regular (sync) functions — threading handled by caller
"""

from __future__ import annotations
import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


# ── Directory layout ──────────────────────────────────────────────────────────

BASE_DIR       = Path.home() / ".venv_manager"
ENVS_DIR       = BASE_DIR / "environments"
SNAPSHOTS_DIR  = BASE_DIR / "snapshots"
TEMPLATES_DIR  = BASE_DIR / "templates"

for _d in (BASE_DIR, ENVS_DIR, SNAPSHOTS_DIR, TEMPLATES_DIR):
    _d.mkdir(exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _python_exe(env_name: str) -> str:
    p = ENVS_DIR / env_name
    if os.name == "nt":
        return str(p / "Scripts" / "python.exe")
    return str(p / "bin" / "python")


def _pip_exe(env_name: str) -> str:
    p = ENVS_DIR / env_name
    if os.name == "nt":
        return str(p / "Scripts" / "pip.exe")
    return str(p / "bin" / "pip")


def _run(cmd: list[str], timeout: int = 60, env_name: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _dir_size_mb(path: Path) -> float:
    total = 0
    for dirpath, _, filenames in os.walk(path, onerror=lambda _: None):
        for f in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return round(total / 1_048_576, 2)


# ── Environment CRUD ──────────────────────────────────────────────────────────

def load_environments() -> dict[str, dict]:
    """Scan ENVS_DIR and return a dict of {name: info}."""
    envs: dict[str, dict] = {}
    for env_dir in ENVS_DIR.iterdir():
        if not env_dir.is_dir():
            continue
        name = env_dir.name
        py = _python_exe(name)
        if not Path(py).exists():
            continue
        try:
            ver_r = _run([py, "--version"], timeout=10)
            python_version = (ver_r.stdout or ver_r.stderr).strip()
        except Exception:
            continue
        meta_file = env_dir / "venv_id.json"
        meta = {}
        env_id = None
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
                env_id = meta.get("env_id")
            except Exception:
                pass
        envs[name] = {
            "path":           str(env_dir),
            "python_version": python_version,
            "packages":       get_installed_packages(name),
            "size_mb":        _dir_size_mb(env_dir),
            "env_id":         env_id,
            "metadata":       meta,
        }
    return envs


def create_env(
    name: str,
    python_version: str | None = None,
    template: str | None = None,
    project_name: str = "Unknown",
) -> tuple[bool, str]:
    if (ENVS_DIR / name).exists():
        return False, f"Environment '{name}' already exists."
    cmd = [f"python{python_version}" if python_version else "python", "-m", "venv", str(ENVS_DIR / name)]
    if python_version and not shutil.which(cmd[0]):
        return False, f"Python {python_version} not found in PATH."
    r = _run(cmd, timeout=120)
    if r.returncode != 0:
        return False, f"venv creation failed:\n{r.stderr}"

    env_id = str(uuid.uuid4())
    meta = {
        "env_id":   env_id,
        "created":  datetime.now().isoformat(),
        "project":  project_name,
        "template": template or "None",
    }
    (ENVS_DIR / name / "venv_id.json").write_text(json.dumps(meta, indent=2))

    if template:
        tpl = TEMPLATES_DIR / f"{template}.txt"
        if tpl.exists():
            ok, msg = install_from_requirements(name, str(tpl))
            if not ok:
                return False, f"Template install failed: {msg}"

    log.info(f"create_env: {name} OK")
    return True, f"Environment '{name}' created successfully."


def delete_env(name: str) -> tuple[bool, str]:
    if not (ENVS_DIR / name).exists():
        return False, f"Environment '{name}' does not exist."
    shutil.rmtree(ENVS_DIR / name)
    log.info(f"delete_env: {name} OK")
    return True, f"Environment '{name}' deleted."


def clone_env(src: str, dst: str, project_name: str = "Unknown") -> tuple[bool, str]:
    src_path = ENVS_DIR / src
    dst_path = ENVS_DIR / dst
    if not src_path.exists():
        return False, f"Source '{src}' does not exist."
    if dst_path.exists():
        return False, f"Destination '{dst}' already exists."
    shutil.copytree(src_path, dst_path)
    meta = {
        "env_id":  str(uuid.uuid4()),
        "created": datetime.now().isoformat(),
        "project": project_name,
        "cloned_from": src,
    }
    (dst_path / "venv_id.json").write_text(json.dumps(meta, indent=2))
    log.info(f"clone_env: {src} → {dst} OK")
    return True, f"Cloned '{src}' → '{dst}'."


def check_health(name: str) -> tuple[bool, str]:
    py = _python_exe(name)
    if not Path(py).exists():
        return False, "Python executable missing."
    try:
        r = _run([py, "-c", "import sys; print(sys.version)"], timeout=10)
        if r.returncode == 0:
            return True, r.stdout.strip()
        return False, r.stderr.strip()
    except Exception as e:
        return False, str(e)


def wipe_env(name: str) -> tuple[bool, str]:
    """Uninstall all user packages, keep pip/setuptools/wheel."""
    packages = get_installed_packages(name)
    preserve = {"pip", "setuptools", "wheel"}
    pip = _pip_exe(name)
    to_remove = [p for p in packages if p.lower() not in preserve]
    if not to_remove:
        return True, "Nothing to remove."
    r = _run([pip, "uninstall", "-y"] + to_remove, timeout=300)
    if r.returncode != 0:
        return False, f"Wipe failed:\n{r.stderr}"
    return True, f"Removed {len(to_remove)} packages."


# ── Package operations ────────────────────────────────────────────────────────

def get_installed_packages(name: str) -> dict[str, str]:
    """Return {package_name: version} for all installed packages."""
    pip = _pip_exe(name)
    if not Path(pip).exists():
        return {}
    try:
        r = _run([pip, "list", "--format", "json"], timeout=30)
        return {p["name"]: p["version"] for p in json.loads(r.stdout)}
    except Exception:
        return {}


def install_package(name: str, package: str, version: str = "") -> tuple[bool, str]:
    spec = f"{package}=={version}" if version else package
    pip = _pip_exe(name)
    r = _run([pip, "install", spec], timeout=300)
    if r.returncode == 0:
        return True, f"Installed {spec}.\n{r.stdout}"
    return False, f"Install failed:\n{r.stderr}"


def uninstall_package(name: str, package: str) -> tuple[bool, str]:
    pip = _pip_exe(name)
    r = _run([pip, "uninstall", "-y", package], timeout=120)
    if r.returncode == 0:
        return True, f"Uninstalled {package}."
    return False, f"Uninstall failed:\n{r.stderr}"


def upgrade_package(name: str, package: str) -> tuple[bool, str]:
    pip = _pip_exe(name)
    r = _run([pip, "install", "--upgrade", package], timeout=300)
    if r.returncode == 0:
        return True, f"Upgraded {package}.\n{r.stdout}"
    return False, f"Upgrade failed:\n{r.stderr}"


def upgrade_all(name: str) -> tuple[bool, str]:
    packages = get_installed_packages(name)
    pip = _pip_exe(name)
    # upgrade pip first
    _run([_python_exe(name), "-m", "pip", "install", "--upgrade", "pip"], timeout=120)
    r = _run([pip, "install", "--upgrade"] + list(packages.keys()), timeout=600)
    if r.returncode == 0:
        return True, f"All packages upgraded.\n{r.stdout}"
    return False, f"Upgrade failed:\n{r.stderr}"


def install_from_requirements(name: str, req_file: str) -> tuple[bool, str]:
    if not Path(req_file).exists():
        return False, f"File not found: {req_file}"
    pip = _pip_exe(name)
    r = _run([pip, "install", "-r", req_file], timeout=600)
    if r.returncode == 0:
        return True, f"Installed from {req_file}.\n{r.stdout}"
    return False, f"Install failed:\n{r.stderr}"


def export_requirements(name: str, output_file: str) -> tuple[bool, str]:
    pip = _pip_exe(name)
    r = _run([pip, "freeze"], timeout=60)
    if r.returncode != 0:
        return False, f"Export failed:\n{r.stderr}"
    Path(output_file).write_text(r.stdout, encoding="utf-8")
    return True, f"Requirements exported to {output_file}."


def get_outdated(name: str) -> list[dict]:
    """Return list of {name, version, latest_version} for outdated packages."""
    pip = _pip_exe(name)
    try:
        r = _run([pip, "list", "--outdated", "--format", "json"], timeout=60)
        return json.loads(r.stdout)
    except Exception:
        return []


# ── Dependency tree ───────────────────────────────────────────────────────────

def get_dependency_tree(name: str, package: str) -> dict:
    """
    Return a dependency tree for *package* in *env* using pip show.
    Result: {package: {version, requires: [dep, ...], required_by: [pkg, ...]}}
    """
    pip = _pip_exe(name)

    def _pip_show(pkg: str) -> dict:
        r = _run([pip, "show", pkg], timeout=15)
        info: dict[str, Any] = {}
        for line in r.stdout.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                info[k.strip().lower()] = v.strip()
        return info

    visited: set[str] = set()
    tree: dict[str, Any] = {}

    def _walk(pkg: str, depth: int = 0) -> None:
        if pkg.lower() in visited or depth > 6:
            return
        visited.add(pkg.lower())
        info = _pip_show(pkg)
        if not info:
            return
        requires = [r.strip() for r in info.get("requires", "").split(",") if r.strip()]
        tree[pkg] = {
            "version":     info.get("version", "?"),
            "summary":     info.get("summary", ""),
            "requires":    requires,
            "required_by": [r.strip() for r in info.get("required-by", "").split(",") if r.strip()],
        }
        for dep in requires:
            _walk(dep, depth + 1)

    _walk(package)
    return tree


# ── PyPI ──────────────────────────────────────────────────────────────────────

def get_pypi_info(package: str) -> tuple[bool, dict | str]:
    """Fetch package info from PyPI JSON API. Returns (ok, info_dict or error_str)."""
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PyCentricStudio/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        info = data["info"]
        releases = data.get("releases", {})
        # collect version list newest-first
        versions = sorted(releases.keys(), reverse=True)[:20]
        return True, {
            "name":          info.get("name", package),
            "version":       info.get("version", ""),
            "summary":       info.get("summary", ""),
            "author":        info.get("author", ""),
            "license":       info.get("license", ""),
            "home_page":     info.get("home_page") or info.get("project_url", ""),
            "requires_python": info.get("requires_python", ""),
            "classifiers":   info.get("classifiers", []),
            "versions":      versions,
            "keywords":      info.get("keywords", ""),
            "description":   (info.get("description") or "")[:2000],  # cap length
        }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, f"Package '{package}' not found on PyPI."
        return False, f"PyPI HTTP error {e.code}."
    except urllib.error.URLError as e:
        return False, f"Network error: {e.reason}"
    except Exception as e:
        return False, f"Error: {e}"


def search_pypi(query: str, limit: int = 20) -> tuple[bool, list[dict] | str]:
    """
    Search PyPI using the simple XML-RPC API.
    Returns list of {name, version, summary}.
    """
    import xmlrpc.client
    try:
        client = xmlrpc.client.ServerProxy("https://pypi.org/pypi")
        results = client.search({"name": query, "summary": query}, "or")
        if not isinstance(results, list):
            return False, "No results."
        seen: set[str] = set()
        out = []
        for r in results:
            n = r.get("name", "")
            if n.lower() not in seen:
                seen.add(n.lower())
                out.append({"name": n, "version": r.get("version", ""), "summary": r.get("summary", "")})
            if len(out) >= limit:
                break
        return True, out
    except Exception as e:
        return False, f"Search failed: {e}"


# ── Snapshots ─────────────────────────────────────────────────────────────────

def save_snapshot(name: str) -> tuple[bool, str]:
    """Save a requirements snapshot for the environment."""
    packages = get_installed_packages(name)
    snap = {
        "timestamp": datetime.now().isoformat(),
        "packages":  packages,
    }
    snap_file = SNAPSHOTS_DIR / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    snap_file.write_text(json.dumps(snap, indent=2))
    return True, f"Snapshot saved: {snap_file.name}"


def list_snapshots(name: str) -> list[Path]:
    return sorted(SNAPSHOTS_DIR.glob(f"{name}_*.json"), reverse=True)


# ── Usage log ─────────────────────────────────────────────────────────────────

def log_usage(name: str, project: str = "Unknown") -> None:
    log_file = ENVS_DIR / name / "usage_log.json"
    entry = {"timestamp": datetime.now().isoformat(), "project": project}
    try:
        logs = json.loads(log_file.read_text()) if log_file.exists() else []
        logs.append(entry)
        log_file.write_text(json.dumps(logs, indent=2))
    except Exception as e:
        log.error(f"log_usage: {name}: {e}")


def get_usage_history(name: str) -> list[dict]:
    log_file = ENVS_DIR / name / "usage_log.json"
    if not log_file.exists():
        return []
    try:
        return json.loads(log_file.read_text())
    except Exception:
        return []
