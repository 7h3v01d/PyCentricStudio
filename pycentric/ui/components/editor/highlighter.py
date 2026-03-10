"""
pycentric.ui.components.editor.highlighter
==========================================
Multi-language QSyntaxHighlighter using QRegExp rules.
"""

from __future__ import annotations
from PyQt5.QtCore import QRegExp, Qt
from PyQt5.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from pycentric.core.types import Language
from pycentric.ui.common.theme import (
    GREEN, BLUE, YELLOW, ORANGE, RED, PURPLE, CYAN, FG_DIM,
)


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:   f.setFontWeight(QFont.Bold)
    if italic: f.setFontItalic(True)
    return f


def _rules_for(language: Language) -> list[tuple[QRegExp, QTextCharFormat]]:
    rules: list[tuple[QRegExp, QTextCharFormat]] = []

    if language == Language.PYTHON:
        kw = (r'\b(False|None|True|and|as|assert|async|await|break|class|'
              r'continue|def|del|elif|else|except|finally|for|from|global|'
              r'if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|'
              r'try|while|with|yield)\b')
        rules += [
            (QRegExp(kw),            _fmt(PURPLE, bold=True)),
            (QRegExp(r'\bself\b'),   _fmt(BLUE, italic=True)),
            (QRegExp(r'@\w+'),       _fmt(YELLOW)),
            (QRegExp(r'#[^\n]*'),    _fmt(FG_DIM, italic=True)),
            (QRegExp(r'""".*?"""'),  _fmt(ORANGE)),
            (QRegExp(r"'''.*?'''"),  _fmt(ORANGE)),
            (QRegExp(r'"[^"\\]*(\\.[^"\\]*)*"'), _fmt(ORANGE)),
            (QRegExp(r"'[^'\\]*(\\.[^'\\]*)*'"), _fmt(ORANGE)),
            (QRegExp(r'\b\d+\.?\d*\b'), _fmt(GREEN)),
            (QRegExp(r'\b(print|len|range|type|int|str|float|list|dict|set|'
                     r'tuple|open|super|property|isinstance|hasattr|getattr|'
                     r'enumerate|zip|map|filter|sorted|reversed)\b'),
             _fmt(CYAN, italic=True)),
            (QRegExp(r'def\s+\w+'),   _fmt(YELLOW)),
            (QRegExp(r'class\s+\w+'), _fmt(BLUE, bold=True)),
        ]

    elif language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
        kw = (r'\b(break|case|catch|class|const|continue|debugger|default|'
              r'delete|do|else|export|extends|finally|for|function|if|import|'
              r'in|instanceof|let|new|of|return|static|super|switch|throw|try|'
              r'typeof|var|void|while|with|yield|async|await|true|false|null|'
              r'undefined)\b')
        rules += [
            (QRegExp(kw),                        _fmt(PURPLE, bold=True)),
            (QRegExp(r'//[^\n]*'),               _fmt(FG_DIM, italic=True)),
            (QRegExp(r'"[^"\\]*(\\.[^"\\]*)*"'), _fmt(ORANGE)),
            (QRegExp(r"'[^'\\]*(\\.[^'\\]*)*'"), _fmt(ORANGE)),
            (QRegExp(r'`[^`]*`'),                _fmt(ORANGE)),
            (QRegExp(r'\b\d+\.?\d*\b'),          _fmt(GREEN)),
            (QRegExp(r'\b(console|Math|JSON|Promise|Array|Object|String)\b'), _fmt(CYAN)),
            (QRegExp(r'=>'),                     _fmt(PURPLE)),
        ]

    elif language == Language.JSON:
        rules += [
            (QRegExp(r'"[^"\\]*(\\.[^"\\]*)*"\s*:'), _fmt(BLUE)),
            (QRegExp(r':\s*"[^"\\]*(\\.[^"\\]*)*"'), _fmt(ORANGE)),
            (QRegExp(r'\b(true|false|null)\b'),        _fmt(PURPLE, bold=True)),
            (QRegExp(r'\b\d+\.?\d*\b'),                _fmt(GREEN)),
        ]

    elif language == Language.HTML:
        rules += [
            (QRegExp(r'<!--.*?-->'),  _fmt(FG_DIM, italic=True)),
            (QRegExp(r'</?[\w]+'),    _fmt(BLUE)),
            (QRegExp(r'>'),           _fmt(BLUE)),
            (QRegExp(r'"[^"]*"'),     _fmt(ORANGE)),
            (QRegExp(r'&\w+;'),       _fmt(CYAN)),
        ]

    elif language == Language.CSS:
        rules += [
            (QRegExp(r'/\*.*?\*/'),    _fmt(FG_DIM, italic=True)),
            (QRegExp(r'[\w-]+\s*\{'), _fmt(YELLOW)),
            (QRegExp(r'[\w-]+\s*:'),  _fmt(BLUE)),
            (QRegExp(r'#[0-9a-fA-F]{3,8}\b'), _fmt(GREEN)),
            (QRegExp(r'"[^"]*"'),     _fmt(ORANGE)),
        ]

    elif language == Language.SQL:
        kw = (r'\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN|LEFT|RIGHT|'
              r'INNER|OUTER|ON|CREATE|DROP|ALTER|TABLE|INDEX|INTO|VALUES|'
              r'AND|OR|NOT|NULL|IS|AS|ORDER|BY|GROUP|HAVING|LIMIT|OFFSET|'
              r'PRIMARY|KEY|FOREIGN|REFERENCES|UNIQUE|DEFAULT|IF|EXISTS|'
              r'BEGIN|COMMIT|ROLLBACK|PRAGMA|AUTOINCREMENT|TEXT|INTEGER|REAL|BLOB)\b')
        rules += [
            (QRegExp(kw, Qt.CaseInsensitive), _fmt(PURPLE, bold=True)),
            (QRegExp(r'--[^\n]*'),            _fmt(FG_DIM, italic=True)),
            (QRegExp(r"'[^']*'"),             _fmt(ORANGE)),
            (QRegExp(r'\b\d+\.?\d*\b'),       _fmt(GREEN)),
        ]

    elif language == Language.BASH:
        rules += [
            (QRegExp(r'#[^\n]*'), _fmt(FG_DIM, italic=True)),
            (QRegExp(r'\b(if|then|else|fi|for|while|do|done|case|esac|'
                     r'function|return|echo|export|source|cd|grep|awk|sed|'
                     r'ls|cat|mkdir|rm|mv|cp|chmod|chown)\b'),
             _fmt(PURPLE, bold=True)),
            (QRegExp(r'"[^"]*"'), _fmt(ORANGE)),
            (QRegExp(r"'[^']*'"), _fmt(ORANGE)),
            (QRegExp(r'\$[\w{][^}]*}?'), _fmt(CYAN)),
        ]

    # YAML / TOML / INI / TEXT / MARKDOWN → no rules (plain)
    return rules


class UniversalHighlighter(QSyntaxHighlighter):
    def __init__(self, document, language: Language = Language.TEXT) -> None:
        super().__init__(document)
        self._rules: list[tuple[QRegExp, QTextCharFormat]] = []
        self.set_language(language)

    def set_language(self, language: Language) -> None:
        self._rules = _rules_for(language)
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        for rx, fmt in self._rules:
            i = rx.indexIn(text)
            while i >= 0:
                self.setFormat(i, rx.matchedLength(), fmt)
                i = rx.indexIn(text, i + rx.matchedLength())
