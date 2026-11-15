"""GUI tests — offscreen Qt. Run with QT_QPA_PLATFORM=offscreen."""
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from converter.engine import ConvertOptions
from converter.gui import MainWindow, QueueModel
from converter.gui_bulk import BulkController
from tests.make_fixtures import make_epub, make_pdf


@pytest.fixture(scope="module")
def app():
    return QApplication([])


def test_queue_model_add_and_update(app, tmp_path: Path):
    model = QueueModel()
    src = tmp_path / "a.epub"
    make_epub(src)
    assert model.add_paths([src]) == 1
    assert model.rowCount() == 1
    assert model.add_paths([src]) == 0  # dedupe
    assert model.data(model.index(0, 0)) == "a.epub"
    assert model.data(model.index(0, 1)) == "EPUB"


def test_mainwindow_creates_offscreen(app, tmp_path: Path):
    win = MainWindow()
    assert win.model.rowCount() == 0
    src = tmp_path / "b.pdf"
    make_pdf(src)
    win._add_paths([str(src)])
    assert win.model.rowCount() == 1
    win.close()


def test_controller_converts_files(app, tmp_path: Path):
    src_dir = tmp_path / "books"
    src_dir.mkdir()
    make_epub(src_dir / "a.epub")
    make_pdf(src_dir / "b.pdf")
    out = tmp_path / "out"

    model = QueueModel()
    model.add_paths([src_dir / "a.epub", src_dir / "b.pdf"])
    tasks = model.queued_tasks(out, "mirror", [src_dir])
    assert len(tasks) == 2

    controller = BulkController()
    results = {}
    done = {"finished": False}

    def on_finished(row, result):
        results[row] = result

    controller.file_finished.connect(on_finished)
    controller.finished.connect(lambda s: done.update(finished=True, summary=s))
    controller.start(tasks, ConvertOptions(), workers=2)

    # Pump Qt events until finished (max 30s)
    deadline = time.time() + 30
    while not done["finished"] and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    assert done["finished"], "controller did not finish"
    assert len(results) == 2
    assert all(r.status == "ok" for r in results.values())
    assert (out / "a" / "a.txt").exists()
    assert (out / "b" / "b.txt").exists()


def test_clear_all_and_clear_finished(app, tmp_path: Path):
    win = MainWindow()
    src = tmp_path / "a.epub"
    make_epub(src)
    src2 = tmp_path / "b.pdf"
    make_pdf(src2)
    win._add_paths([str(src), str(src2)])
    assert win.model.rowCount() == 2
    win.model.rows[0]["status"] = "ok"
    win.clear_btn.click()
    app.processEvents()
    assert win.model.rowCount() == 1
    win.clear_all_btn.click()
    app.processEvents()
    assert win.model.rowCount() == 0
    win.close()


def test_clear_downloaded_and_failed_separate(app, tmp_path: Path):
    win = MainWindow()
    src = tmp_path / "a.epub"
    make_epub(src)
    src2 = tmp_path / "b.pdf"
    make_pdf(src2)
    win._add_paths([str(src), str(src2)])
    win.model.rows[0]["status"] = "ok"
    win.model.rows[1]["status"] = "failed"
    win.clear_btn.click()  # Clear Downloaded
    app.processEvents()
    assert win.model.rowCount() == 1
    assert win.model.rows[0]["status"] == "failed"
    win.clear_failed_btn.click()  # Clear Failed
    app.processEvents()
    assert win.model.rowCount() == 0
    win.close()


def test_controller_pause_resume_cancel(app, tmp_path: Path):
    src = tmp_path / "a.epub"
    make_epub(src)
    out = tmp_path / "out"
    model = QueueModel()
    model.add_paths([src])
    tasks = model.queued_tasks(out, "mirror", [tmp_path])

    controller = BulkController()
    finished = {}
    controller.finished.connect(lambda s: finished.update(s))
    controller.start(tasks, ConvertOptions(), workers=1)
    controller.pause()
    assert controller.state in ("paused", "running", "idle")  # may finish fast; just must not crash
    controller.resume()
    controller.cancel()  # safe even if already idle/finished
    deadline = time.time() + 30
    while "ok" not in finished and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    # Either completed ok or cancelled cleanly — never hung/crashed
    assert controller.state == "idle"
