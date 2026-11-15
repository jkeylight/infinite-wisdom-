"""Infinite Wisdom Converter — Windows GUI (M6, redesigned).

Modern design system (SOTD-level polish):
- Deep ink background, warm-white text, champagne-gold accent
- Card-based layout, generous spacing, rounded corners
- Status pills (custom delegate), gradient primary button, slim progress
- Virtualized queue (QTableView), throttled log/stats — GUI never lags

Run:  python -m converter.gui   (or Converter.exe / run.bat)
CLI twin (same engine):  python -m converter <folder> -o <output>
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QAbstractTableModel, QModelIndex, QRectF
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPlainTextEdit, QProgressBar, QPushButton,
    QSlider, QStyledItemDelegate, QStyle, QTableView, QVBoxLayout, QWidget, QDialog,
    QDialogButtonBox, QStyleOptionViewItem,
)

from .bulk import output_dir_for, scan_inputs
from .config import load_config, save_config
from .engine import ConvertOptions
from .gui_bulk import BulkController

# ---------------------------------------------------------------- design tokens
BG = "#0f0e14"
SURFACE = "#17161e"
SURFACE2 = "#1e1d28"
SURFACE3 = "#262433"
BORDER = "#2e2b3d"
BORDER_SOFT = "#232130"
TEXT = "#f2ede3"
TEXT_DIM = "#a8a29e"
TEXT_FAINT = "#7a768a"
GOLD = "#d6b48c"
GOLD_DARK = "#b8935f"
GOLD_LIGHT = "#ecd3a8"
GREEN = "#8fc97f"
RED = "#f08a8a"
BLUE = "#8fb0f0"

COLUMNS = ["File", "Type", "Size", "Status", "Images", "Time", "Output"]
STATUS_ICON = {"queued": "○", "running": "◌", "ok": "✓", "failed": "✗", "skipped": "↷"}
STATUS_COLORS = {
    "queued": ("#2e2b3d", "#a8a29e"),
    "running": ("#24304d", "#8fb0f0"),
    "ok": ("#1e3324", "#8fc97f"),
    "failed": ("#3d2222", "#f08a8a"),
    "skipped": ("#2a2838", "#9a95a8"),
}


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class StatusDelegate(QStyledItemDelegate):
    """Draws the Status column as a rounded pill badge; other columns default."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        if index.column() != 3:
            super().paint(painter, option, index)
            return
        text = index.data(Qt.DisplayRole) or ""
        status = text.split()[-1] if text else "queued"
        bg, fg = STATUS_COLORS.get(status, STATUS_COLORS["queued"])
        painter.save()
        # Row background (selected / hover handled by view palette)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#2e2b3d"))
        else:
            painter.fillRect(option.rect, QColor(SURFACE2) if index.row() % 2 == 0 else QColor("#1a1924"))
        # Pill
        r = QRectF(option.rect)
        r.setX(r.x() + 10)
        r.setWidth(min(r.width() - 20, 110))
        r.setY(r.y() + 5)
        r.setHeight(r.height() - 10)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(bg))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(r, 9, 9)
        painter.setPen(QColor(fg))
        font = QFont(option.font)
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(r, Qt.AlignCenter, text)
        painter.restore()


