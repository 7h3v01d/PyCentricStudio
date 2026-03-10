# PyCentric Studio

An all-in-one Python project tool built with PyQt5.

## Features

| Tab                  | What it does                                                                                   |
|----------------------|------------------------------------------------------------------------------------------------|
| 📁 **Explorer**      | Multi-file tabbed code editor, syntax highlighting (Python/JS/JSON/HTML/CSS/SQL/Bash), git panel, content search (rg + fallback), run & lint |
| 🗄 **Database**      | SQLite browser with live schema, SQL console (Ctrl+Enter), query history, add/drop rows/columns, CSV export |
| 🏗 **Scaffold**      | Generate project structures from presets or paste your own tree; build to disk or export as zip |
| 🧹 **Cleaner**       | Scan & remove `__pycache__`, `.pyc`, `.egg-info`, `.mypy_cache`, `dist/`, `build/`, and more   |
| 🔧 **File Tree**     | Standalone project file tree view                                                              |
| 🔄 **Base64 Encoder**| Encode/decode text, files or clipboard content to/from Base64                                 |
| 🖼 **ICO Converter** | Convert images (PNG, JPG, etc.) to Windows .ico format (multi-size support)                    |
| 🔍 **Import Mapper** | Scan and remap Python imports (refactoring, vendoring, alias handling)                         |
## Installation

```bash
pip install -r requirements.txt
# or
pip install PyQt5 PyQtWebEngine markdown2
```

## Running

```bash
python -m pycentric
```

Or after installing via pip:
```bash
pycentric
```

## Package Structure

```
pycentric/
├── __init__.py
├── __main__.py           ← entry point
├── application.py        ← QApplication factory + theme
├── mainwindow.py         ← top-level window, wires all panels
│
├── core/
│   ├── types.py          ← Language enum, file-type detection (one place)
│   ├── settings.py       ← QSettings wrapper with typed accessors
│   ├── services/
│   │   ├── filesystem.py ← project stats, content search (no Qt)
│   │   ├── git.py        ← git CLI facade (no Qt)
│   │   ├── venv_service.py
│   │   ├── cleaner.py    ← deletion logic (no Qt)
│   │   └── import_scanner.py ← import analysis for mapper
│   └── utils/
│       ├── threading.py  ← safe BackgroundTask wrapper
│       └── zip_utils.py
│
└── ui/
    ├── common/
    │   └── theme.py      ← all colours, fonts, QSS stylesheet
    └── components/
        ├── editor/
        │   ├── editor_tab.py
        │   ├── highlighter.py
        │   └── find_replace_dlg.py
        ├── explorer/
        │   ├── project_explorer.py   ← tree + search + git panel
        │   ├── editor_panel.py       ← tabs + toolbar + output
        │   └── git_panel.py
        ├── db_viewer/
        │   └── database_viewer.py
        ├── scaffold/
        │   └── scaffold_panel.py
        ├── cleaner/
        │   └── cleaner_panel.py
        ├── file_tree/
        │   └── file_tree_panel.py
        ├── base64_encoder/
        │   └── base64_panel.py
        ├── ico_converter/
        │   └── ico_panel.py
        └── import_mapper/
            └── import_mapper_panel.py
```

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

## Keyboard Shortcuts (Explorer tab)

| Shortcut | Action |
|----------|--------|
| Ctrl+S | Save current file |
| Ctrl+R | Run Python file |
| Ctrl+H | Find & Replace |
| Ctrl+W | Close current tab |
| Ctrl+T | New blank tab |
| Ctrl+Enter | Run SQL query (DB tab) |
