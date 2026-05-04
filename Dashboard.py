from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path
import statistics

import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.ticker import FuncFormatter

from tracker_core import (
    MAX_HISTORY_POINTS,
    format_damage_value,
    load_saved_state,
    parse_damage_line,
    save_state,
)

APP_TITLE = "WF Damage"
WINDOW_GEOMETRY = "1500x900"
WINDOW_MIN_SIZE = (1320, 760)
PLOT_FIGSIZE = (11, 4.2)

# Palette
BG_COLOR = "#090909"
SURFACE_COLOR = "#111111"
SURFACE_ALT_COLOR = "#171717"
CARD_COLOR = "#1b1b1b"
CARD_BORDER = "#2f2f2f"
TEXT_COLOR = "#e5e5e5"
MUTED_TEXT_COLOR = "#9ca3af"
ACCENT_COLOR = "#ef4444"
ACCENT_HOVER = "#dc2626"
SUCCESS_COLOR = "#22c55e"
SUCCESS_SOFT = "#14532d"
INFO_COLOR = "#38bdf8"
WARNING_COLOR = "#fbbf24"
DANGER_COLOR = "#ef4444"
TOTAL_COLOR = "#a78bfa"
TOP5_COLOR = "#60a5fa"
SESSION_COLOR = "#f472b6"
MEAN_COLOR = "#22d3ee"
LAST_BREACH_COLOR = "#fb923c"
OVER_CAP_COLOR = "#2dd4bf"
HISTORY_COLOR = "#f43f5e"
MAX_LINE_COLOR = "#f43f5e"
GRID_COLOR = "#2a2a2a"
PLOT_BG = "#101010"

TITLE_FONT = ("Segoe UI", 22, "bold")
SUBTITLE_FONT = ("Segoe UI", 12)
CARD_TITLE_FONT = ("Segoe UI", 12, "bold")
STAT_VALUE_FONT = ("Consolas", 22, "bold")
SMALL_FONT = ("Segoe UI", 10)
LOG_FONT = ("Consolas", 14)
TOP5_FONT = STAT_VALUE_FONT
FILE_FONT = ("Segoe UI", 11, "bold")
STAMP_FONT = STAT_VALUE_FONT
CARD_HEIGHT = 146


