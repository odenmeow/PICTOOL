from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from ffmpeg_converter import ConversionStopped, FFmpegConverter
from models import ImageJob


class ConversionWorker(QObject):
    progress_changed = Signal(int, int)
    file_started = Signal(int)
    file_finished = Signal(int, bool)
    file_failed = Signal(int, str)
    batch_finished = Signal()
    batch_stopped = Signal()

    def __init__(self, jobs: list[ImageJob], converter: FFmpegConverter,
                 width: int, jpeg_q: int, skip_existing: bool) -> None:
        super().__init__()
        self.jobs = jobs  # already ordered exactly as displayed by the UI
        self.converter = converter
        self.width = width
        self.jpeg_q = jpeg_q
        self.skip_existing = skip_existing
        self.stop_event = threading.Event()

    @Slot()
    def run(self) -> None:
        total = len(self.jobs)
        completed = 0
        for index, job in enumerate(self.jobs):
            if self.stop_event.is_set():
                self.batch_stopped.emit()
                return
            if self.skip_existing and job.output_path.is_file():
                self.file_finished.emit(index, True)
                completed += 1
                self.progress_changed.emit(completed, total)
                continue
            self.file_started.emit(index)
            try:
                self.converter.convert(job.source_path, job.output_path, self.width,
                                       self.jpeg_q, self.stop_event)
            except ConversionStopped:
                job.output_path.unlink(missing_ok=True)
                self.batch_stopped.emit()
                return
            except Exception as exc:
                job.output_path.unlink(missing_ok=True)
                self.file_failed.emit(index, str(exc))
            else:
                self.file_finished.emit(index, False)
            completed += 1
            self.progress_changed.emit(completed, total)
        self.batch_finished.emit()

    @Slot()
    def stop(self) -> None:
        self.stop_event.set()
        self.converter.stop()
