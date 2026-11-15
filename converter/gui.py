"""Infinite Wisdom Converter — Windows GUI (M6).

Bulk-first, no-lag design:
- QTableView + QAbstractTableModel (virtualized: only visible rows render)
- All conversion in BulkController background thread + ProcessPool workers
- GUI thread only draws; log/stats throttled via QTimer
- Pause stops submitting new files; in-flight files finish cleanly

Run:  python -m converter.gui   (or Converter.exe in the portable build)
CLI twin (same engine):  python -m converter <folder> -o <output>
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPlainTextEdit, QProgressBar, QPushButton,
    QSlider, QTableView, QVBoxLayout, QWidget, QDialog, QDialogButtonBox,
)

from .bulk import output_dir_for, scan_inputs
from .config import load_config, save_config
from .engine import ConvertOptions
from .gui_bulk import BulkController

COLUMNS = ["File", "Type", "Size", "Status", "Images", "Time", "Output"]
STATUS_ICON = {"queued": "○", "running": "◌", "ok": "✓", "failed": "✗", "skipped": "↷"}


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


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
        """Add files (already scanned). Returns number added."""
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

    def failed_paths(self) -> list[Path]:
        return [r["src"] for r in self.rows if r["status"] == "failed"]

    def queued_tasks(self, output_root: Path, layout: str, input_roots: list[Path]):
        """Build (row, src, out_dir) tasks for queued rows, with collision-safe stems."""
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


class MainWindow(QMainWindow):
    def __init__(self, config: dict | None = None):
        super().__init__()
        self.setWindowTitle("Infinite Wisdom — EPUB/PDF → TXT Converter")
        self.resize(1100, 700)
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

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        save_config(self._collect_config())
        super().closeEvent(event)

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Drop hint
        self.drop_label = QLabel("Drop EPUB/PDF files or folders here — or use Add buttons below")
        self.drop_label.setAlignment(Qt.AlignCenter)
        self.drop_label.setMinimumHeight(56)
        root.addWidget(self.drop_label)

        # Options row 1: output + layout + preset
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Output:"))
        self.output_edit = QLineEdit(str(Path.cwd() / "Converted"))
        row1.addWidget(self.output_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_output)
        row1.addWidget(browse)
        row1.addWidget(QLabel("Layout:"))
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["mirror", "flat", "same"])
        row1.addWidget(self.layout_combo)
        row1.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["fast", "balanced", "best"])
        self.preset_combo.setCurrentText("balanced")
        row1.addWidget(self.preset_combo)
        root.addLayout(row1)

        # Options row 2: workers + toggles + add buttons
        row2 = QHBoxLayout()
        add_files = QPushButton("Add Files…")
        add_files.clicked.connect(self._add_files_dialog)
        row2.addWidget(add_files)
        add_folder = QPushButton("Add Folder…")
        add_folder.clicked.connect(self._add_folder_dialog)
        row2.addWidget(add_folder)
        row2.addWidget(QLabel("Workers:"))
        self.workers_slider = QSlider(Qt.Horizontal)
        max_w = max(1, os.cpu_count() or 2)
        self.workers_slider.setRange(1, max_w)
        self.workers_slider.setValue(max(1, max_w - 1))
        self.workers_slider.setFixedWidth(140)
        row2.addWidget(self.workers_slider)
        self.workers_label = QLabel(str(self.workers_slider.value()))
        row2.addWidget(self.workers_label)
        self.workers_slider.valueChanged.connect(lambda v: self.workers_label.setText(str(v)))
        self.text_only_chk = QCheckBox("Text-only (fastest)")
        row2.addWidget(self.text_only_chk)
        self.skip_chk = QCheckBox("Skip already converted")
        self.skip_chk.setChecked(True)
        row2.addWidget(self.skip_chk)
        self.flat_chk = QCheckBox("Also copy TXT to output root (flat)")
        row2.addWidget(self.flat_chk)
        row2.addStretch()
        root.addLayout(row2)

        # Queue table (virtualized)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.doubleClicked.connect(self._preview_row)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 3)

        # Controls
        ctrl = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start")
        self.pause_btn = QPushButton("⏸ Pause")
        self.resume_btn = QPushButton("▶ Resume")
        self.cancel_btn = QPushButton("✕ Cancel")
        self.retry_btn = QPushButton("↻ Retry Failed")
        self.clear_btn = QPushButton("Clear Finished")
        for b in (self.pause_btn, self.resume_btn, self.cancel_btn, self.retry_btn, self.clear_btn):
            b.setEnabled(False)
        ctrl.addWidget(self.start_btn)
        ctrl.addWidget(self.pause_btn)
        ctrl.addWidget(self.resume_btn)
        ctrl.addWidget(self.cancel_btn)
        ctrl.addWidget(self.retry_btn)
        ctrl.addWidget(self.clear_btn)
        ctrl.addStretch()
        root.addLayout(ctrl)

        # Progress + stats
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        root.addWidget(self.progress)
        self.stats_label = QLabel("Ready. Drop files/folders to begin.")
        root.addWidget(self.stats_label)

        # Log (throttled)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(2000)
        self.log_edit.setFixedHeight(110)
        root.addWidget(self.log_edit, 1)

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
        self.setStyleSheet("""
            QMainWindow { background: #12111a; }
            QLabel { color: #e8e2d5; }
            QLineEdit, QComboBox, QPlainTextEdit { background: #1c1a26; color: #e8e2d5;
                border: 1px solid #3a3648; border-radius: 6px; padding: 4px; }
            QPushButton { background: #c9a86a; color: #12111a; border: none;
                border-radius: 6px; padding: 6px 12px; font-weight: bold; }
            QPushButton:disabled { background: #4a4658; color: #9a95a8; }
            QPushButton:hover:!disabled { background: #dbbc85; }
            QTableView { background: #1c1a26; color: #e8e2d5; gridline-color: #3a3648; }
            QHeaderView::section { background: #262233; color: #c9a86a; padding: 4px; }
            QProgressBar { background: #1c1a26; border: 1px solid #3a3648; border-radius: 6px;
                text-align: center; color: #e8e2d5; }
            QProgressBar::chunk { background: #c9a86a; border-radius: 5px; }
            QCheckBox { color: #e8e2d5; }
        """)
        self.drop_label.setStyleSheet(
            "border: 2px dashed #c9a86a; border-radius: 10px; color: #c9a86a; font-size: 14px;")

    def _connect(self):
        self.start_btn.clicked.connect(self._start)
        self.pause_btn.clicked.connect(self.controller.pause)
        self.resume_btn.clicked.connect(self.controller.resume)
        self.cancel_btn.clicked.connect(self.controller.cancel)
        self.retry_btn.clicked.connect(self._retry_failed)
        self.clear_btn.clicked.connect(self.model.clear_finished)
        self.controller.file_finished.connect(self._on_file_finished)
        self.controller.file_started.connect(lambda row: self.model.set_status(row, "running"))
        self.controller.progress.connect(self._on_progress)
        self.controller.log_message.connect(self._log)
        self.controller.finished.connect(self._on_finished)
        self.controller.state_changed.connect(self._on_state)

    # ---------- Add files ----------
    def _add_paths(self, paths: list[str]) -> None:
        files = scan_inputs(paths)
        # Track folder roots for mirror layout
        for p in paths:
            pp = Path(p)
            if pp.is_dir() and pp not in self._input_roots:
                self._input_roots.append(pp)
        added = self.model.add_paths(files)
        self._log(f"Added {added} file(s) to queue (total {self.model.rowCount()}).")
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
        save_config(self._collect_config())  # persist on Start too (crash-safe)
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
            # New name first, legacy content.txt fallback
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