class DamageTracker(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._stop_event = threading.Event()
        self._log_thread: threading.Thread | None = None

        self.local_app_data = self._resolve_local_app_data()
        self.warframe_dir = self.local_app_data / "Warframe"
        self.save_path = self.warframe_dir / "savelog.json"
        self.log_path = self.warframe_dir / "EE.log"

        state = load_saved_state(self.save_path)
        self.damage_history = state["damage_history"]
        self.max_hit = state["max_hit"]
        self.hit_count = state["hit_count"]
        self.all_hits = state["all_hits"]
        self.hit_events = state.get("hit_events", [])
        self.session_started_at = self._parse_saved_timestamp(state.get("session_started_at")) or datetime.now()
        self.last_cap_breach_at = self._latest_event_timestamp()
        self.highest_hit_at = self._latest_max_timestamp()

        self.title(APP_TITLE)
        self.geometry(WINDOW_GEOMETRY)
        self.minsize(*WINDOW_MIN_SIZE)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.configure(fg_color=BG_COLOR)

        self._build_ui()
        self._update_labels()
        self._draw_graph()
        self._start_log_listener()

    @staticmethod
    def _resolve_local_app_data() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("LOCALAPPDATA is not set. Run this app on Windows.")
        return Path(local_app_data)

    @property
    def average_hit(self) -> float:
        return self.all_hits / self.hit_count if self.hit_count else 0

    @property
    def recent_hit(self) -> int:
        return self.damage_history[-1] if self.damage_history else 0

    @property
    def over_cap_count(self) -> int:
        return self.hit_count

    @property
    def session_duration(self) -> float:
        return max((datetime.now() - self.session_started_at).total_seconds(), 0.0)

    @property
    def hits_per_minute(self) -> float:
        elapsed_minutes = max(self.session_duration / 60.0, 1 / 60)
        return self.hit_count / elapsed_minutes if self.hit_count else 0.0

    @property
    def std_deviation(self) -> float:
        values = self._event_values()
        if len(values) <= 1:
            return 0.0
        return statistics.pstdev(values)

    def _event_values(self) -> list[int]:
        values = [event.get("value") for event in self.hit_events if isinstance(event, dict)]
        return [int(value) for value in values if isinstance(value, int)]

    def _format_duration(self, total_seconds: float) -> str:
        seconds = max(int(total_seconds), 0)
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_stat_value(value: float) -> str:
        numeric = float(value)
        if abs(numeric) >= 1_000_000:
            return format_damage_value(numeric)
        if numeric.is_integer():
            return f"{int(numeric):,}"
        return f"{numeric:,.1f}"

    @staticmethod
    def _format_log_timestamp(value: datetime | str | None) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M")
        if not value:
            return "---- -- --:--"

        text = str(value).strip()
        for pattern in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M",
            "%m/%d %H:%M",
            "%H:%M:%S",
            "%H:%M",
        ):
            try:
                parsed = datetime.strptime(text, pattern)
                if pattern in ("%H:%M:%S", "%H:%M"):
                    return f"{datetime.now():%Y-%m-%d} {parsed:%H:%M}"
                return parsed.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return text

    @staticmethod
    def _format_timestamp(value: datetime | None) -> str:
        return value.strftime("%Y-%m-%d %H:%M") if value else "--"

    def _latest_event_timestamp(self) -> datetime | None:
        if not self.hit_events:
            return None
        for event in reversed(self.hit_events):
            timestamp = self._parse_event_timestamp(event)
            if timestamp is not None:
                return timestamp
        return None

    def _latest_max_timestamp(self) -> datetime | None:
        if not self.hit_events:
            return None
        best_value = None
        best_timestamp = None
        for event in self.hit_events:
            value = event.get("value") if isinstance(event, dict) else None
            if not isinstance(value, int):
                continue
            timestamp = self._parse_event_timestamp(event)
            if best_value is None or value > best_value or (value == best_value and timestamp is not None):
                best_value = value
                best_timestamp = timestamp
        return best_timestamp

    @staticmethod
    def _parse_saved_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    @staticmethod
    def _parse_event_timestamp(event: dict) -> datetime | None:
        raw_timestamp = event.get("timestamp") if isinstance(event, dict) else None
        display_timestamp = event.get("display_timestamp") if isinstance(event, dict) else None

        for candidate in (raw_timestamp, display_timestamp):
            if not candidate:
                continue

            text = str(candidate).strip()
            for pattern in (
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M",
                "%m/%d %H:%M",
                "%H:%M:%S",
                "%H:%M",
            ):
                try:
                    parsed = datetime.strptime(text, pattern)
                    if pattern in ("%m/%d %H:%M", "%H:%M:%S", "%H:%M"):
                        return datetime.combine(datetime.now().date(), parsed.time())
                    return parsed
                except ValueError:
                    continue

            try:
                return datetime.fromisoformat(text)
            except ValueError:
                continue

        return None

    def _top_hits_text(self) -> str:
        values = [event for event in self.hit_events if isinstance(event, dict) and isinstance(event.get("value"), int)]
        if not values:
            return "No hits yet"

        top_hits = sorted(
            values,
            key=lambda event: (int(event["value"]), str(event.get("timestamp") or "")),
            reverse=True,
        )[:3]
        lines = []
        for index, event in enumerate(top_hits, start=1):
            lines.append(f"{index}. {format_damage_value(event['value'])}")
        return "\n".join(lines)

    def _tracked_file_label(self) -> str:
        return f"{self.log_path.parent.name}/{self.log_path.name}"

    def _build_ui(self) -> None:
        self.app_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.app_frame.pack(fill="both", expand=True, padx=18, pady=18)
        self.app_frame.grid_rowconfigure(1, weight=1)
        self.app_frame.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_main_content()
        self._build_footer()

    def _build_header(self) -> None:
        self.header_frame = ctk.CTkFrame(
            self.app_frame,
            fg_color=SURFACE_COLOR,
            corner_radius=18,
            border_width=1,
            border_color=CARD_BORDER,
        )
        self.header_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        self.header_frame.grid_columnconfigure(0, weight=1)
        self.header_frame.grid_columnconfigure(1, weight=0)

        title_bar = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        title_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=14)
        title_bar.grid_columnconfigure(0, weight=1)
        title_bar.grid_columnconfigure(1, weight=0)
        title_bar.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            title_bar,
            text="WF Damage",
            font=TITLE_FONT,
            text_color=TEXT_COLOR,
        ).grid(row=0, column=0, sticky="w")

        self.log_status_frame, self.log_status_label = self._make_badge(
            title_bar,
            "Found EE.log" if self.log_path.exists() else "Waiting for EE.log",
            ACCENT_COLOR if self.log_path.exists() else MUTED_TEXT_COLOR,
            SURFACE_ALT_COLOR if self.log_path.exists() else SURFACE_ALT_COLOR,
        )
        self.log_status_frame.grid(row=0, column=1, sticky="n", padx=8)

        self.reset_button = ctk.CTkButton(
            master=title_bar,
            text="Reset",
            width=110,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER,
            command=self.reset_data,
        )
        self.reset_button.grid(row=0, column=2, sticky="e")

    def _build_main_content(self) -> None:
        self.content_frame = ctk.CTkFrame(self.app_frame, fg_color="transparent")
        self.content_frame.grid(row=1, column=0, sticky="nsew")
        self.content_frame.grid_columnconfigure(0, weight=4, uniform="content")
        self.content_frame.grid_columnconfigure(1, weight=3, uniform="content")
        self.content_frame.grid_rowconfigure(0, weight=1)

        self.stats_panel = ctk.CTkFrame(
            self.content_frame,
            fg_color=SURFACE_COLOR,
            corner_radius=18,
            border_width=1,
            border_color=CARD_BORDER,
        )
        self.stats_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        for column in range(2):
            self.stats_panel.grid_columnconfigure(column, weight=1, uniform="stats")
        for row in range(1, 5):
            self.stats_panel.grid_rowconfigure(row, weight=1, minsize=CARD_HEIGHT)

        self._build_stats_panel()

        self.right_stack = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.right_stack.grid(row=0, column=1, sticky="nsew")
        self.right_stack.grid_rowconfigure(0, weight=1)
        self.right_stack.grid_rowconfigure(1, weight=1)
        self.right_stack.grid_columnconfigure(0, weight=1)

        self.log_panel = ctk.CTkFrame(
            self.right_stack,
            fg_color=SURFACE_COLOR,
            corner_radius=18,
            border_width=1,
            border_color=CARD_BORDER,
        )
        self.log_panel.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        self.log_panel.grid_rowconfigure(1, weight=1)
        self.log_panel.grid_columnconfigure(0, weight=1)
        self._build_log_panel()

        self.graph_panel = ctk.CTkFrame(
            self.right_stack,
            fg_color=SURFACE_COLOR,
            corner_radius=18,
            border_width=1,
            border_color=CARD_BORDER,
        )
        self.graph_panel.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.graph_panel.grid_rowconfigure(1, weight=1)
        self.graph_panel.grid_columnconfigure(0, weight=1)
        self._build_graph_panel()

    def _build_stats_panel(self) -> None:
        header = ctk.CTkFrame(self.stats_panel, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(18, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Stats",
            font=("Segoe UI", 16, "bold"),
            text_color=TEXT_COLOR,
        ).grid(row=0, column=0, sticky="w")

        self.metric_cards: dict[str, ctk.CTkLabel] = {}
        self._create_metric_card(1, 0, "Highest Hit", "highest_time", SUCCESS_COLOR, value_font=STAMP_FONT)
        self._create_metric_card(1, 1, "Last Cap Breach", "last_breach", LAST_BREACH_COLOR, value_font=STAMP_FONT)
        self._create_metric_card(2, 0, "Mean Damage", "mean", MEAN_COLOR)
        self._create_metric_card(2, 1, "Standard Deviation", "std_dev", DANGER_COLOR)
        self._create_metric_card(3, 0, "Hits Per Minute", "hits_per_min", TOTAL_COLOR)
        self._create_metric_card(3, 1, "Session Duration", "session", SESSION_COLOR, value_font=STAMP_FONT)
        self._create_metric_card(4, 0, "Top 3 Hits", "top_3", TOP5_COLOR, value_font=STAMP_FONT)
        self._create_metric_card(4, 1, "Above Cap Hits", "over_cap", OVER_CAP_COLOR, value_font=STAMP_FONT)

    def _create_metric_card(
        self,
        row: int,
        column: int,
        title: str,
        key: str,
        value_color: str,
        colspan: int = 1,
        value_font: tuple[str, int, str] | tuple[str, int] = STAT_VALUE_FONT,
        value_wraplength: int | None = None,
        value_justify: str = "left",
    ) -> None:
        card = ctk.CTkFrame(
            self.stats_panel,
            fg_color=CARD_COLOR,
            corner_radius=16,
            border_width=1,
            border_color=CARD_BORDER,
            height=CARD_HEIGHT,
        )
        card.grid_propagate(False)
        card.grid(row=row, column=column, columnspan=colspan, sticky="nsew", padx=10, pady=10)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            card,
            text=title,
            font=CARD_TITLE_FONT,
            text_color=MUTED_TEXT_COLOR,
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))

        value_kwargs = {
            "font": value_font,
            "text_color": value_color,
            "anchor": "w",
            "justify": value_justify,
        }
        if value_wraplength is not None:
            value_kwargs["wraplength"] = value_wraplength

        value_label = ctk.CTkLabel(
            card,
            text="0",
            **value_kwargs,
        )
        value_label.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 12))
        self.metric_cards[key] = value_label

    def _build_log_panel(self) -> None:
        header = ctk.CTkFrame(self.log_panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Log",
            font=("Segoe UI", 18, "bold"),
            text_color=TEXT_COLOR,
        ).grid(row=0, column=0, sticky="w")

        self.list_view = ctk.CTkTextbox(
            self.log_panel,
            state="disabled",
            fg_color=PLOT_BG,
            text_color=TEXT_COLOR,
            font=LOG_FONT,
            corner_radius=16,
            border_width=1,
            border_color=CARD_BORDER,
        )
        self.list_view.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.list_view.tag_config("Max", foreground=SUCCESS_COLOR)
        self.list_view.tag_config("Hit", foreground=TEXT_COLOR)
        self.list_view.tag_config("System", foreground=ACCENT_COLOR)
        self._seed_log_view()

    def _seed_log_view(self) -> None:
        self.list_view.configure(state="normal")
        self.list_view.delete("1.0", "end")

        if self.hit_events:
            running_max = 0
            wrote_any = False
            for event in self.hit_events:
                if not isinstance(event, dict):
                    continue
                value = event.get("value")
                if not isinstance(value, int):
                    continue

                timestamp = self._format_log_timestamp(event.get("display_timestamp") or event.get("timestamp"))
                raw_value = str(event.get("raw_value") or value)
                is_new_max = value >= running_max
                running_max = max(running_max, value)
                prefix = "New max" if is_new_max else "Hit"
                tag = "Max" if is_new_max else "Hit"
                self.list_view.insert(
                    "end",
                    f"{timestamp}  {prefix:<8}  {format_damage_value(value):<16} Raw: {raw_value}\n",
                    tag,
                )
                wrote_any = True

            if not wrote_any:
                self.list_view.insert(
                    "end",
                    "No saved hits yet. Watching EE.log for the first cap breach.\n",
                    "System",
                )
        else:
            self.list_view.insert(
                "end",
                "No hits yet. Watching EE.log for the first cap breach.\n",
                "System",
            )

        self.list_view.configure(state="disabled")

    def _build_graph_panel(self) -> None:
        header = ctk.CTkFrame(self.graph_panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 8))
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        ctk.CTkLabel(
            header,
            text="Trend",
            font=("Segoe UI", 18, "bold"),
            text_color=TEXT_COLOR,
        ).grid(row=0, column=0, sticky="w")

        self.graph_state_label = ctk.CTkLabel(
            header,
            text="",
            font=SMALL_FONT,
            text_color=MUTED_TEXT_COLOR,
        )
        self.graph_state_label.grid(row=0, column=1, sticky="e")

        self.fig, self.ax = plt.subplots(figsize=PLOT_FIGSIZE, facecolor=PLOT_BG)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.graph_panel)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))

        self.style_graph()

    def _build_footer(self) -> None:
        self.footer_frame = ctk.CTkFrame(
            self.app_frame,
            fg_color="transparent",
        )
        self.footer_frame.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.footer_frame.grid_columnconfigure(0, weight=1)
        self.footer_frame.grid_columnconfigure(1, weight=1)

        self.status_text = ctk.CTkLabel(
            self.footer_frame,
            text="",
            font=SMALL_FONT,
            text_color=MUTED_TEXT_COLOR,
            anchor="w",
        )
        self.status_text.grid(row=0, column=0, sticky="w")

        self.path_text = ctk.CTkLabel(
            self.footer_frame,
            text=f"Save: {self.save_path}",
            font=SMALL_FONT,
            text_color=MUTED_TEXT_COLOR,
            anchor="e",
        )
        self.path_text.grid(row=0, column=1, sticky="e")

    def _make_badge(self, parent, text: str, text_color: str, fill_color: str):
        badge = ctk.CTkFrame(
            parent,
            fg_color=fill_color,
            corner_radius=999,
            border_width=1,
            border_color=text_color,
        )
        badge.grid_columnconfigure(0, weight=1)

        label = ctk.CTkLabel(
            badge,
            text=text,
            font=("Segoe UI", 10, "bold"),
            text_color=text_color,
        )
        label.grid(row=0, column=0, padx=10, pady=4)
        return badge, label

    def reset_data(self) -> None:
        self.damage_history = [0]
        self.max_hit = 0
        self.hit_count = 0
        self.all_hits = 0
        self.hit_events = []
        self.session_started_at = datetime.now()
        self.last_cap_breach_at = None
        self.highest_hit_at = None

        self._seed_log_view()

        self.graph_state_label.configure(text="Reset complete")
        self._update_labels()
        self._draw_graph()

    def style_graph(self) -> None:
        self.ax.set_facecolor(PLOT_BG)
        self.ax.tick_params(colors=TEXT_COLOR, which="both", labelsize=10)
        self.ax.xaxis.label.set_color(TEXT_COLOR)
        self.ax.yaxis.label.set_color(TEXT_COLOR)
        self.ax.yaxis.set_major_formatter(FuncFormatter(self._format_axis_label))
        self.ax.grid(True, color=GRID_COLOR, linestyle="--", alpha=0.35)

        for spine in ("top", "right"):
            self.ax.spines[spine].set_visible(False)
        self.ax.spines["left"].set_color(CARD_BORDER)
        self.ax.spines["bottom"].set_color(CARD_BORDER)

    @staticmethod
    def _format_axis_label(value: float, _pos: int = 0) -> str:
        return format_damage_value(value)

    def _draw_graph(self) -> None:
        self.ax.clear()
        self.style_graph()

        history = self.damage_history or [0]
        x_values = list(range(len(history)))

        self.ax.plot(
            x_values,
            history,
            color=HISTORY_COLOR,
            linewidth=2.8,
            marker="o",
            markersize=3,
            markerfacecolor=TEXT_COLOR,
            markeredgewidth=0,
        )
        self.ax.fill_between(x_values, history, color=HISTORY_COLOR, alpha=0.08)

        self.ax.set_xlim(left=0, right=max(1, len(history) - 1))
        self.ax.margins(x=0.02, y=0.12)
        self.ax.set_xticks([])
        self.ax.set_title("Recent hit history", color=TEXT_COLOR, loc="left", fontsize=12, pad=8)

        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _start_log_listener(self) -> None:
        self._log_thread = threading.Thread(target=self._monitor_log_file, daemon=True)
        self._log_thread.start()

    def _monitor_log_file(self) -> None:
        while not self._stop_event.is_set():
            if not self.log_path.exists():
                time.sleep(0.5)
                continue

            try:
                with self.log_path.open("r", encoding="utf-8", errors="ignore") as log_file:
                    log_file.seek(0, os.SEEK_END)
                    last_position = log_file.tell()

                    while not self._stop_event.is_set():
                        line = log_file.readline()
                        if line:
                            last_position = log_file.tell()
                            if "after illumination" in line:
                                continue

                            parsed = parse_damage_line(line)
                            if parsed is not None:
                                value, raw_value = parsed
                                self.after(0, self.update_data, value, raw_value)
                            continue

                        try:
                            current_size = self.log_path.stat().st_size
                        except OSError:
                            break

                        if current_size < last_position:
                            break

                        time.sleep(0.25)
            except OSError:
                time.sleep(0.5)

    def update_data(self, value: int, raw_value: str) -> None:
        if self._stop_event.is_set():
            return

        self.damage_history.append(value)
        if len(self.damage_history) > MAX_HISTORY_POINTS:
            self.damage_history.pop(0)

        timestamp = datetime.now()
        timestamp_text = timestamp.strftime("%Y-%m-%d %H:%M")
        event = {"timestamp": timestamp.isoformat(timespec="seconds"), "display_timestamp": timestamp_text, "value": value, "raw_value": raw_value}
        self.hit_events.append(event)

        self.all_hits += value
        self.hit_count += 1
        self.last_cap_breach_at = timestamp

        if value > self.max_hit:
            self.max_hit = value
            self.highest_hit_at = timestamp
        elif value == self.max_hit:
            self.highest_hit_at = timestamp

        self._append_log_entry(timestamp_text, value, raw_value, value == self.max_hit)
        self.graph_state_label.configure(text=f"Latest cap breach: {format_damage_value(value)}")
        self._update_labels(recent_value=value)
        self._draw_graph()

    def _append_log_entry(self, timestamp: str, value: int, raw_value: str, is_new_max: bool) -> None:
        label = "Max" if is_new_max else "Hit"
        prefix = "New max" if is_new_max else "Hit"
        formatted_value = format_damage_value(value)

        self.list_view.configure(state="normal")
        self.list_view.insert(
            "end",
            f"{timestamp}  {prefix:<8}  {formatted_value:<16} Raw: {raw_value}\n",
            label,
        )
        self.list_view.see("end")
        self.list_view.configure(state="disabled")

    def _update_labels(self, recent_value: int | None = None) -> None:
        recent = self.recent_hit if recent_value is None else recent_value
        session_text = self._format_duration(self.session_duration)
        hits_per_minute_text = f"{self.hits_per_minute:.1f}"
        mean_text = self._format_stat_value(self.average_hit)
        std_text = self._format_stat_value(self.std_deviation)

        self.metric_cards["session"].configure(text=session_text)
        self.metric_cards["hits_per_min"].configure(text=hits_per_minute_text)
        self.metric_cards["mean"].configure(text=mean_text)
        self.metric_cards["std_dev"].configure(text=std_text)
        self.metric_cards["highest_time"].configure(text=format_damage_value(self.max_hit))
        self.metric_cards["last_breach"].configure(text=format_damage_value(recent))
        self.metric_cards["top_3"].configure(text=self._top_hits_text())
        self.metric_cards["over_cap"].configure(text=self._format_stat_value(self.over_cap_count))

        self.status_text.configure(
            text=f"{self.over_cap_count} hits • total {self._format_stat_value(self.all_hits)} • recent {format_damage_value(recent)} • mean {mean_text} • stdev {std_text}"
        )
        if self._stop_event.is_set():
            status_text = "Closing"
            status_color = MUTED_TEXT_COLOR
            status_fill = SURFACE_ALT_COLOR
        elif self.log_path.exists():
            status_text = "Found EE.log"
            status_color = ACCENT_COLOR
            status_fill = SURFACE_ALT_COLOR
        else:
            status_text = "Waiting for EE.log"
            status_color = MUTED_TEXT_COLOR
            status_fill = SURFACE_ALT_COLOR

        self.log_status_label.configure(text=status_text, text_color=status_color)
        self.log_status_frame.configure(fg_color=status_fill, border_color=status_color)

    def on_closing(self) -> None:
        save_state(
            self.save_path,
            {
                "damage_history": self.damage_history,
                "max_hit": self.max_hit,
                "hit_count": self.hit_count,
                "all_hits": self.all_hits,
                "hit_events": self.hit_events,
                "session_started_at": self.session_started_at.isoformat(timespec="seconds"),
            },
        )

        self._stop_event.set()
        if self._log_thread and self._log_thread.is_alive():
            self._log_thread.join(timeout=1.0)
        self.quit()


if __name__ == "__main__":
    app = DamageTracker()
    app.mainloop()
