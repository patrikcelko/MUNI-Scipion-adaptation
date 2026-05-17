"""
Task monitor application
========================
"""

import time
import tkinter as tk
from tkinter import messagebox, ttk

from monitor.api import ControllerClient
from monitor.ui.theme import (
    BG,
    BLUE,
    BLUE_DARK,
    BORDER,
    CARD,
    DIM,
    FG,
    FONT_FAMILY,
    GREEN,
    LOG_BG,
    LOG_FG,
    ORANGE,
    RED,
    YELLOW,
    apply_styles,
)
from monitor.ui.widgets import (
    classify_log_line,
    create_action_button,
    create_card,
    create_gauge_card,
    draw_gauge,
)

REFRESH_MS = 3000
"""Polling interval for jobs / pods / events (ms)."""

METRICS_REFRESH_MS = 5000
"""Polling interval for metrics + disk (heavier calls)."""

_MAX_EVENTS = 15
"""Maximum number of events shown in the overview table."""


class TaskMonitor(tk.Tk):
    """Top-level Tk window for the Scipion cluster dashboard."""

    def __init__(self, client: ControllerClient | None = None) -> None:
        super().__init__()
        self.title('Scipion Task Monitor')
        self.configure(bg=BG)

        # Centre on the primary monitor instead of hardcoding an x offset that
        # puts the window off-screen on single-monitor setups.
        self.geometry('640x900')
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - 640) // 2)
        y = max(0, (sh - 900) // 2)
        self.geometry(f'640x900+{x}+{y}')
        self.minsize(500, 600)

        self._client = client or ControllerClient()

        style = ttk.Style(self)
        style.theme_use('clam')
        apply_styles(style)

        self._nb = ttk.Notebook(self, style='Dark.TNotebook')
        self._nb.pack(fill='both', expand=True)

        self._tab_overview = tk.Frame(self._nb, bg=BG)
        self._nb.add(self._tab_overview, text=' Overview ')

        self._tab_logs = tk.Frame(self._nb, bg=BG)
        self._nb.add(self._tab_logs, text=' Logs ')

        self._pod_metrics: dict[str, dict] = {}
        self._build_overview()
        self._build_logs_tab()

        self._schedule_refresh()
        self._schedule_metrics()

    @staticmethod
    def _get_selected(tree: ttk.Treeview) -> str | None:
        """Return the name (first column) of the selected row, or `None`."""

        sel = tree.selection()
        if not sel:
            return None

        vals = tree.item(sel[0], 'values')
        return vals[0] if vals else None

    def _show_logs_for(self, tree: ttk.Treeview) -> None:
        """Switch to Logs tab and fetch logs for the selected tree row."""

        name = self._get_selected(tree)
        if name:
            self._log_pod_var.set(name)
            self._nb.select(self._tab_logs)
            self._fetch_logs()

    def _show_result(self, result: dict | None, success_msg: str) -> None:
        """Update the cleanup label with a delete_job / delete_pod result."""

        if result and 'deleted' in result:
            self._cleanup_lbl.config(text=success_msg, fg=GREEN)
        else:
            err = result.get('error', 'unknown') if result else 'no response'
            self._cleanup_lbl.config(text=f'Error: {err}', fg=RED)

    def _on_rightclick(
        self,
        event: tk.Event,
        tree: ttk.Treeview,
        menu: tk.Menu,
    ) -> None:
        """Select row under cursor and show context menu."""

        row = tree.identify_row(event.y)
        if row:
            tree.selection_set(row)
            menu.post(event.x_root, event.y_root)

    def _on_dblclick(self, _event: tk.Event, tree: ttk.Treeview) -> None:
        """Double-click handler: jump to logs for the clicked row."""

        self._show_logs_for(tree)

    @staticmethod
    def _setup_treeview(
        parent: tk.Frame,
        columns: list[tuple[str, int, str]],
        *,
        height: int = 7,
    ) -> ttk.Treeview:
        """Create a `Treeview` with the given columns and pack it."""

        col_ids = tuple(c[0] for c in columns)
        tree = ttk.Treeview(
            parent,
            columns=col_ids,
            show='headings',
            style='Dark.Treeview',
            height=height,
        )

        for col_id, width, heading in columns:
            tree.heading(col_id, text=heading)
            tree.column(col_id, width=width, minwidth=40)
        tree.pack(fill='both', expand=True, padx=1, pady=(0, 1))

        return tree

    @staticmethod
    def _create_context_menu(parent: tk.Tk) -> tk.Menu:
        """Create a dark-themed right-click context menu."""

        return tk.Menu(
            parent,
            tearoff=0,
            bg=CARD,
            fg=FG,
            activebackground=BLUE,
            activeforeground='#ffffff',
            font=(FONT_FAMILY, 9),
        )

    def _build_overview(self) -> None:  # noqa: PLR0915
        """Construct the Overview tab with metrics, job/pod summary, and tables."""

        parent = self._tab_overview

        hdr = tk.Frame(parent, bg=CARD, height=32)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)
        tk.Label(
            hdr,
            text='  Scipion Task Monitor',
            bg=CARD,
            fg=BLUE,
            font=(FONT_FAMILY, 11, 'bold'),
        ).pack(side='left', padx=6, pady=4)
        self._status_lbl = tk.Label(hdr, text='connecting...', bg=CARD, fg=DIM, font=(FONT_FAMILY, 9))
        self._status_lbl.pack(side='right', padx=10)

        metrics_frame = tk.Frame(parent, bg=BG)
        metrics_frame.pack(fill='x', padx=10, pady=(6, 2))

        self._cpu_bar, self._cpu_lbl = create_gauge_card(metrics_frame, 'CPU', pad_left=0, pad_right=3)
        self._mem_bar, self._mem_lbl = create_gauge_card(metrics_frame, 'Memory', pad_left=3, pad_right=3)
        self._disk_bar, self._disk_lbl = create_gauge_card(metrics_frame, 'Disk', pad_left=3, pad_right=0)

        summary = tk.Frame(parent, bg=BG)
        summary.pack(fill='x', padx=10, pady=(4, 2))
        self._sum_labels: dict[str, tk.Label] = {}
        for key, label, color in [
            ('total', 'Total', FG),
            ('running', 'Running', BLUE),
            ('done', 'Done', GREEN),
            ('failed', 'Failed', RED),
        ]:
            f = tk.Frame(summary, bg=BG)
            f.pack(side='left', padx=(0, 16))
            num = tk.Label(f, text='0', bg=BG, fg=color, font=(FONT_FAMILY, 14, 'bold'))
            num.pack(side='left')
            tk.Label(f, text=f' {label}', bg=BG, fg=DIM, font=(FONT_FAMILY, 9)).pack(side='left')
            self._sum_labels[key] = num

        ctrl_frame = tk.Frame(parent, bg=BG)
        ctrl_frame.pack(fill='x', padx=10, pady=(2, 2))

        create_action_button(ctrl_frame, 'Kill Selected Job', RED, self._kill_selected_job).pack(side='left', padx=(0, 4))
        create_action_button(ctrl_frame, 'Kill Selected Pod', ORANGE, self._kill_selected_pod).pack(side='left', padx=4)
        create_action_button(ctrl_frame, 'Cleanup Finished', YELLOW, self._force_cleanup, fg='#000000').pack(side='left', padx=4)

        self._cleanup_lbl = tk.Label(ctrl_frame, text='', bg=BG, fg=DIM, font=(FONT_FAMILY, 9))
        self._cleanup_lbl.pack(side='left', padx=8)

        self._jobs_frame = create_card(parent, 'Jobs')
        self._jobs_tree = self._setup_treeview(
            self._jobs_frame,
            [
                ('name', 170, 'Job'),
                ('tool', 90, 'Tool'),
                ('status', 70, 'Status'),
                ('cpu', 50, 'CPU'),
                ('mem', 55, 'Mem'),
                ('age', 55, 'Age'),
            ],
            height=7,
        )
        self._jobs_tree.tag_configure('running', foreground=BLUE)
        self._jobs_tree.tag_configure('done', foreground=GREEN)
        self._jobs_tree.tag_configure('failed', foreground=RED)
        self._jobs_tree.bind('<Double-1>', lambda e: self._on_dblclick(e, self._jobs_tree))

        self._jobs_menu = self._create_context_menu(self)
        self._jobs_menu.add_command(label='View Logs', command=lambda: self._show_logs_for(self._jobs_tree))
        self._jobs_menu.add_separator()
        self._jobs_menu.add_command(label='Kill Job', command=self._kill_selected_job)
        self._jobs_tree.bind(
            '<Button-3>',
            lambda e: self._on_rightclick(e, self._jobs_tree, self._jobs_menu),
        )

        self._pods_frame = create_card(parent, 'Pods')
        self._pods_tree = self._setup_treeview(
            self._pods_frame,
            [
                ('name', 200, 'Pod'),
                ('phase', 70, 'Phase'),
                ('cpu', 50, 'CPU'),
                ('mem', 55, 'Mem'),
                ('restarts', 40, 'Rst'),
                ('age', 55, 'Age'),
            ],
            height=4,
        )

        self._pods_tree.tag_configure('running', foreground=GREEN)
        self._pods_tree.tag_configure('pending', foreground=YELLOW)
        self._pods_tree.tag_configure('succeeded', foreground=DIM)
        self._pods_tree.bind('<Double-1>', lambda e: self._on_dblclick(e, self._pods_tree))

        self._pods_menu = self._create_context_menu(self)
        self._pods_menu.add_command(label='View Logs', command=lambda: self._show_logs_for(self._pods_tree))
        self._pods_menu.add_separator()
        self._pods_menu.add_command(label='Kill Pod', command=self._kill_selected_pod)
        self._pods_tree.bind(
            '<Button-3>',
            lambda e: self._on_rightclick(e, self._pods_tree, self._pods_menu),
        )

        self._events_frame = create_card(parent, 'Events')
        self._events_tree = self._setup_treeview(
            self._events_frame,
            [
                ('reason', 90, 'Reason'),
                ('object', 150, 'Object'),
                ('message', 300, 'Message'),
            ],
            height=4,
        )

        self._events_tree.tag_configure('normal', foreground=GREEN)
        self._events_tree.tag_configure('warning', foreground=YELLOW)

    def _build_logs_tab(self) -> None:
        """Construct the Logs tab with pod selection, tail lines, and log viewer."""

        parent = self._tab_logs

        toolbar = tk.Frame(parent, bg=CARD, height=36)
        toolbar.pack(fill='x')
        toolbar.pack_propagate(False)

        tk.Label(toolbar, text=' Pod:', bg=CARD, fg=DIM, font=(FONT_FAMILY, 10)).pack(side='left', padx=(8, 4), pady=6)

        self._log_pod_var = tk.StringVar(value='')
        self._log_combo = ttk.Combobox(toolbar, textvariable=self._log_pod_var, width=40, state='readonly')
        self._log_combo.pack(side='left', padx=4, pady=6)

        self._log_tail_var = tk.StringVar(value='50')
        tk.Label(toolbar, text='Lines:', bg=CARD, fg=DIM, font=(FONT_FAMILY, 10)).pack(side='left', padx=(12, 4))
        tail_spin = tk.Spinbox(
            toolbar,
            textvariable=self._log_tail_var,
            from_=10,
            to=500,
            width=5,
            bg=BORDER,
            fg=FG,
            font=(FONT_FAMILY, 10),
            buttonbackground=BORDER,
            insertbackground=FG,
        )
        tail_spin.pack(side='left', padx=4, pady=6)

        create_action_button(toolbar, 'Fetch', BLUE, self._fetch_logs).pack(
            side='left',
            padx=8,
            pady=6,
        )

        self._auto_refresh_var = tk.BooleanVar(value=False)
        auto_cb = tk.Checkbutton(
            toolbar,
            text='Auto',
            bg=CARD,
            fg=DIM,
            selectcolor=BORDER,
            activebackground=CARD,
            activeforeground=FG,
            variable=self._auto_refresh_var,
            font=(FONT_FAMILY, 9),
        )
        auto_cb.pack(side='left', padx=4)

        self._log_text = tk.Text(
            parent,
            bg=LOG_BG,
            fg=LOG_FG,
            font=('Consolas', 9),
            wrap='none',
            insertbackground=FG,
            selectbackground=BLUE_DARK,
            borderwidth=0,
            padx=8,
            pady=6,
        )
        self._log_text.pack(fill='both', expand=True)

        log_scroll = tk.Scrollbar(self._log_text, command=self._log_text.yview, bg=BORDER, troughcolor=LOG_BG)
        log_scroll.pack(side='right', fill='y')
        self._log_text.config(yscrollcommand=log_scroll.set)

        self._log_text.tag_configure('error', foreground=RED)
        self._log_text.tag_configure('warn', foreground=YELLOW)
        self._log_text.tag_configure('info', foreground=GREEN)
        self._log_text.tag_configure('timestamp', foreground=DIM)

    def _kill_selected_job(self) -> None:
        """Prompt for confirmation and delete the selected job from the cluster."""

        name = self._get_selected(self._jobs_tree)
        if not name:
            self._cleanup_lbl.config(text='Select a job first', fg=YELLOW)
            return

        if not messagebox.askyesno('Kill Job', f"Delete job '{name}' and its pods?"):
            return

        result = self._client.delete_job(name)
        self._show_result(result, f'Killed: {name}')

    def _kill_selected_pod(self) -> None:
        """Prompt for confirmation and delete the selected pod."""

        name = self._get_selected(self._pods_tree)
        if not name:
            self._cleanup_lbl.config(text='Select a pod first', fg=YELLOW)
            return

        if not messagebox.askyesno('Kill Pod', f"Delete pod '{name}'?"):
            return

        result = self._client.delete_pod(name)
        self._show_result(result, f'Killed: {name}')

    def _force_cleanup(self) -> None:
        """Prompt for confirmation and trigger finished-job cleanup."""

        if not messagebox.askyesno('Force Cleanup', 'Delete ALL finished/failed jobs?'):
            return

        result = self._client.run_cleanup()
        if result is None:
            self._cleanup_lbl.config(text='Error: no response', fg=RED)
            return

        if 'error' in result:
            self._cleanup_lbl.config(text=f'Error: {result["error"]}', fg=RED)
            return

        n = result.get('deleted_ttl', 0) + result.get('deleted_cap', 0)
        evicted = result.get('evicted', 0)
        parts = [f'{n} job(s)']

        if evicted:
            parts.append(f'{evicted} evicted pod(s)')

        self._cleanup_lbl.config(text=f'Cleaned up {" + ".join(parts)}', fg=GREEN)

    def _fetch_logs(self) -> None:
        """Fetch logs for the selected pod and update the text widget."""

        pod = self._log_pod_var.get()
        if not pod:
            return

        try:
            tail = int(self._log_tail_var.get())
        except ValueError:
            tail = 50
            self._log_tail_var.set('50')

        data = self._client.get_logs(pod, tail=tail)
        if not data:
            self._log_text.delete('1.0', 'end')
            self._log_text.insert('end', 'Failed to fetch logs\n', 'error')
            return

        lines = data.get('lines', [])
        err = data.get('error')

        self._log_text.delete('1.0', 'end')
        if err:
            self._log_text.insert('end', f'Error: {err}\n', 'error')
            return

        for line in lines:
            self._insert_log_line(line)

        self._log_text.see('end')

    def _insert_log_line(self, line: str) -> None:
        """Append one log line with colour tags to the text widget."""

        if not line.strip():
            return

        tag = classify_log_line(line)
        if line[0].isdigit() and 'T' in line[:30]:
            ts_end = line.find(' ', 20)

            if ts_end > 0:
                self._log_text.insert('end', line[:ts_end], 'timestamp')
                self._log_text.insert('end', line[ts_end:] + '\n', tag)
                return

        self._log_text.insert('end', line + '\n', tag)

    def _schedule_refresh(self) -> None:
        """Poll jobs / pods / events on the fast cycle."""

        try:
            self._update_jobs()
            self._update_pods()
            self._update_events()

            if self._auto_refresh_var.get() and self._log_pod_var.get():
                self._fetch_logs()

            now = time.strftime('%H:%M:%S')
            self._status_lbl.config(text=f'live  {now}', fg=GREEN)
        except Exception as exc:
            self._status_lbl.config(text=f'err: {exc}', fg=RED)

        self.after(REFRESH_MS, self._schedule_refresh)

    def _schedule_metrics(self) -> None:
        """Poll metrics + disk on a slower, independent cycle."""

        try:
            self._update_metrics()
            self._update_disk()
        except Exception as exc:
            self._status_lbl.config(text=f'metrics err: {exc}', fg=RED)

        self.after(METRICS_REFRESH_MS, self._schedule_metrics)

    def _format_resource(self, name: str) -> tuple[str, str]:
        """Return `(cpu_str, mem_str)` from cached pod metrics."""

        pm = self._pod_metrics.get(name, {})
        cpu_str = f'{pm["cpu_m"]}m' if pm.get('cpu_m') else '-'
        mem_str = f'{pm["mem_mi"]}Mi' if pm.get('mem_mi') else '-'

        return cpu_str, mem_str

    def _update_metrics(self) -> None:
        """Fetch metrics and update the gauges and labels."""

        data = self._client.get_metrics()

        if not data:
            return

        nodes = data.get('nodes', [])
        if nodes and 'error' not in nodes[0]:
            n = nodes[0]
            cpu_pct = n.get('cpu_pct', 0)
            mem_pct = n.get('mem_pct', 0)
            cpu_used = n.get('cpu_used_m', 0)
            cpu_cap = n.get('cpu_capacity_m', 0)
            mem_used = n.get('mem_used_mi', 0)
            mem_cap = n.get('mem_capacity_mi', 0)

            self._cpu_lbl.config(text=f'{cpu_pct}%  ({cpu_used}m / {cpu_cap}m)')
            self._mem_lbl.config(text=f'{mem_pct}%  ({mem_used}Mi / {mem_cap}Mi)')

            self.after_idle(lambda: draw_gauge(self._cpu_bar, cpu_pct, f'{cpu_pct}%'))
            self.after_idle(lambda: draw_gauge(self._mem_bar, mem_pct, f'{mem_pct}%'))

        pods = data.get('pods', [])
        self._pod_metrics = {}

        for p in pods:
            self._pod_metrics[p.get('name', '')] = p

    def _update_disk(self) -> None:
        """Fetch disk usage and update the gauge and label."""

        data = self._client.get_disk()

        if not data or 'error' in data:
            return

        pct = data.get('percent', 0)
        used = data.get('used_gi', 0)
        total = data.get('total_gi', 0)
        free = data.get('free_gi', 0)

        self._disk_lbl.config(text=f'{pct}%  ({used} / {total} GiB, {free} free)')
        self.after_idle(lambda: draw_gauge(self._disk_bar, pct, f'{pct}%'))

    def _update_jobs(self) -> None:
        """Fetch recent jobs and update the treeview table."""

        data = self._client.get_jobs()

        if not data:
            return

        jobs = data.get('jobs', [])
        running = sum(1 for j in jobs if j.get('phase') == 'RUNNING')
        done = sum(1 for j in jobs if j.get('phase') == 'DONE')
        failed = sum(1 for j in jobs if j.get('phase') == 'FAILED')

        self._sum_labels['total'].config(text=str(len(jobs)))
        self._sum_labels['running'].config(text=str(running))
        self._sum_labels['done'].config(text=str(done))
        self._sum_labels['failed'].config(text=str(failed))

        self._jobs_tree.delete(*self._jobs_tree.get_children())

        for j in jobs:
            phase = j.get('phase', 'UNKNOWN')
            tag = phase.lower()
            name = j.get('name', '-')
            tool = j.get('tool', '-')
            age = j.get('age', '-')

            cpu_str, mem_str = self._format_resource(name)

            self._jobs_tree.insert('', 'end', values=(name, tool, phase, cpu_str, mem_str, age), tags=(tag,))

    def _update_pods(self) -> None:
        """Fetch recent pods and update the treeview table."""

        data = self._client.get_pods()

        if not data:
            return

        pods = data.get('pods', [])
        all_pod_names: list[str] = []

        self._pods_tree.delete(*self._pods_tree.get_children())
        for p in pods:
            restarts = sum(c.get('restarts', 0) for c in p.get('containers', []))
            phase = p.get('phase', 'Unknown')
            name = p.get('name', '-')
            age = p.get('age', '-')
            tag = 'running' if phase == 'Running' else ('succeeded' if phase == 'Succeeded' else 'pending')

            cpu_str, mem_str = self._format_resource(name)

            self._pods_tree.insert('', 'end', values=(name, phase, cpu_str, mem_str, str(restarts), age), tags=(tag,))
            if name != '-':
                all_pod_names.append(name)

        self._log_combo['values'] = all_pod_names

        # If the currently selected pod has disappeared, clear the selection
        # to prevent the next auto-refresh from querying a deleted pod.
        current = self._log_pod_var.get()
        if current and current not in all_pod_names:
            self._log_pod_var.set('')

    def _update_events(self) -> None:
        """Fetch recent events and update the treeview table."""

        data = self._client.get_events()

        if not data:
            return

        events = data.get('events', [])
        self._events_tree.delete(*self._events_tree.get_children())

        for e in events[:_MAX_EVENTS]:
            tag = 'normal' if e.get('type') == 'Normal' else 'warning'
            self._events_tree.insert(
                '',
                'end',
                values=(
                    e.get('reason', '-'),
                    e.get('object', '-'),
                    e.get('message', '-')[:120],
                ),
                tags=(tag,),
            )