class QueueModel(QAbstractTableModel):
    """Virtualized queue model — data() is O(1), view renders visible rows only."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or not index.isValid():
            return None
        r = self.rows[index.row()]
        col = index.column()
        if col == 0:
            return r["name"]
        if col == 1:
            return r["type"].upper()
        if col == 2:
            return _fmt_size(r["size"])
        if col == 3:
            return f"{STATUS_ICON.get(r['status'], '?')} {r['status']}"
        if col == 4:
            return str(r["images"]) if r["status"] == "ok" else ""
        if col == 5:
            return f"{r['duration']:.2f}s" if r["status"] == "ok" else ""
        if col == 6:
            return r.get("error") or r.get("output", "")
        return None

    def add_paths(self, paths: list[Path]) -> int:
        existing = {r["path"] for r in self.rows}
        added = 0
        for p in paths:
            key = str(p.resolve()) if p.exists() else str(p)
            if key in existing:
                continue
            try:
                size = p.stat().st_size if p.exists() else 0
            except OSError:
                size = 0
            self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
            self.rows.append({
                "path": key, "name": p.name, "type": p.suffix.lstrip(".").lower(),
                "size": size, "status": "queued", "images": 0, "duration": 0.0,
                "output": "", "error": "", "src": p,
            })
            self.endInsertRows()
            added += 1
        return added

    def update_row(self, row: int, result) -> None:
        if not (0 <= row < len(self.rows)):
            return
        r = self.rows[row]
        r["status"] = result.status
        r["images"] = result.images
        r["duration"] = result.duration_sec
        r["output"] = result.output_dir
        r["error"] = result.error
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, self.index(row, len(COLUMNS) - 1))

    def set_status(self, row: int, status: str) -> None:
        if 0 <= row < len(self.rows):
            self.rows[row]["status"] = status
            idx = self.index(row, 3)
            self.dataChanged.emit(idx, idx)

    def clear_finished(self) -> None:
        keep = [r for r in self.rows if r["status"] not in ("ok", "skipped")]
        if len(keep) != len(self.rows):
            self.beginResetModel()
            self.rows = keep
            self.endResetModel()

    def clear_all(self) -> int:
        n = len(self.rows)
        if n:
            self.beginResetModel()
            self.rows = []
            self.endResetModel()
        return n

    def failed_paths(self) -> list[Path]:
        return [r["src"] for r in self.rows if r["status"] == "failed"]

    def queued_tasks(self, output_root: Path, layout: str, input_roots: list[Path]):
        from collections import Counter
        queued = [(i, r) for i, r in enumerate(self.rows) if r["status"] in ("queued", "failed")]
        base_dirs = [output_dir_for(r["src"], output_root, layout, input_roots) for _, r in queued]
        counts = Counter(str(d).lower() for d in base_dirs)
        tasks = []
        for (row, r), base in zip(queued, base_dirs):
            src = r["src"]
            stem = src.stem if counts[str(base).lower()] <= 1 else f"{src.stem}-{src.suffix.lstrip('.').lower()}"
            tasks.append((row, src, output_dir_for(src, output_root, layout, input_roots, stem=stem)))
        return tasks


def _card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f


class MainWindow(QMainWindow):
    def __init__(self, config: dict | None = None):
        super().__init__()
        self.setWindowTitle("Infinite Wisdom — EPUB/PDF → TXT Converter")
        self.resize(1220, 820)
        self.model = QueueModel(self)
        self.controller = BulkController(self)
        self._log_buffer: list[str] = []
        self._input_roots: list[Path] = []
        self._config = config if config is not None else load_config()
        self._build_ui()
        self._connect()
        self._apply_theme()
        self._apply_config()

    def _apply_config(self) -> None:
        cfg = self._config
        if cfg.get("output_folder"):
            self.output_edit.setText(str(cfg["output_folder"]))
        if cfg.get("layout") in ("mirror", "flat", "same"):
            self.layout_combo.setCurrentText(cfg["layout"])
        if cfg.get("preset") in ("fast", "balanced", "best"):
            self.preset_combo.setCurrentText(cfg["preset"])
        try:
            w = int(cfg.get("workers") or 0)
            if w:
                self.workers_slider.setValue(max(1, min(w, self.workers_slider.maximum())))
        except Exception:
            pass
        self.text_only_chk.setChecked(bool(cfg.get("text_only")))
        self.skip_chk.setChecked(bool(cfg.get("skip_existing", True)))
        self.flat_chk.setChecked(bool(cfg.get("flat_txt")))

    def _collect_config(self) -> dict:
        return {
            "output_folder": self.output_edit.text(),
            "layout": self.layout_combo.currentText(),
            "preset": self.preset_combo.currentText(),
            "workers": self.workers_slider.value(),
            "text_only": self.text_only_chk.isChecked(),
            "skip_existing": self.skip_chk.isChecked(),
            "flat_txt": self.flat_chk.isChecked(),
        }

    def closeEvent(self, event) -> None:  # noqa: N802
        save_config(self._collect_config())
        super().closeEvent(event)

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        # --- Header ---
        header = QHBoxLayout()
        logo = QLabel("∞")
        logo.setObjectName("logo")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(46, 46)
        header.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("Infinite Wisdom")
        title.setObjectName("appTitle")
        sub = QLabel("EPUB / PDF  →  TXT  ·  BULK CONVERTER")
        sub.setObjectName("appSub")
        titles.addWidget(title)
        titles.addWidget(sub)
        header.addLayout(titles)
        header.addStretch()
        badge = QLabel("  v1.1.0  ·  WINDOWS PERSONAL  ")
        badge.setObjectName("badge")
        header.addWidget(badge)
        root.addLayout(header)

        # --- Drop zone (hero card) ---
        drop_card = _card()
        drop_card.setObjectName("dropCard")
        drop_layout = QVBoxLayout(drop_card)
        drop_layout.setContentsMargins(20, 18, 20, 18)
        self.drop_label = QLabel(
            '<span style="font-size:26px; color:#d6b48c;">⬇</span><br/>'
            '<span style="font-size:15px; font-weight:600; color:#f2ede3;">Drop EPUB / PDF books here</span><br/>'
            '<span style="font-size:11px; color:#a8a29e;">files or folders — folders are scanned recursively · or use Add buttons below</span>'
        )
        self.drop_label.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(self.drop_label)
        root.addWidget(drop_card)

        # --- Options card ---
        opt_card = _card()
        opt_layout = QVBoxLayout(opt_card)
        opt_layout.setContentsMargins(18, 14, 18, 14)
        opt_layout.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        row1.addWidget(QLabel("Output"), )
        self.output_edit = QLineEdit(str(Path.cwd() / "Converted"))
        self.output_edit.setPlaceholderText("Output folder…")
        row1.addWidget(self.output_edit, 1)
        browse = QPushButton("Browse…")
        browse.setObjectName("ghost")
        browse.clicked.connect(self._browse_output)
        row1.addWidget(browse)
        row1.addWidget(QLabel("Layout"))
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["mirror", "flat", "same"])
        row1.addWidget(self.layout_combo)
        row1.addWidget(QLabel("Preset"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["fast", "balanced", "best"])
        self.preset_combo.setCurrentText("balanced")
        row1.addWidget(self.preset_combo)
        opt_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        add_files = QPushButton("+  Add Files…")
        add_files.setObjectName("ghost")
        add_files.clicked.connect(self._add_files_dialog)
        row2.addWidget(add_files)
        add_folder = QPushButton("+  Add Folder…")
        add_folder.setObjectName("ghost")
        add_folder.clicked.connect(self._add_folder_dialog)
        row2.addWidget(add_folder)
        row2.addWidget(QLabel("Workers"))
        self.workers_slider = QSlider(Qt.Horizontal)
        max_w = max(1, os.cpu_count() or 2)
        self.workers_slider.setRange(1, max_w)
        self.workers_slider.setValue(max(1, max_w - 1))
        self.workers_slider.setFixedWidth(150)
        row2.addWidget(self.workers_slider)
        self.workers_label = QLabel(str(self.workers_slider.value()))
        self.workers_label.setObjectName("workersVal")
        self.workers_label.setFixedWidth(22)
        row2.addWidget(self.workers_label)
        self.workers_slider.valueChanged.connect(lambda v: self.workers_label.setText(str(v)))
        self.text_only_chk = QCheckBox("Text-only")
        row2.addWidget(self.text_only_chk)
        self.skip_chk = QCheckBox("Skip converted")
        self.skip_chk.setChecked(True)
        row2.addWidget(self.skip_chk)
        self.flat_chk = QCheckBox("Flat TXT copy")
        row2.addWidget(self.flat_chk)
        row2.addStretch()
        opt_layout.addLayout(row2)
        root.addWidget(opt_card)

        # --- Queue card ---
        queue_card = _card()
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(0)
        qhead = QHBoxLayout()
        qhead.setContentsMargins(18, 12, 18, 10)
        self.queue_title = QLabel("Queue")
        self.queue_title.setObjectName("cardTitle")
        qhead.addWidget(self.queue_title)
        qhead.addStretch()
        self.clear_btn = QPushButton("Clear Finished")
        self.clear_btn.setObjectName("ghostSmall")
        self.clear_all_btn = QPushButton("🗑 Clear All")
        self.clear_all_btn.setObjectName("ghostSmall")
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.setObjectName("ghostSmall")
        qhead.addWidget(self.clear_btn)
        qhead.addWidget(self.clear_all_btn)
        qhead.addWidget(self.clear_log_btn)
        queue_layout.addLayout(qhead)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.doubleClicked.connect(self._preview_row)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setItemDelegate(StatusDelegate(self.table))
        # Column widths: File wide, Output wide, others compact
        widths = [260, 70, 80, 130, 70, 70, 320]
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)
        queue_layout.addWidget(self.table, 3)
        root.addWidget(queue_card, 3)

        # --- Controls ---
        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)
        self.start_btn = QPushButton("▶  Start Conversion")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(42)
        self.pause_btn = QPushButton("⏸  Pause")
        self.pause_btn.setObjectName("ghost")
        self.resume_btn = QPushButton("▶  Resume")
        self.resume_btn.setObjectName("ghost")
        self.cancel_btn = QPushButton("✕  Cancel")
        self.cancel_btn.setObjectName("danger")
        self.retry_btn = QPushButton("↻  Retry Failed")
        self.retry_btn.setObjectName("ghost")
        for b in (self.pause_btn, self.resume_btn, self.cancel_btn, self.retry_btn):
            b.setEnabled(False)
        ctrl.addWidget(self.start_btn)
        ctrl.addWidget(self.pause_btn)
        ctrl.addWidget(self.resume_btn)
        ctrl.addWidget(self.cancel_btn)
        ctrl.addWidget(self.retry_btn)
        ctrl.addStretch()
        root.addLayout(ctrl)

        # --- Progress + stats ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(10)
        self.progress.setTextVisible(False)
        root.addWidget(self.progress)
        self.stats_label = QLabel("Ready — drop files or folders to begin.")
        self.stats_label.setObjectName("stats")
        root.addWidget(self.stats_label)

        # --- Log card ---
        log_card = _card()
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(18, 10, 18, 12)
        log_layout.setSpacing(6)
        log_head = QHBoxLayout()
        log_title = QLabel("Log")
        log_title.setObjectName("cardTitle")
        log_head.addWidget(log_title)
        log_head.addStretch()
        log_layout.addLayout(log_head)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(2000)
        self.log_edit.setFixedHeight(105)
        self.log_edit.setObjectName("log")
        log_layout.addWidget(self.log_edit)
        root.addWidget(log_card, 1)

        # Timers: log flush 200ms, stats 500ms — GUI never lags on bulk
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(200)
        self._log_timer.timeout.connect(self._flush_log)
        self._log_timer.start()
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(500)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background: {BG}; }}
            QWidget#central {{ background: {BG}; }}
            QLabel {{ color: {TEXT}; font-family: "Segoe UI", sans-serif; }}
            QLabel#logo {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {GOLD_LIGHT}, stop:1 {GOLD_DARK});
                color: #17161e; font-size: 26px; font-weight: bold; border-radius: 23px;
            }}
            QLabel#appTitle {{ font-size: 21px; font-weight: 700; color: {TEXT}; }}
            QLabel#appSub {{ font-size: 10px; color: {TEXT_FAINT}; font-weight: 600; }}
            QLabel#badge {{
                background: {SURFACE2}; color: {GOLD}; border: 1px solid {BORDER};
                border-radius: 11px; padding: 5px 10px; font-size: 10px; font-weight: 700;
            }}
            QFrame#card {{
                background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: 14px;
            }}
            QFrame#dropCard {{
                background: {SURFACE}; border: 1.5px dashed {GOLD_DARK}; border-radius: 14px;
            }}
            QLabel#cardTitle {{ font-size: 12px; font-weight: 700; color: {GOLD}; }}
            QLabel#stats {{ font-size: 12px; color: {TEXT_DIM}; }}
            QLabel#workersVal {{ font-size: 12px; font-weight: 700; color: {GOLD}; }}
            QLineEdit, QComboBox {{
                background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 9px; padding: 7px 10px; font-size: 12px;
            }}
            QLineEdit:focus, QComboBox:focus {{ border: 1px solid {GOLD_DARK}; }}
            QComboBox::drop-down {{ border: none; width: 22px; }}
            QComboBox QAbstractItemView {{ background: {SURFACE2}; color: {TEXT};
                selection-background-color: {SURFACE3}; border: 1px solid {BORDER}; }}
            QPushButton {{
                border-radius: 10px; padding: 8px 14px; font-size: 12px; font-weight: 600;
                font-family: "Segoe UI", sans-serif;
            }}
            QPushButton#primary {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {GOLD_LIGHT}, stop:1 {GOLD});
                color: #17161e; border: none; font-size: 13px; font-weight: 800; padding: 10px 22px;
            }}
            QPushButton#primary:hover:!disabled {{ background: {GOLD_LIGHT}; }}
            QPushButton#primary:disabled {{ background: {SURFACE3}; color: {TEXT_FAINT}; }}
            QPushButton#ghost {{
                background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER};
            }}
            QPushButton#ghost:hover:!disabled {{ border: 1px solid {GOLD_DARK}; color: {GOLD_LIGHT}; }}
            QPushButton#ghost:disabled {{ color: {TEXT_FAINT}; border: 1px solid {BORDER_SOFT}; }}
            QPushButton#danger {{
                background: transparent; color: {RED}; border: 1px solid #4a2e2e;
            }}
            QPushButton#danger:hover:!disabled {{ border: 1px solid {RED}; }}
            QPushButton#danger:disabled {{ color: {TEXT_FAINT}; border: 1px solid {BORDER_SOFT}; }}
            QPushButton#ghostSmall {{
                background: transparent; color: {TEXT_DIM}; border: 1px solid {BORDER_SOFT};
                padding: 5px 10px; font-size: 11px;
            }}
            QPushButton#ghostSmall:hover {{ color: {GOLD_LIGHT}; border: 1px solid {GOLD_DARK}; }}
            QTableView {{
                background: {SURFACE2}; color: {TEXT}; border: none; border-radius: 0 0 14px 14px;
                font-size: 12px; outline: none;
            }}
            QTableView::item {{ border: none; padding: 4px 8px; }}
            QTableView::item:selected {{ background: {SURFACE3}; color: {TEXT}; }}
            QHeaderView::section {{
                background: {SURFACE}; color: {TEXT_FAINT}; border: none;
                border-bottom: 1px solid {BORDER_SOFT}; padding: 8px; font-size: 10px;
                font-weight: 700; text-transform: uppercase;
            }}
            QProgressBar {{
                background: {SURFACE2}; border: 1px solid {BORDER_SOFT}; border-radius: 5px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {GOLD_DARK}, stop:1 {GOLD_LIGHT});
                border-radius: 4px;
            }}
            QPlainTextEdit#log {{
                background: #0c0b10; color: #b8b2a8; border: 1px solid {BORDER_SOFT};
                border-radius: 9px; padding: 6px; font-family: "Cascadia Code", "Consolas", monospace;
                font-size: 11px;
            }}
            QCheckBox {{ color: {TEXT_DIM}; font-size: 12px; spacing: 6px; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px; border-radius: 5px;
                border: 1.5px solid {BORDER}; background: {SURFACE2};
            }}
            QCheckBox::indicator:checked {{
                background: {GOLD}; border: 1.5px solid {GOLD};
            }}
            QSlider::groove:horizontal {{ height: 5px; background: {SURFACE3}; border-radius: 2px; }}
            QSlider::handle:horizontal {{
                width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
                background: {GOLD}; border: 2px solid {BG};
            }}
            QSlider::sub-page:horizontal {{ background: {GOLD_DARK}; border-radius: 2px; }}
            QScrollBar:vertical {{ background: {SURFACE}; width: 10px; border-radius: 5px; }}
            QScrollBar::handle:vertical {{ background: {SURFACE3}; border-radius: 5px; min-height: 30px; }}
            QScrollBar::handle:vertical:hover {{ background: {GOLD_DARK}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar:horizontal {{ background: {SURFACE}; height: 10px; border-radius: 5px; }}
            QScrollBar::handle:horizontal {{ background: {SURFACE3}; border-radius: 5px; min-width: 30px; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        """)

    def _connect(self):
        self.start_btn.clicked.connect(self._start)
        self.pause_btn.clicked.connect(self.controller.pause)
        self.resume_btn.clicked.connect(self.controller.resume)
        self.cancel_btn.clicked.connect(self.controller.cancel)
        self.retry_btn.clicked.connect(self._retry_failed)
        self.clear_btn.clicked.connect(self.model.clear_finished)
        self.clear_all_btn.clicked.connect(self._clear_all)
        self.clear_log_btn.clicked.connect(self._clear_log)
        self.controller.file_finished.connect(self._on_file_finished)
        self.controller.file_started.connect(lambda row: self.model.set_status(row, "running"))
        self.controller.progress.connect(self._on_progress)
        self.controller.log_message.connect(self._log)
        self.controller.finished.connect(self._on_finished)
        self.controller.state_changed.connect(self._on_state)
        self.model.rowsChanged = getattr(self.model, "rowsChanged", None)

    # ---------- Add files ----------
    def _add_paths(self, paths: list[str]) -> None:
        files = scan_inputs(paths)
        for p in paths:
            pp = Path(p)
            if pp.is_dir() and pp not in self._input_roots:
                self._input_roots.append(pp)
        added = self.model.add_paths(files)
        self._log(f"Added {added} file(s) to queue (total {self.model.rowCount()}).")
        self.queue_title.setText(f"Queue  ·  {self.model.rowCount()} file(s)")
        self._update_stats()

    def _add_files_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add EPUB/PDF files", "",
                                                "Books (*.epub *.pdf)")
        if files:
            self._add_paths(files)

    def _add_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Add folder (recursive)")
        if folder:
            self._add_paths([folder])

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Output folder")
        if folder:
            self.output_edit.setText(folder)

    # Drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            self._add_paths(paths)
            event.acceptProposedAction()

    # ---------- Run control ----------
    def _start(self):
        if self.model.rowCount() == 0:
            self._log("Queue is empty — add files/folders first.")
            return
        output_root = Path(self.output_edit.text())
        tasks = self.model.queued_tasks(output_root, self.layout_combo.currentText(), self._input_roots)
        if not tasks:
            self._log("Nothing queued (all done/skipped). Use Retry Failed or Clear + re-add.")
            return
        options = ConvertOptions(preset=self.preset_combo.currentText(),
                                 text_only=self.text_only_chk.isChecked(),
                                 flat_txt_dir=str(output_root) if self.flat_chk.isChecked() else "")
        save_config(self._collect_config())
        self.progress.setRange(0, len(tasks))
        self.progress.setValue(0)
        self._log(f"Starting {len(tasks)} file(s), workers={self.workers_slider.value()}, "
                  f"preset={options.preset}, text_only={options.text_only}")
        self.controller.start(tasks, options, workers=self.workers_slider.value(),
                              skip_existing=self.skip_chk.isChecked())

    def _retry_failed(self):
        failed = self.model.failed_paths()
        if failed:
            self._log(f"Re-queueing {len(failed)} failed file(s).")
            self._start()

    def _clear_all(self) -> None:
        if self.controller.state in ("running", "paused"):
            self._log("Cannot clear while converting — Cancel first.")
            return
        n = self.model.clear_all()
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.stats_label.setText("Queue cleared. Drop files/folders to begin.")
        self.queue_title.setText("Queue")
        self._log(f"Cleared {n} file(s) from queue.")

    def _clear_log(self) -> None:
        self._log_buffer.clear()
        self.log_edit.clear()

    def _on_file_finished(self, row: int, result) -> None:
        self.model.update_row(row, result)
        if result.status == "ok":
            self._log(f"✓ {Path(result.source).name} ({result.duration_sec:.2f}s, {result.images} images)")
        elif result.status == "skipped":
            self._log(f"↷ {Path(result.source).name} (already converted)")
        else:
            self._log(f"✗ {Path(result.source).name}: {result.error}")

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setValue(done)

    def _on_finished(self, summary: dict) -> None:
        msg = (f"Finished: {summary['ok']} converted, {summary['failed']} failed, "
               f"{summary['skipped']} skipped in {summary['elapsed']:.1f}s"
               + (" (cancelled)" if summary["cancelled"] else ""))
        self._log(msg)
        self.stats_label.setText(msg)

    def _on_state(self, state: str) -> None:
        running = state in ("running", "paused", "cancelling")
        self.start_btn.setEnabled(not running)
        self.pause_btn.setEnabled(state == "running")
        self.resume_btn.setEnabled(state == "paused")
        self.cancel_btn.setEnabled(running)
        self.retry_btn.setEnabled(state == "idle")

    # ---------- Log / stats (throttled) ----------
    def _log(self, msg: str) -> None:
        self._log_buffer.append(msg)

    def _flush_log(self) -> None:
        if self._log_buffer:
            self.log_edit.appendPlainText("\n".join(self._log_buffer))
            self._log_buffer.clear()

    def _update_stats(self) -> None:
        if self.controller.state in ("running", "paused"):
            done = self.progress.value()
            total = self.progress.maximum()
            elapsed = self.controller.elapsed
            rate = done / elapsed if elapsed > 0 and done else 0
            eta = (total - done) / rate if rate else 0
            state = "Paused" if self.controller.state == "paused" else "Running"
            self.stats_label.setText(
                f"{state}: {done}/{total} · {rate:.1f} files/min · ETA {int(eta//60)}:{int(eta%60):02d}")

    # ---------- Preview ----------
    def _preview_row(self, index: QModelIndex) -> None:
        row = index.row()
        if not (0 <= row < len(self.model.rows)):
            return
        r = self.model.rows[row]
        txt_path = None
        if r.get("output"):
            from .engine import txt_filename_for
            out_dir = Path(r["output"])
            for cand in (out_dir / txt_filename_for(out_dir), out_dir / "content.txt"):
                if cand.exists():
                    txt_path = cand
                    break
            else:
                txt_path = out_dir / txt_filename_for(out_dir)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Preview — {r['name']}")
        dlg.resize(700, 500)
        layout = QVBoxLayout(dlg)
        info = QLabel(f"Status: {r['status']} · Images: {r['images']} · "
                      f"Output: {r.get('output') or '(not converted yet)'}")
        layout.addWidget(info)
        edit = QPlainTextEdit()
        edit.setReadOnly(True)
        if txt_path and txt_path.exists():
            text = txt_path.read_text(encoding="utf-8", errors="replace")
            edit.setPlainText(text[:8000] + ("\n… (truncated)" if len(text) > 8000 else ""))
        else:
            edit.setPlainText("No output yet. Convert this file first, then double-click to preview.")
        layout.addWidget(edit)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        dlg.exec()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Infinite Wisdom Converter")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
