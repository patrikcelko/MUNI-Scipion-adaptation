"""
Theme constants
===============
"""

from tkinter import ttk

FONT_FAMILY = 'Segoe UI'
"""Primary font family (falls back to system default if unavailable)."""

BG = '#0d1117'
"""Main window background."""

CARD = '#161b22'
"""Card / panel background."""

BORDER = '#30363d'
"""Subtle borders and separators."""

FG = '#c9d1d9'
"""Primary foreground text."""

DIM = '#8b949e'
"""Secondary / muted text."""

BLUE = '#58a6ff'
"""Accent - active / running items."""

GREEN = '#3fb950'
"""Success / healthy items."""

RED = '#f85149'
"""Error / failed items."""

YELLOW = '#d29922'
"""Warning / pending items."""

ORANGE = '#d18616'
"""Caution actions (e.g. kill pod)."""

BLUE_DARK = '#1f6feb'
"""Darker accent blue (selections, active backgrounds)."""

LOG_BG = '#010409'
"""Log viewer background."""

LOG_FG = '#e6edf3'
"""Log viewer foreground."""


def apply_styles(style: ttk.Style) -> None:
    """Configure all ttk styles for the dark theme."""

    style.configure('.', background=BG, foreground=FG, borderwidth=0)
    style.configure('Card.TFrame', background=CARD)

    style.configure('Dark.TNotebook', background=BG, borderwidth=0)
    style.configure(
        'Dark.TNotebook.Tab',
        background=BORDER,
        foreground=DIM,
        font=(FONT_FAMILY, 10, 'bold'),
        padding=(12, 4),
    )
    style.map(
        'Dark.TNotebook.Tab',
        background=[('selected', CARD)],
        foreground=[('selected', BLUE)],
    )

    style.configure(
        'Dark.Treeview',
        background=CARD,
        foreground=FG,
        fieldbackground=CARD,
        borderwidth=0,
        font=(FONT_FAMILY, 9),
    )
    style.configure(
        'Dark.Treeview.Heading',
        background=BORDER,
        foreground=DIM,
        font=(FONT_FAMILY, 9, 'bold'),
    )
    style.map(
        'Dark.Treeview',
        background=[('selected', BLUE_DARK)],
        foreground=[('selected', '#ffffff')],
    )
