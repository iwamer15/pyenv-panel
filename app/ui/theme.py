"""アプリ全体の見た目（Qtスタイルシート）と、画面間で共通の小さな部品。"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

ACCENT = "#2563eb"

# 状態の色（背景, 文字）
OK_COLORS = ("#dcfce7", "#166534")
WARN_COLORS = ("#ffedd5", "#9a3412")
ERROR_COLORS = ("#fee2e2", "#991b1b")
INFO_COLORS = ("#dbeafe", "#1e40af")
CAUTION_COLORS = ("#fef9c3", "#854d0e")
MUTED_COLORS = ("#f1f5f9", "#64748b")

APP_QSS = f"""
QMainWindow, QDialog {{ background: #f8fafc; }}
QWidget {{ font-size: 13px; color: #0f172a; }}

/* 左サイドバー */
QListWidget#nav {{
    background: #0f172a; border: none; padding: 8px 6px; outline: 0;
}}
QListWidget#nav::item {{
    color: #cbd5e1; padding: 10px 12px; border-radius: 6px; margin: 2px 0;
}}
QListWidget#nav::item:selected {{ background: {ACCENT}; color: white; }}
QListWidget#nav::item:hover:!selected {{ background: #1e293b; }}

/* 上部の環境バー・カード */
QFrame#envbar {{ background: white; border-bottom: 1px solid #e2e8f0; }}
QFrame#card {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; }}
QFrame#banner {{ border-radius: 8px; }}

QPushButton {{
    background: white; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 12px;
}}
QPushButton:hover {{ background: #f1f5f9; }}
QPushButton:disabled {{ color: #94a3b8; background: #f8fafc; border-color: #e2e8f0; }}
QPushButton#primary {{
    background: {ACCENT}; color: white; border: none; font-weight: bold; padding: 8px 16px;
}}
QPushButton#primary:hover {{ background: #1d4ed8; }}
QPushButton#primary:disabled {{ background: #93c5fd; color: #eff6ff; }}
QPushButton#link {{ border: none; background: transparent; color: {ACCENT}; padding: 2px 6px; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QPushButton#rowaction {{ padding: 3px 14px; font-size: 12px; min-height: 20px; }}

/* 絞り込みの切替ボタン（セグメント） */
QPushButton#segment {{ border-radius: 0; padding: 5px 14px; margin: 0; }}
QPushButton#segment:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}

QLineEdit {{ border: 1px solid #cbd5e1; border-radius: 6px; padding: 5px 8px; background: white; }}
QTableWidget {{
    background: white; border: 1px solid #e2e8f0; border-radius: 8px; gridline-color: #f1f5f9;
    selection-background-color: #bfdbfe; selection-color: #0f172a;
}}
QHeaderView::section {{
    background: #f8fafc; border: none; border-bottom: 1px solid #e2e8f0; padding: 6px; font-weight: bold;
    color: #475569;
}}
QListWidget#toollist {{ background: transparent; border: none; outline: 0; }}
QListWidget#toollist::item {{ border-radius: 8px; margin: 3px 0; }}
QListWidget#toollist::item:selected {{ background: #dbeafe; }}
QListWidget#toollist::item:hover:!selected {{ background: #f1f5f9; }}
QPlainTextEdit {{ background: #0f172a; color: #e2e8f0; border-radius: 6px; font-family: Menlo, Consolas, monospace; font-size: 12px; }}
QProgressBar {{ border: none; background: #e2e8f0; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QLabel#muted {{ color: #64748b; }}
QLabel#h1 {{ font-size: 18px; font-weight: bold; }}
QLabel#h2 {{ font-size: 15px; font-weight: bold; }}
"""


def pill(text: str, colors: tuple[str, str]) -> QLabel:
    """角丸の小さなバッジ。"""
    label = QLabel(text)
    label.setFixedHeight(20)
    bg, fg = colors
    label.setStyleSheet(
        f"background:{bg}; color:{fg}; border-radius:9px; padding:2px 8px; font-size:11px; font-weight:bold;"
    )
    return label


def elide_middle(text: str, max_len: int = 60) -> str:
    """長いパスを「先頭…末尾」に縮める（全体はツールチップで見せる）。"""
    if len(text) <= max_len:
        return text
    keep = (max_len - 1) // 2
    return text[:keep] + "…" + text[-keep:]
