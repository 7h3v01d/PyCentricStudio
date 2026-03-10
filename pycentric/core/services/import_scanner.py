"""
pycentric.core.services.import_scanner
=======================================
Python import dependency analyser — pure stdlib, no Qt dependency.

Originally: ImportMapper v2.1 by Leon Priest.
Integrated into PyCentric Studio with the following changes:
  • Removed PyQt6/pyvis GUI code (lives in ui/components/import_mapper/)
  • Removed argparse CLI entry point (accessible via pycentric CLI separately)
  • All analysis logic is identical to v2.1
  • Module is fully importable without any Qt installation

Public API
----------
  scanner = ImportScanner("/path/to/project")
  scanner.scan()
  stats   = scanner.project_stats()      # dict with all metrics
  dot     = export_dot(scanner)          # Graphviz DOT string
  html    = build_architecture_html(scanner)   # standalone HTML string
  md      = build_markdown_report(scanner)     # Markdown string

  # pyvis interactive graph (requires: pip install pyvis)
  build_interactive_graph(scanner, "graph.html")
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ── Constants / heuristics ────────────────────────────────────────────────────

_TEST_PATTERNS = re.compile(
    r"(^|[\./])(tests?|test_|_test|conftest|fixtures?)([\./]|$)", re.IGNORECASE
)

_MODULE_TYPE_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"(^|[\./])(domain|model|entity|entities|aggregate)([\./]|$)", re.I), "domain"),
    (re.compile(r"(^|[\./])(infra|infrastructure|adapter|repository|repo|db|database|storage)([\./]|$)", re.I), "infra"),
    (re.compile(r"(^|[\./])(app|application|service|use_case|usecase|handler)([\./]|$)", re.I), "application"),
    (re.compile(r"(^|[\./])(api|routes?|view|controller|presentation|cli|interface)([\./]|$)", re.I), "presentation"),
    (re.compile(r"(^|[\./])(config|settings?|conf|env)([\./]|$)", re.I), "config"),
    (re.compile(r"(^|[\./])(util|utils?|helper|helpers?|common|shared|core)([\./]|$)", re.I), "utils"),
    (re.compile(r"(^|[\./])(script|scripts?|tool|tools?|bin)([\./]|$)", re.I), "scripts"),
]

_SKIP_DIRS: Set[str] = {
    "__pycache__", ".git", ".tox", "node_modules", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "venv",
}

CACHE_FILE = Path.home() / ".importmapper_cache.json"

_LAYER_PALETTE = [
    "#1a6b3c", "#1a4b6b", "#4b1a6b", "#6b3c1a",
    "#6b1a1a", "#1a6b6b", "#3c6b1a", "#6b6b1a",
]

_LAYER_COLORS = [
    ("#1a6b3c", "#27ae60"), ("#1a4b6b", "#2980b9"), ("#4b1a6b", "#8e44ad"),
    ("#6b3c1a", "#d35400"), ("#6b1a1a", "#c0392b"), ("#1a6b6b", "#16a085"),
    ("#3c6b1a", "#27ae60"), ("#6b6b1a", "#f39c12"),
]


# ── Utilities ─────────────────────────────────────────────────────────────────

def to_fqn(project_root: Path, file_path: Path) -> str:
    return ".".join(file_path.relative_to(project_root).with_suffix("").parts)


def resolve_from_import(current_fqn: str, level: int, module: Optional[str]) -> str:
    pkg = current_fqn.split(".")[:-1]
    if level:
        pkg = pkg[: -level + 1] if level > 1 else pkg
    return ".".join([*pkg, module]) if module else ".".join(pkg)


def file_hash(path: Path) -> str:
    try:
        stat = path.stat()
        return hashlib.md5(f"{stat.st_mtime}:{stat.st_size}".encode()).hexdigest()
    except OSError:
        return ""


def classify_module(fqn: str) -> str:
    if _TEST_PATTERNS.search(fqn):
        return "test"
    for pattern, label in _MODULE_TYPE_RULES:
        if pattern.search(fqn):
            return label
    return "general"


def is_test_module(fqn: str) -> bool:
    return classify_module(fqn) == "test"


def strongly_connected_components(graph: Dict[str, set]) -> List[List[str]]:
    """Tarjan's SCC — finds all circular dependency groups."""
    idx_ctr = [0]
    stack, onstack = [], set()
    indices, lowlink, sccs = {}, {}, []

    def dfs(v: str) -> None:
        indices[v] = lowlink[v] = idx_ctr[0]
        idx_ctr[0] += 1
        stack.append(v)
        onstack.add(v)
        for w in graph.get(v, ()):
            if w not in indices:
                dfs(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in onstack:
                lowlink[v] = min(lowlink[v], indices[w])
        if lowlink[v] == indices[v]:
            comp: List[str] = []
            while True:
                w = stack.pop()
                onstack.remove(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                sccs.append(comp)

    for v in list(graph):
        if v not in indices:
            dfs(v)
    return sccs


def topological_layers(graph: Dict[str, set]) -> List[List[str]]:
    """Kahn's algorithm → architectural layers. Cycles land in last bucket."""
    nodes: Set[str] = set(graph)
    for deps in graph.values():
        nodes.update(deps)
    in_deg = {n: 0 for n in nodes}
    for deps in graph.values():
        for d in deps:
            in_deg[d] += 1

    layers: List[List[str]] = []
    visited: Set[str] = set()
    queue = sorted(n for n, d in in_deg.items() if d == 0)
    while queue:
        layers.append(queue)
        visited.update(queue)
        nxt: List[str] = []
        for node in queue:
            for dep in graph.get(node, ()):
                in_deg[dep] -= 1
                if in_deg[dep] == 0 and dep not in visited:
                    nxt.append(dep)
        queue = sorted(set(nxt))
    remaining = sorted(nodes - visited)
    if remaining:
        layers.append(remaining)
    return layers


# ── Cache ─────────────────────────────────────────────────────────────────────

def load_cache() -> Dict[str, Any]:
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_cache(cache: Dict[str, Any]) -> None:
    try:
        CACHE_FILE.write_text(
            json.dumps(cache, indent=2, default=str), encoding="utf-8"
        )
    except Exception:
        pass


def clear_cache() -> None:
    try:
        CACHE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ── Scanner ───────────────────────────────────────────────────────────────────

class ImportScanner:
    """
    Scans a Python project for import dependencies and rich metrics.

    Uses per-file mtime+size hashing for fast incremental re-scans.
    All computation is pure Python — safe to run in a background thread.

    After scan() completes, access results via:
      .module_info   — dict[fqn, metric_dict]
      .project_stats()  — aggregated summary dict
      .find_cycles()    — list of cycle groups
      .build_graph()    — dict[fqn, set[fqn]]
    """

    def __init__(self, project_root: str = "") -> None:
        self.project_root: Optional[Path] = (
            Path(project_root).resolve() if project_root else None
        )
        self.module_info:      Dict[str, Dict[str, Any]] = {}
        self.local_packages:   Set[str] = set()
        self.all_local_modules: Set[str] = set()
        self._cache:           Dict[str, Any] = {}
        self.exclude_tests:    bool = True

    # ── public ────────────────────────────────────────────────────────────────

    def scan(self, cancelled=None) -> None:
        """
        Full (or incremental) scan.  Accepts optional cancelled() callable
        so BackgroundTask can inject cancellation support automatically.
        """
        self.module_info.clear()
        if not self.project_root or not self.project_root.is_dir():
            return

        self._cache = load_cache().get(str(self.project_root), {})
        self._find_local_packages_and_modules()

        for root, dirs, files in os.walk(self.project_root):
            if cancelled and cancelled():
                return
            if "pyvenv.cfg" in files:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]

            for fname in files:
                if not fname.endswith(".py"):
                    continue
                if cancelled and cancelled():
                    return
                path = Path(root) / fname
                fqn  = to_fqn(self.project_root, path)
                h    = file_hash(path)

                if fqn in self._cache and self._cache[fqn].get("_hash") == h:
                    self.module_info[fqn] = dict(self._cache[fqn])
                else:
                    self.module_info[fqn] = {"path": str(path), "imports": [], "_hash": h}
                    self._scan_file(path, fqn)
                    self._cache[fqn] = dict(self.module_info[fqn])

        # Prune stale cache entries
        valid = set(self.module_info)
        self._cache = {k: v for k, v in self._cache.items() if k in valid}
        save_cache({str(self.project_root): self._cache})

        self._categorize_imports()
        self._compute_metrics()

    def build_graph(self, include_tests: bool = True) -> Dict[str, set]:
        return {
            mod: set(d.get("internal_imports", []))
            for mod, d in self.module_info.items()
            if include_tests or not is_test_module(mod)
        }

    def find_cycles(self) -> List[List[str]]:
        return strongly_connected_components(self.build_graph())

    def project_stats(self) -> Dict[str, Any]:
        if not self.module_info:
            return {}
        mods       = list(self.module_info.values())
        cycle_list = self.find_cycles()
        cycles_flat: Set[str] = set()
        for c in cycle_list:
            cycles_flat.update(c)

        ext_ctr: Counter = Counter()
        for d in mods:
            for e in d.get("external_imports", []):
                ext_ctr[e.split(".")[0]] += 1

        total_loc  = sum(d.get("loc", 0) for d in mods)
        avg_health = round(
            sum(d.get("health_score", 0) for d in mods) / max(len(mods), 1), 1
        )

        graph  = self.build_graph(include_tests=False)
        layers = topological_layers(graph)
        layer_map = {mod: i for i, layer in enumerate(layers) for mod in layer}

        violations = []
        for src, deps in graph.items():
            sl = layer_map.get(src, -1)
            for dst in deps:
                dl = layer_map.get(dst, -1)
                if dl >= 0 and sl >= 0 and dl > sl + 1:
                    violations.append((src, dst, sl, dl))

        return {
            "total_modules":    len(self.module_info),
            "total_loc":        total_loc,
            "total_cycles":     len(cycle_list),
            "cycles":           cycle_list,
            "cycle_members":    sorted(cycles_flat),
            "avg_health":       avg_health,
            "most_imported":    sorted(
                self.module_info.items(),
                key=lambda kv: kv[1].get("fan_in", 0), reverse=True
            )[:10],
            "most_complex":     sorted(
                self.module_info.items(),
                key=lambda kv: kv[1].get("complexity", 0), reverse=True
            )[:10],
            "orphan_modules":   [
                f for f, d in self.module_info.items()
                if d.get("fan_in", 0) == 0 and d.get("fan_out", 0) == 0
            ],
            "top_external_deps": ext_ctr.most_common(15),
            "layers":           layers,
            "layer_map":        layer_map,
            "arch_violations":  violations,
            "module_types":     Counter(
                d.get("module_type", "general") for d in mods
            ),
        }

    # ── internals ─────────────────────────────────────────────────────────────

    def _find_local_packages_and_modules(self) -> None:
        self.local_packages.clear()
        self.all_local_modules.clear()
        for root, dirs, files in os.walk(self.project_root):
            if "pyvenv.cfg" in files:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            rel = Path(root).relative_to(self.project_root)
            if "__init__.py" in files:
                self.local_packages.add(".".join(rel.parts))
            for f in files:
                if f.endswith(".py"):
                    self.all_local_modules.add(
                        to_fqn(self.project_root, Path(root) / f)
                    )

    def _scan_file(self, path: Path, fqn: str) -> None:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree   = ast.parse(source, filename=str(path))
        except Exception:
            return

        d     = self.module_info[fqn]
        lines = source.splitlines()
        d["loc"]          = len(lines)
        d["blank_lines"]  = sum(1 for l in lines if not l.strip())
        d["comment_lines"]= sum(1 for l in lines if l.strip().startswith("#"))
        d["module_type"]  = classify_module(fqn)
        d["is_test"]      = d["module_type"] == "test"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    d["imports"].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                d["imports"].append(
                    resolve_from_import(fqn, node.level, node.module)
                )

        d["num_classes"]   = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        d["num_functions"] = sum(
            1 for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        branch_nodes = (
            ast.If, ast.For, ast.While, ast.ExceptHandler,
            ast.With, ast.AsyncFor, ast.AsyncWith, ast.comprehension,
        )
        d["complexity"] = sum(1 for n in ast.walk(tree) if isinstance(n, branch_nodes))

    def _categorize_imports(self) -> None:
        for fqn, d in self.module_info.items():
            internal, external = [], []
            for name in d.get("imports", []):
                root_pkg = name.split(".")[0]
                if name in self.all_local_modules or root_pkg in self.local_packages:
                    internal.append(name)
                else:
                    external.append(name)
            d["internal_imports"] = internal
            d["external_imports"] = external

    def _compute_metrics(self) -> None:
        graph  = self.build_graph()
        fan_in: Dict[str, int] = defaultdict(int)
        for deps in graph.values():
            for dep in deps:
                if dep in self.module_info:
                    fan_in[dep] += 1

        cycles_flat: Set[str] = set()
        for c in self.find_cycles():
            cycles_flat.update(c)

        for fqn, d in self.module_info.items():
            fo = len(d.get("internal_imports", []))
            fi = fan_in.get(fqn, 0)
            d["fan_out"]    = fo
            d["fan_in"]     = fi
            d["instability"] = round(fo / (fi + fo), 2) if (fi + fo) else 0.0
            d["in_cycle"]   = fqn in cycles_flat

            score = 100
            breakdown = []
            if d["in_cycle"]:
                score -= 30
                breakdown.append("Circular dependency: −30")
            inst_pen = round(min(30, d["instability"] * 20))
            if inst_pen:
                score -= inst_pen
                breakdown.append(f"High instability ({d['instability']:.2f}): −{inst_pen}")
            cplx     = d.get("complexity", 0)
            cplx_pen = round(min(20, max(0, cplx - 10) * 0.5))
            if cplx_pen:
                score -= cplx_pen
                breakdown.append(f"Complexity ({cplx} branches): −{cplx_pen}")
            fo_pen = round(min(10, max(0, fo - 8)))
            if fo_pen:
                score -= fo_pen
                breakdown.append(f"High fan-out ({fo}): −{fo_pen}")

            d["health_score"]     = max(0, score)
            d["health_breakdown"] = breakdown or ["No issues detected ✓"]


# ── Graphviz DOT export ───────────────────────────────────────────────────────

def export_dot(scanner: ImportScanner, show_external: bool = False) -> str:
    graph      = scanner.build_graph()
    cycles     = {frozenset(c) for c in scanner.find_cycles()}
    layers     = topological_layers(graph)
    layer_map  = {mod: i for i, layer in enumerate(layers) for mod in layer}

    lines = [
        "digraph imports {",
        '  graph [bgcolor="#1e1e2e" fontcolor=white fontname="Helvetica" splines=ortho];',
        '  node [fontname="Helvetica" fontsize=10 style=filled fontcolor=white];',
        '  edge [color="#888888" arrowsize=0.7];',
        "  rankdir=LR;",
    ]
    all_nodes = set(scanner.module_info)
    if show_external:
        for d in scanner.module_info.values():
            all_nodes.update(d.get("external_imports", []))

    for mod in sorted(all_nodes):
        in_cycle    = any(mod in c for c in cycles)
        is_internal = mod in scanner.module_info
        if in_cycle:
            color, brd = "#c0392b", "#e74c3c"
        elif not is_internal:
            color, brd = "#2c3e7a", "#3498db"
        else:
            color = _LAYER_PALETTE[layer_map.get(mod, 0) % len(_LAYER_PALETTE)]
            brd   = "#aaaaaa"
        fi    = scanner.module_info.get(mod, {}).get("fan_in", 0)
        label = mod.split(".")[-1]
        lines.append(
            f'  "{mod}" [label="{label}" tooltip="{mod}" fillcolor="{color}" '
            f'color="{brd}" penwidth={max(1, min(5, fi))} shape=box];'
        )

    for src, dests in graph.items():
        for dst in dests:
            if dst in scanner.module_info:
                lines.append(f'  "{src}" -> "{dst}";')
    if show_external:
        for src, d in scanner.module_info.items():
            for dst in d.get("external_imports", []):
                lines.append(f'  "{src}" -> "{dst}" [style=dashed color="#3498db"];')
    lines.append("}")
    return "\n".join(lines)


def render_graphviz(dot_str: str, out_path: str) -> bool:
    try:
        subprocess.run(
            ["dot", "-Tpng", "-o", out_path],
            input=dot_str.encode(), check=True, capture_output=True,
        )
        return True
    except Exception:
        return False


# ── Interactive graph (requires pyvis) ───────────────────────────────────────

def build_interactive_graph(
    scanner:          ImportScanner,
    out_html:         str,
    show_external:    bool = True,
    search_filter:    str  = "",
    min_fan_in:       int  = 0,
    hide_tests:       bool = True,
    cluster_packages: bool = True,
) -> None:
    """Requires: pip install pyvis"""
    from pyvis.network import Network  # type: ignore[import]

    cycles_flat: Set[str] = set()
    for c in scanner.find_cycles():
        cycles_flat.update(c)

    layers    = topological_layers(scanner.build_graph())
    layer_map = {mod: i for i, layer in enumerate(layers) for mod in layer}

    net = Network(
        height="100%", width="100%", directed=True,
        bgcolor="#1e1e2e", font_color="#eeeeee", cdn_resources="in_line",
    )
    net.force_atlas_2based(
        gravity=-60, central_gravity=0.005,
        spring_length=150, spring_strength=0.04, damping=0.9,
    )

    def passes(mod: str, d: dict) -> bool:
        if hide_tests and d.get("is_test"):
            return False
        if search_filter and search_filter.lower() not in mod.lower():
            return False
        if d.get("fan_in", 0) < min_fan_in and min_fan_in > 0:
            return False
        if (mod.endswith(".__init__") or mod == "__init__") and not d.get("imports"):
            return False
        return True

    modules_to_show = [
        mod for mod, d in scanner.module_info.items() if passes(mod, d)
    ]
    packages = sorted({mod.split(".")[0] for mod in modules_to_show})
    pkg_hues = {
        pkg: int(i * 360 / max(len(packages), 1))
        for i, pkg in enumerate(packages)
    }

    for mod in modules_to_show:
        d       = scanner.module_info[mod]
        fi, fo  = d.get("fan_in", 0), d.get("fan_out", 0)
        health  = d.get("health_score", 100)
        breakdown = "\n".join(d.get("health_breakdown", []))
        pkg     = mod.split(".")[0]

        if mod in cycles_flat:
            color = {
                "background": "#c0392b", "border": "#e74c3c",
                "highlight": {"background": "#e74c3c", "border": "#ff6b6b"},
            }
        else:
            hue = (
                pkg_hues.get(pkg, 200)
                if cluster_packages
                else int(200 + layer_map.get(mod, 0) * 25) % 360
            )
            color = {
                "background": f"hsl({hue},40%,30%)",
                "border":     f"hsl({hue},60%,55%)",
            }

        size  = max(14, min(50, 14 + fi * 5))
        label = mod.split(".")[-1]
        mtype = d.get("module_type", "general")
        hc    = "#27ae60" if health >= 75 else "#f39c12" if health >= 50 else "#e74c3c"
        title = (
            f"<b style='font-size:14px'>{mod}</b>"
            f"<div style='color:#aaa;font-size:11px'>{mtype} module</div>"
            f"<hr style='border-color:#555;margin:6px 0'>"
            f"📂 <small>{d['path']}</small><br><br>"
            f"<b>Fan-in:</b> {fi} &nbsp; <b>Fan-out:</b> {fo}<br>"
            f"<b>Instability:</b> {d.get('instability', 0):.2f} &nbsp; "
            f"<b>Health:</b> <span style='color:{hc}'>{health}/100</span><br>"
            f"<b>LOC:</b> {d.get('loc', 0)} &nbsp; "
            f"<b>Complexity:</b> {d.get('complexity', 0)}<br>"
            f"<b>Classes:</b> {d.get('num_classes', 0)} &nbsp; "
            f"<b>Functions:</b> {d.get('num_functions', 0)}<br>"
            f"<hr style='border-color:#555;margin:6px 0'>"
            f"<b>Health breakdown:</b><br>"
            f"<small style='color:#ccc'>{breakdown}</small>"
        )
        if d.get("internal_imports"):
            title += (
                f"<br><b>Internal imports:</b> "
                f"<small>{', '.join(d['internal_imports'][:6])}"
            )
            if len(d["internal_imports"]) > 6:
                title += f" +{len(d['internal_imports'])-6} more"
            title += "</small>"
        if d.get("external_imports"):
            title += (
                f"<br><b>External imports:</b> "
                f"<small>{', '.join(d['external_imports'][:6])}"
            )
            if len(d["external_imports"]) > 6:
                title += f" +{len(d['external_imports'])-6} more"
            title += "</small>"

        net.add_node(
            mod, label=label, title=title, color=color, size=size,
            font={"size": 12, "color": "#eeeeee"},
            group=pkg if cluster_packages else None,
        )

    existing = {n["id"] for n in net.nodes}

    for mod in modules_to_show:
        for dep in scanner.module_info[mod].get("internal_imports", []):
            if dep in existing:
                fi_dep = scanner.module_info.get(dep, {}).get("fan_in", 1)
                net.add_edge(
                    mod, dep,
                    width=max(1, min(5, fi_dep)),
                    color={"color": "#7f8c8d", "highlight": "#ecf0f1"},
                )

    if show_external:
        for mod in modules_to_show:
            for dep in scanner.module_info[mod].get("external_imports", []):
                if dep not in existing:
                    net.add_node(
                        dep,
                        label=dep.split(".")[0],
                        title=f"<b>External:</b> {dep}",
                        color={"background": "#1a3a5c", "border": "#2980b9"},
                        size=11,
                        font={"size": 9, "color": "#aaccff"},
                        shape="diamond",
                    )
                    existing.add(dep)
                net.add_edge(
                    mod, dep,
                    dashes=True,
                    color={"color": "#2980b9", "highlight": "#3498db"},
                    width=1,
                )

    Path(out_html).write_bytes(net.generate_html().encode("utf-8"))


# ── Architecture HTML ─────────────────────────────────────────────────────────

def build_architecture_html(scanner: ImportScanner) -> str:
    stats        = scanner.project_stats()
    layers       = stats.get("layers", [])
    cycles_flat  = set(stats.get("cycle_members", []))
    violations   = stats.get("arch_violations", [])
    viol_srcs    = {src for src, *_ in violations}
    project_name = scanner.project_root.name if scanner.project_root else "Project"

    layer_parts = []
    for li, layer_mods in enumerate(layers):
        bg, brd = _LAYER_COLORS[li % len(_LAYER_COLORS)]
        if li == 0:
            lbl = "Foundation (no deps)"
        elif li < len(layers) - 1:
            lbl = f"Layer {li}"
        else:
            lbl = "Entry Points"

        cards = []
        for mod in sorted(layer_mods):
            d        = scanner.module_info.get(mod, {})
            in_cycle = mod in cycles_flat
            in_viol  = mod in viol_srcs
            health   = d.get("health_score", "—")
            short    = mod.split(".")[-1]
            mtype    = d.get("module_type", "")
            card_bg  = "#c0392b" if in_cycle else "#5a3a00" if in_viol else bg
            card_brd = "#e74c3c" if in_cycle else "#f39c12" if in_viol else brd
            badges   = ""
            if in_cycle: badges += '<span class="badge red">⚠ CYCLE</span>'
            if in_viol:  badges += '<span class="badge orange">⚡ VIOLATION</span>'
            breakdown_lines = "\n".join(d.get("health_breakdown", []))
            cards.append(
                f'<div class="mod-card" style="background:{card_bg};border-color:{card_brd};" '
                f'title="{mod}\n\nHealth breakdown:\n{breakdown_lines}">\n'
                f'  <div class="mod-name">{short}</div>\n'
                f'  <div class="mod-fqn">{mod}</div>\n'
                f'  <div class="mod-type">{mtype}</div>\n'
                f'  {badges}\n'
                f'  <div class="mod-stats">'
                f'<span title="fan-in">↓{d.get("fan_in","—")}</span>'
                f'<span title="fan-out">↑{d.get("fan_out","—")}</span>'
                f'<span title="health">❤{health}</span>'
                f'<span title="LOC">📄{d.get("loc","—")}</span>'
                f'</div>\n</div>'
            )

        layer_parts.append(
            f'<div class="layer">\n'
            f'  <div class="layer-label" style="color:{brd}">{lbl}'
            f'<span class="layer-count">{len(layer_mods)} modules</span></div>\n'
            f'  <div class="layer-cards">{"".join(cards)}</div>\n</div>'
        )

    def _rows(items, *keys):
        return "".join(
            "<tr>" + "".join(f"<td>{d.get(k,'')}</td>" for k in keys) + "</tr>"
            for _, d in items
        )

    def _hc(d):
        h = d.get("health_score", 0)
        return "#27ae60" if h >= 75 else "#f39c12" if h >= 50 else "#e74c3c"

    top_import_rows = "".join(
        "<tr><td>" + m + "</td><td>" + str(d.get("fan_in", 0)) + "</td>"
        "<td style='color:" + _hc(d) + "'>"
        + str(d.get("health_score", 0)) + "</td><td>" + str(d.get("module_type", "")) + "</td></tr>"
        for m, d in stats.get("most_imported", [])
    )
    top_complex_rows = "".join(
        f"<tr><td>{m}</td><td>{d.get('complexity',0)}</td>"
        f"<td>{d.get('loc',0)}</td><td>{d.get('num_functions',0)}</td></tr>"
        for m, d in stats.get("most_complex", [])
    )
    ext_rows = "".join(
        f"<tr><td>{p}</td><td>{c}</td></tr>"
        for p, c in stats.get("top_external_deps", [])
    )
    cycle_items = "".join(
        f"<li>{'  →  '.join(c)}</li>" for c in stats.get("cycles", [])
    ) or "<li>✅ None</li>"
    orphan_items = "".join(
        f"<li>{m}</li>" for m in stats.get("orphan_modules", [])
    ) or "<li>✅ None</li>"
    viol_items = "".join(
        f"<li><code>{s}</code> (layer {sl}) → <code>{d}</code> (layer {dl})</li>"
        for s, d, sl, dl in violations[:20]
    ) or "<li>✅ None detected</li>"
    type_rows = "".join(
        f"<tr><td>{t}</td><td>{c}</td></tr>"
        for t, c in sorted(
            stats.get("module_types", {}).items(), key=lambda x: -x[1]
        )
    )

    h  = stats.get("avg_health", 0)
    hc = "#27ae60" if h >= 75 else "#f39c12" if h >= 50 else "#c0392b"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>ImportMapper — {project_name}</title>
<style>
:root{{--bg:#0f0f1a;--sf:#1a1a2e;--sf2:#16213e;--tx:#e0e0e0;--mu:#888;--ac:#4fc3f7}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--tx);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px}}
header{{background:linear-gradient(135deg,#0d1b2a,#1a1a3e);padding:24px 36px;border-bottom:1px solid #2a2a4a;display:flex;justify-content:space-between;align-items:center}}
header h1{{font-size:1.6rem;color:var(--ac)}}
header .sub{{color:var(--mu);font-size:.82rem;margin-top:3px}}
.kpis{{display:flex;gap:12px;flex-wrap:wrap;padding:16px 36px;background:var(--sf);border-bottom:1px solid #2a2a4a}}
.kpi{{background:var(--sf2);border-radius:8px;padding:12px 18px;flex:1;min-width:110px}}
.kpi .v{{font-size:1.8rem;font-weight:700;color:var(--ac)}}
.kpi .l{{font-size:.7rem;color:var(--mu);text-transform:uppercase;letter-spacing:.08em;margin-top:2px}}
main{{padding:28px 36px}}
h2{{font-size:1.1rem;color:var(--ac);margin-bottom:14px;border-bottom:1px solid #2a2a4a;padding-bottom:6px;margin-top:32px}}
h2:first-child{{margin-top:0}}
.layer{{margin-bottom:22px}}
.layer-label{{font-size:.8rem;font-weight:600;text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px;display:flex;align-items:center;gap:8px}}
.layer-count{{background:#2a2a4a;color:var(--mu);font-size:.68rem;padding:2px 7px;border-radius:20px;font-weight:400;text-transform:none;letter-spacing:0}}
.layer-cards{{display:flex;flex-wrap:wrap;gap:8px}}
.mod-card{{border:1px solid;border-radius:7px;padding:9px 12px;min-width:150px;max-width:210px;cursor:default;transition:transform .12s,box-shadow .12s}}
.mod-card:hover{{transform:translateY(-2px);box-shadow:0 5px 18px rgba(0,0,0,.5)}}
.mod-name{{font-weight:700;font-size:.88rem;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.mod-fqn{{font-size:.62rem;color:rgba(255,255,255,.5);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}}
.mod-type{{font-size:.62rem;color:rgba(255,255,255,.4);margin-top:1px;text-transform:uppercase;letter-spacing:.06em}}
.mod-stats{{display:flex;gap:6px;margin-top:7px;font-size:.68rem;color:rgba(255,255,255,.7)}}
.mod-stats span{{background:rgba(0,0,0,.25);padding:1px 5px;border-radius:4px;cursor:help}}
.badge{{font-size:.62rem;padding:2px 5px;border-radius:3px;margin-top:3px;display:inline-block;margin-right:3px}}
.badge.red{{background:#c0392b;color:#fff}}
.badge.orange{{background:#d35400;color:#fff}}
.grids{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}}
.card{{background:var(--sf);border-radius:8px;overflow:hidden}}
.card h3{{padding:12px 16px;font-size:.85rem;color:var(--ac);background:var(--sf2)}}
table{{width:100%;border-collapse:collapse;font-size:.8rem}}
th{{padding:7px 13px;text-align:left;color:var(--mu);font-weight:600;text-transform:uppercase;font-size:.68rem;letter-spacing:.05em;border-bottom:1px solid #2a2a4a}}
td{{padding:6px 13px;border-bottom:1px solid #1a1a2e;font-size:.8rem}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:rgba(255,255,255,.03)}}
ul{{padding-left:18px;font-size:.8rem;color:var(--mu);line-height:1.9}}
ul li code{{color:#aaccff;font-size:.78rem}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
.listcard{{background:var(--sf);border-radius:8px;padding:14px 18px}}
.listcard h3{{font-size:.85rem;color:var(--ac);margin-bottom:8px}}
footer{{text-align:center;padding:20px;color:var(--mu);font-size:.72rem;border-top:1px solid #2a2a4a;margin-top:40px}}
</style></head><body>
<header>
  <div><h1>🗺 ImportMapper — {project_name}</h1><div class="sub">{scanner.project_root}</div></div>
</header>
<div class="kpis">
  <div class="kpi"><div class="v">{stats.get('total_modules',0)}</div><div class="l">Modules</div></div>
  <div class="kpi"><div class="v">{stats.get('total_loc',0):,}</div><div class="l">Lines of Code</div></div>
  <div class="kpi"><div class="v">{len(layers)}</div><div class="l">Arch Layers</div></div>
  <div class="kpi"><div class="v">{stats.get('total_cycles',0)}</div><div class="l">Cycle Groups</div></div>
  <div class="kpi"><div class="v" style="color:{hc}">{h}</div><div class="l">Avg Health /100</div></div>
  <div class="kpi"><div class="v">{len(stats.get('orphan_modules',[]))}</div><div class="l">Orphans</div></div>
  <div class="kpi"><div class="v">{len(violations)}</div><div class="l">Layer Violations</div></div>
  <div class="kpi"><div class="v">{len(stats.get('top_external_deps',[]))}</div><div class="l">Ext Packages</div></div>
</div>
<main>
<h2>🏗 Architectural Layer View</h2>
<p style="color:#666;font-size:.78rem;margin-bottom:16px">Layer 0 = foundation (no internal deps). Hover cards for health breakdown. ↓=fan-in ↑=fan-out ❤=health 📄=LOC</p>
{"".join(layer_parts)}

<h2>📊 Key Metrics</h2>
<div class="grids">
  <div class="card"><h3>🔥 Hotspots (Most Imported)</h3><table><tr><th>Module</th><th>Fan-in</th><th>Health</th><th>Type</th></tr>{top_import_rows}</table></div>
  <div class="card"><h3>🧠 Most Complex</h3><table><tr><th>Module</th><th>Complexity</th><th>LOC</th><th>Functions</th></tr>{top_complex_rows}</table></div>
  <div class="card"><h3>📦 External Dependencies</h3><table><tr><th>Package</th><th>Imports</th></tr>{ext_rows}</table></div>
  <div class="card"><h3>🏷 Module Types</h3><table><tr><th>Type</th><th>Count</th></tr>{type_rows}</table></div>
</div>

<h2>⚠ Issues</h2>
<div class="two-col">
  <div class="listcard"><h3>🔄 Circular Dependencies</h3><ul>{cycle_items}</ul></div>
  <div class="listcard"><h3>⚡ Layer Violations</h3><ul>{viol_items}</ul></div>
</div>
<div class="two-col" style="margin-top:20px">
  <div class="listcard"><h3>🏝 Orphan Modules</h3><ul>{orphan_items}</ul></div>
</div>
</main>
<footer>Generated by ImportMapper v2.1 • Integrated into PyCentric Studio • {project_name}</footer>
</body></html>"""


# ── Markdown report ───────────────────────────────────────────────────────────

def build_markdown_report(scanner: ImportScanner) -> str:
    s  = scanner.project_stats()
    pn = scanner.project_root.name if scanner.project_root else "Project"
    lines = [
        f"# ImportMapper Report — {pn}\n",
        f"**Path:** `{scanner.project_root}`\n",
        "## Summary\n",
        "| Metric | Value |", "|--------|-------|",
        f"| Modules | {s.get('total_modules', 0)} |",
        f"| LOC | {s.get('total_loc', 0):,} |",
        f"| Arch Layers | {len(s.get('layers', []))} |",
        f"| Cycle Groups | {s.get('total_cycles', 0)} |",
        f"| Layer Violations | {len(s.get('arch_violations', []))} |",
        f"| Avg Health | {s.get('avg_health', 0)}/100 |",
        f"| Orphans | {len(s.get('orphan_modules', []))} |\n",
        "## Hotspots\n",
        "| Module | Fan-in | Fan-out | Health | Type |",
        "|--------|--------|---------|--------|------|",
    ]
    for m, d in s.get("most_imported", []):
        lines.append(
            f"| `{m}` | {d.get('fan_in',0)} | {d.get('fan_out',0)} "
            f"| {d.get('health_score',0)} | {d.get('module_type','')} |"
        )
    lines += [
        "\n## Most Complex\n",
        "| Module | Complexity | LOC | Classes | Functions |",
        "|--------|-----------|-----|---------|-----------|",
    ]
    for m, d in s.get("most_complex", []):
        lines.append(
            f"| `{m}` | {d.get('complexity',0)} | {d.get('loc',0)} "
            f"| {d.get('num_classes',0)} | {d.get('num_functions',0)} |"
        )
    lines += ["\n## Circular Dependencies\n"]
    for c in s.get("cycles", []):
        lines.append("- `" + "` → `".join(c) + "`")
    if not s.get("cycles"):
        lines.append("✅ None")
    lines += ["\n## Architecture Violations\n"]
    for src, dst, sl, dl in s.get("arch_violations", []):
        lines.append(f"- `{src}` (layer {sl}) → `{dst}` (layer {dl})")
    if not s.get("arch_violations"):
        lines.append("✅ None")
    lines += ["\n## Orphan Modules\n"]
    for m in s.get("orphan_modules", []):
        lines.append(f"- `{m}`")
    if not s.get("orphan_modules"):
        lines.append("✅ None")
    lines += ["\n## External Dependencies\n", "| Package | Count |", "|---------|-------|"]
    for p, c in s.get("top_external_deps", []):
        lines.append(f"| `{p}` | {c} |")
    return "\n".join(lines)
