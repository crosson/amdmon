#!/usr/bin/env python3
"""Simple AMD GPU monitor for Ubuntu using amd-smi JSON output."""

from __future__ import annotations

import json
import subprocess
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from tkinter import ttk
from typing import Any


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    color: str
    unit: str | None = None
    default_max: float | None = None


METRICS: list[MetricSpec] = [
    MetricSpec("gfx", "GPU Utilization", "#2a9d8f", "%", 100),
    MetricSpec("mem", "Memory Utilization", "#264653", "%", 100),
    MetricSpec("hotspot_temperature", "Hotspot Temp", "#e76f51", "C", 120),
    MetricSpec("memory_temperature", "Memory Temp", "#f4a261", "C", 120),
    MetricSpec("power_usage", "Power", "#8ab17d", "W", None),
    MetricSpec("vram_used", "VRAM Used", "#577590", "GB", None),
    MetricSpec("gfx_clk", "GPU Clock", "#6d597a", "MHz", None),
]

SESSION_MAX_KEYS = [
    "hotspot_temperature",
    "memory_temperature",
    "power_usage",
    "vram_used",
    "gfx_clk",
]


class LineChart(tk.Canvas):
    def __init__(self, master: tk.Misc, title: str, color: str, **kwargs: Any) -> None:
        super().__init__(
            master,
            bg="#111111",
            highlightthickness=1,
            highlightbackground="#333333",
            height=140,
            **kwargs,
        )
        self.title = title
        self.color = color
        self.bind("<Configure>", lambda _e: self.redraw([], [], "", None))

    def redraw(
        self,
        xs: list[float],
        ys: list[float | None],
        latest_text: str,
        y_max: float | None,
    ) -> None:
        self.delete("all")
        w = max(self.winfo_width(), 10)
        h = max(self.winfo_height(), 10)
        pad_l, pad_r, pad_t, pad_b = 44, 10, 30, 18
        plot_w = max(w - pad_l - pad_r, 10)
        plot_h = max(h - pad_t - pad_b, 10)

        self.create_text(8, 7, anchor="nw", text=self.title, fill="#f0f0f0", font=("TkDefaultFont", 9, "bold"))
        self.create_text(w - 8, 7, anchor="ne", text=latest_text, fill="#d9d9d9", font=("TkDefaultFont", 9))

        # Grid
        for i in range(5):
            y = pad_t + (plot_h * i / 4)
            self.create_line(pad_l, y, pad_l + plot_w, y, fill="#252525")
        self.create_line(pad_l, pad_t, pad_l, pad_t + plot_h, fill="#404040")
        self.create_line(pad_l, pad_t + plot_h, pad_l + plot_w, pad_t + plot_h, fill="#404040")

        valid_values = [v for v in ys if v is not None]
        if not valid_values or len(xs) < 2:
            self.create_text(w / 2, h / 2, text="Waiting for data...", fill="#888888")
            return

        top = y_max if y_max and y_max > 0 else max(valid_values) * 1.15
        if top <= 0:
            top = 1.0

        # Labels on y axis
        for i in range(5):
            frac = 1 - (i / 4)
            val = top * frac
            y = pad_t + plot_h * (1 - frac)
            self.create_text(40, y, anchor="e", text=f"{val:.0f}", fill="#9a9a9a", font=("TkDefaultFont", 8))

        x_min = xs[0]
        x_max = xs[-1]
        span = max(x_max - x_min, 1e-6)
        pts: list[float] = []
        for x, yv in zip(xs, ys):
            if yv is None:
                if len(pts) >= 4:
                    self.create_line(*pts, fill=self.color, width=2, smooth=True)
                pts = []
                continue
            cx = pad_l + ((x - x_min) / span) * plot_w
            cy = pad_t + (1 - min(max(yv / top, 0.0), 1.0)) * plot_h
            pts.extend([cx, cy])
        if len(pts) >= 4:
            self.create_line(*pts, fill=self.color, width=2, smooth=True)


class AmdMonApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("AMD GPU Monitor")
        self.root.geometry("1100x760")
        self.root.configure(bg="#1a1a1a")

        self.gpu_index = tk.IntVar(value=0)
        self.interval_sec = tk.IntVar(value=2)
        self.history_sec = tk.IntVar(value=120)
        self.running = False
        self.after_id: str | None = None
        self.status_text = tk.StringVar(value="Stopped")
        self.last_sample_time = tk.StringVar(value="No samples yet")

        self.timestamps: deque[float] = deque()
        self.series: dict[str, deque[float | None]] = {m.key: deque() for m in METRICS}
        self.units: dict[str, str] = {}
        self.session_max: dict[str, float | None] = {key: None for key in SESSION_MAX_KEYS}
        self.session_max_vars: dict[str, tk.StringVar] = {}

        self.chart_widgets: dict[str, LineChart] = {}
        self._build_ui()
        self._trim_history()
        self._redraw_all()

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background="#1a1a1a")
        style.configure("TLabel", background="#1a1a1a", foreground="#e8e8e8")
        style.configure("TButton", padding=6)
        style.configure("TCombobox", padding=4)

        controls = ttk.Frame(self.root, padding=10)
        controls.pack(fill="x")

        ttk.Label(controls, text="GPU Index").grid(row=0, column=0, padx=(0, 6), pady=4, sticky="w")
        gpu_spin = ttk.Spinbox(controls, from_=0, to=15, textvariable=self.gpu_index, width=6)
        gpu_spin.grid(row=0, column=1, padx=(0, 12), pady=4)

        ttk.Label(controls, text="Update Interval").grid(row=0, column=2, padx=(0, 6), pady=4, sticky="w")
        interval_box = ttk.Combobox(
            controls,
            width=6,
            state="readonly",
            values=[str(i) for i in range(1, 11)],
            textvariable=self.interval_sec,
        )
        interval_box.grid(row=0, column=3, padx=(0, 12), pady=4)

        ttk.Label(controls, text="History").grid(row=0, column=4, padx=(0, 6), pady=4, sticky="w")
        history_box = ttk.Combobox(
            controls,
            width=8,
            state="readonly",
            values=["60", "120", "300", "600"],
            textvariable=self.history_sec,
        )
        history_box.grid(row=0, column=5, padx=(0, 12), pady=4)
        history_box.bind("<<ComboboxSelected>>", lambda _e: self._on_history_change())

        self.start_btn = ttk.Button(controls, text="Start", command=self.toggle_running)
        self.start_btn.grid(row=0, column=6, padx=(0, 8), pady=4)

        ttk.Button(controls, text="Sample Now", command=self.poll_once).grid(row=0, column=7, padx=(0, 8), pady=4)
        ttk.Button(controls, text="Clear", command=self.clear_history).grid(row=0, column=8, padx=(0, 8), pady=4)

        status = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        status.pack(fill="x")
        ttk.Label(status, text="Status:").pack(side="left")
        ttk.Label(status, textvariable=self.status_text).pack(side="left", padx=(4, 14))
        ttk.Label(status, text="Last Sample:").pack(side="left")
        ttk.Label(status, textvariable=self.last_sample_time).pack(side="left", padx=(4, 0))

        self.error_label = ttk.Label(self.root, text="", foreground="#ff8080", padding=(10, 0, 10, 8))
        self.error_label.pack(fill="x")

        charts_frame = ttk.Frame(self.root, padding=10)
        charts_frame.pack(fill="both", expand=True)
        for i in range(2):
            charts_frame.columnconfigure(i, weight=1)
        for i in range((len(METRICS) + 1) // 2):
            charts_frame.rowconfigure(i, weight=1)

        for idx, metric in enumerate(METRICS):
            chart = LineChart(charts_frame, metric.label, metric.color)
            r, c = divmod(idx, 2)
            chart.grid(row=r, column=c, sticky="nsew", padx=6, pady=6)
            self.chart_widgets[metric.key] = chart

        self._build_session_max_panel(charts_frame)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_session_max_panel(self, parent: ttk.Frame) -> None:
        panel = tk.Frame(parent, bg="#111111", highlightthickness=1, highlightbackground="#333333")
        panel.grid(row=3, column=1, sticky="nsew", padx=6, pady=6)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_columnconfigure(1, weight=0)

        header = tk.Label(
            panel,
            text="Session Max",
            bg="#111111",
            fg="#f0f0f0",
            anchor="w",
            font=("TkDefaultFont", 10, "bold"),
        )
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 10))

        labels = {
            "hotspot_temperature": "Hotspot Temp",
            "memory_temperature": "VRAM Temp",
            "power_usage": "Power",
            "vram_used": "VRAM Used",
            "gfx_clk": "GPU Clock",
        }
        for row, key in enumerate(SESSION_MAX_KEYS, start=1):
            tk.Label(panel, text=labels[key], bg="#111111", fg="#d8d8d8", anchor="w").grid(
                row=row, column=0, sticky="w", padx=(10, 8), pady=4
            )
            value_var = tk.StringVar(value="--")
            self.session_max_vars[key] = value_var
            tk.Label(
                panel,
                textvariable=value_var,
                bg="#111111",
                fg="#ffffff",
                anchor="e",
                font=("TkDefaultFont", 9, "bold"),
            ).grid(row=row, column=1, sticky="e", padx=(8, 10), pady=4)

    def toggle_running(self) -> None:
        if self.running:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        self.running = True
        self.start_btn.configure(text="Stop")
        self.status_text.set("Running")
        self.error_label.configure(text="")
        self._schedule_next(immediate=True)

    def _stop(self) -> None:
        self.running = False
        self.start_btn.configure(text="Start")
        self.status_text.set("Stopped")
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None

    def _schedule_next(self, *, immediate: bool = False) -> None:
        if not self.running:
            return
        delay_ms = 10 if immediate else max(1000, self.interval_sec.get() * 1000)
        self.after_id = self.root.after(delay_ms, self._poll_loop)

    def _poll_loop(self) -> None:
        self.after_id = None
        self.poll_once()
        self._schedule_next()

    def poll_once(self) -> None:
        gpu = self.gpu_index.get()
        cmd = ["amd-smi", "monitor", "-g", str(gpu), "--json"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8, check=False)
        except FileNotFoundError:
            self._set_error("`amd-smi` command not found. Install ROCm/AMD SMI and ensure it is in PATH.")
            return
        except subprocess.TimeoutExpired:
            self._set_error("amd-smi timed out while reading metrics.")
            return

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            self._set_error(f"amd-smi failed for GPU {gpu}: {stderr or 'unknown error'}")
            return

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            self._set_error(f"Invalid JSON from amd-smi: {exc}")
            return

        sample = self._extract_gpu_record(payload, gpu)
        if sample is None:
            self._set_error(f"No GPU record found in amd-smi output for GPU index {gpu}.")
            return

        self._set_error("")
        ts = time.time()
        self.timestamps.append(ts)
        for metric in METRICS:
            value, unit = self._read_metric(sample, metric.key)
            if unit:
                self.units[metric.key] = unit
            self.series[metric.key].append(value)
            if metric.key in self.session_max and value is not None:
                prev = self.session_max[metric.key]
                self.session_max[metric.key] = value if prev is None else max(prev, value)

        self.last_sample_time.set(time.strftime("%H:%M:%S"))
        self.status_text.set(f"Running (GPU {gpu})" if self.running else f"Sampled GPU {gpu}")
        self._trim_history()
        self._redraw_all()

    def _extract_gpu_record(self, payload: Any, gpu_index: int) -> dict[str, Any] | None:
        if isinstance(payload, dict):
            records = [payload]
        elif isinstance(payload, list):
            records = [r for r in payload if isinstance(r, dict)]
        else:
            return None

        for record in records:
            if record.get("gpu") == gpu_index:
                return record
        return records[0] if records else None

    def _read_metric(self, record: dict[str, Any], key: str) -> tuple[float | None, str | None]:
        raw = record.get(key)
        if isinstance(raw, dict):
            val = raw.get("value")
            unit = raw.get("unit")
            return self._to_float(val), (str(unit) if unit is not None else None)
        if isinstance(raw, (int, float)):
            return float(raw), None
        return None, None

    def _to_float(self, value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    def _trim_history(self) -> None:
        window = max(10, self.history_sec.get())
        if not self.timestamps:
            return
        cutoff = self.timestamps[-1] - window
        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.popleft()
            for metric in METRICS:
                if self.series[metric.key]:
                    self.series[metric.key].popleft()

    def _on_history_change(self) -> None:
        self._trim_history()
        self._redraw_all()

    def clear_history(self) -> None:
        self.timestamps.clear()
        for metric in METRICS:
            self.series[metric.key].clear()
        for key in SESSION_MAX_KEYS:
            self.session_max[key] = None
        self.last_sample_time.set("No samples yet")
        self._redraw_all()

    def _redraw_all(self) -> None:
        xs = list(self.timestamps)
        for metric in METRICS:
            ys = list(self.series[metric.key])
            latest = next((v for v in reversed(ys) if v is not None), None)
            unit = self.units.get(metric.key) or metric.unit or ""
            latest_text = "--"
            if latest is not None:
                latest_text = self._format_value(latest, unit)
            self.chart_widgets[metric.key].redraw(xs, ys, latest_text, metric.default_max)
        self._refresh_session_max_panel()

    def _refresh_session_max_panel(self) -> None:
        for key in SESSION_MAX_KEYS:
            metric = next((m for m in METRICS if m.key == key), None)
            unit = self.units.get(key) or (metric.unit if metric else "") or ""
            value = self.session_max.get(key)
            self.session_max_vars[key].set("--" if value is None else self._format_value(value, unit))

    def _format_value(self, value: float, unit: str) -> str:
        if unit == "%":
            return f"{value:.0f}{unit}"
        if unit in {"W", "C", "MHz"}:
            return f"{value:.0f} {unit}"
        return f"{value:.2f} {unit}".strip()

    def _set_error(self, message: str) -> None:
        self.error_label.configure(text=message)

    def on_close(self) -> None:
        self._stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    AmdMonApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
