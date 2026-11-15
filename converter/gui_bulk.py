"""GUI bulk controller: incremental ProcessPool with pause/resume/cancel.

Runs in a background thread; communicates via Qt signals (queued to GUI thread).
Never blocks the GUI. Pause stops submitting new files; in-flight files finish.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .bulk import _is_already_converted, output_dir_for
from .engine import ConvertOptions, ConvertResult, convert_file


def _worker(task: tuple[str, str, dict]) -> ConvertResult:
    src_s, out_s, opts = task
    return convert_file(Path(src_s), Path(out_s), ConvertOptions(**opts))


class BulkController(QObject):
    file_finished = Signal(int, object)   # row_index, ConvertResult
    file_started = Signal(int)            # row_index
    progress = Signal(int, int)           # done, total
    log_message = Signal(str)
    finished = Signal(object)             # summary dict
    state_changed = Signal(str)           # idle|running|paused|cancelling

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._pause_event = threading.Event()   # set = running, clear = paused
        self._pause_event.set()
        self._cancel_event = threading.Event()
        self._state = "idle"
        self._start_time = 0.0
        self._done_count = 0
        self._total = 0

    # -- public API (called from GUI thread) --
    def start(self, tasks: list[tuple[int, Path, Path]], options: ConvertOptions,
              workers: int, skip_existing: bool = True) -> None:
        """tasks: list of (row_index, src_path, out_book_dir)."""
        if self._state in ("running", "paused"):
            return
        self._cancel_event.clear()
        self._pause_event.set()
        self._total = len(tasks)
        self._done_count = 0
        self._start_time = time.perf_counter()
        self._set_state("running")
        self._thread = threading.Thread(
            target=self._run, args=(tasks, options, workers, skip_existing),
            daemon=True, name="bulk-controller",
        )
        self._thread.start()

    def pause(self) -> None:
        if self._state == "running":
            self._pause_event.clear()
            self._set_state("paused")

    def resume(self) -> None:
        if self._state == "paused":
            self._pause_event.set()
            self._set_state("running")

    def cancel(self) -> None:
        if self._state in ("running", "paused"):
            self._cancel_event.set()
            self._pause_event.set()  # wake pause loop so it can exit
            self._set_state("cancelling")

    @property
    def state(self) -> str:
        return self._state

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self._start_time if self._start_time else 0.0

    def _set_state(self, s: str) -> None:
        self._state = s
        self.state_changed.emit(s)

    # -- worker thread --
    def _run(self, tasks, options: ConvertOptions, workers: int, skip_existing: bool) -> None:
        opts_dict = {"preset": options.preset, "text_only": options.text_only, "ocr": options.ocr,
                     "max_image_side": options.max_image_side, "figure_dpi": options.figure_dpi,
                     "include_header": options.include_header, "flat_txt_dir": options.flat_txt_dir}
        pending: deque = deque()
        skipped = 0
        for row, src, out_dir in tasks:
            if skip_existing and _is_already_converted(src, out_dir):
                r = ConvertResult(status="skipped", source=str(src), output_dir=str(out_dir), title=src.stem)
                self.file_finished.emit(row, r)
                self._done_count += 1
                self.progress.emit(self._done_count, self._total)
                skipped += 1
            else:
                pending.append((row, str(src), str(out_dir), opts_dict))

        ok = failed = 0
        workers = max(1, workers)
        futures: dict = {}
        try:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                while pending or futures:
                    if self._cancel_event.is_set():
                        for f in futures:
                            f.cancel()
                        break
                    # Pause: wait until resumed or cancelled
                    while not self._pause_event.is_set():
                        if self._cancel_event.is_set():
                            break
                        time.sleep(0.1)
                    if self._cancel_event.is_set():
                        for f in futures:
                            f.cancel()
                        break
                    # Submit up to workers in-flight
                    while pending and len(futures) < workers and not self._cancel_event.is_set():
                        if not self._pause_event.is_set():
                            break
                        row, src_s, out_s, od = pending.popleft()
                        fut = ex.submit(_worker, (src_s, out_s, od))
                        futures[fut] = row
                        self.file_started.emit(row)
                    if not futures:
                        continue
                    done_futs, _ = wait(list(futures.keys()), timeout=0.5, return_when=FIRST_COMPLETED)
                    for fut in done_futs:
                        row = futures.pop(fut)
                        try:
                            r = fut.result()
                        except Exception as e:
                            r = ConvertResult(status="failed", source="", error=f"Worker crash: {e}")
                        if r.status == "ok":
                            ok += 1
                        elif r.status == "failed":
                            failed += 1
                        self.file_finished.emit(row, r)
                        self._done_count += 1
                        self.progress.emit(self._done_count, self._total)
        except Exception as e:
            self.log_message.emit(f"Controller error: {e}")
        finally:
            cancelled = self._cancel_event.is_set()
            summary = {"ok": ok, "failed": failed, "skipped": skipped,
                       "done": self._done_count, "total": self._total,
                       "cancelled": cancelled, "elapsed": self.elapsed}
            self._set_state("idle")
            self.finished.emit(summary)
