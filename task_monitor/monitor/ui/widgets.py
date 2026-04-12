"""
Widget helpers
==============
"""

import tkinter as tk
from collections.abc import Callable

from monitor.ui.theme import BG, BORDER, CARD, DIM, FG, FONT_FAMILY, GREEN, RED, YELLOW


def classify_log_line(line: str) -> str:
    """Return a text-widget tag name based on log line content."""

    lower = line.lower()
    if 'error' in lower or 'traceback' in lower or 'exception' in lower:
        return 'error'

    if 'warn' in lower:
        return 'warn'

    if '[cleanup]' in lower or '[startup]' in lower or ' complete' in lower or lower.startswith('complete'):
        return 'info'

    return ''


def draw_gauge(canvas: tk.Canvas, pct: float, label: str = '') -> None:
    """Render a horizontal percentage bar on canvas."""

    canvas.delete('all')
    w = canvas.winfo_width() if canvas.winfo_width() > 1 else 200
    h = canvas.winfo_height() if canvas.winfo_height() > 1 else 14
    pct = max(0.0, min(100.0, pct))
    fill_w = int(w * pct / 100)

    if pct < 60:
        color = GREEN
    elif pct < 80:
        color = YELLOW
    else:
        color = RED

    canvas.create_rectangle(0, 0, fill_w, h, fill=color, outline='')
    canvas.create_text(w // 2, h // 2, text=label, fill=FG, font=(FONT_FAMILY, 8, 'bold'))


def create_gauge_card(
    parent: tk.Frame,
    title: str,
    *,
    pad_left: int = 0,
    pad_right: int = 0,
) -> tuple[tk.Canvas, tk.Label]:
    """Create a labelled progress-bar card and return *(canvas, label)*."""

    card = tk.Frame(parent, bg=CARD, padx=10, pady=6)
    card.pack(side='left', fill='x', expand=True, padx=(pad_left, pad_right))

    tk.Label(card, text=title, bg=CARD, fg=DIM, font=(FONT_FAMILY, 9, 'bold')).pack(anchor='w')

    bar = tk.Canvas(card, height=14, bg=BORDER, highlightthickness=0)
    bar.pack(fill='x', pady=(2, 2))

    lbl = tk.Label(card, text='-', bg=CARD, fg=FG, font=(FONT_FAMILY, 9, 'bold'))
    lbl.pack(anchor='w')

    return bar, lbl


def create_card(parent: tk.Frame, title: str) -> tk.Frame:
    """Create a titled card panel and return the inner frame."""

    outer = tk.Frame(parent, bg=BG)
    outer.pack(fill='both', expand=True, padx=10, pady=3)

    hdr = tk.Frame(outer, bg=CARD)
    hdr.pack(fill='x')

    tk.Label(hdr, text=f'  {title}', bg=CARD, fg=FG, font=(FONT_FAMILY, 10, 'bold')).pack(side='left', pady=3)

    inner = tk.Frame(outer, bg=CARD)
    inner.pack(fill='both', expand=True)

    return inner


def create_action_button(
    parent: tk.Frame,
    text: str,
    bg_color: str,
    cmd: Callable[[], None],
    fg: str = '#ffffff',
) -> tk.Button:
    """Create a flat action button."""

    return tk.Button(
        parent,
        text=text,
        bg=bg_color,
        fg=fg,
        font=(FONT_FAMILY, 8, 'bold'),
        bd=0,
        padx=8,
        pady=2,
        activebackground=BORDER,
        cursor='hand2',
        command=cmd,
    )
