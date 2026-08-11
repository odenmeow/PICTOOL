from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QProgressBar, QSpinBox,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from conversion_worker import ConversionWorker
from ffmpeg_converter import FFmpegConverter
from models import ImageJob, SUPPORTED_EXTENSIONS
from settings import AppSettings


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return ""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HEIC 批次轉 JPG")
        self.resize(1200, 700)
        self.settings = AppSettings.load()
        self.jobs: list[ImageJob] = []
        self.thread: QThread | None = None
        self.worker: ConversionWorker | None = None
        self._build_ui()
        self._restore()

    def _build_ui(self) -> None:
        root = QWidget(); layout = QVBoxLayout(root); self.setCentralWidget(root)
        self.source_edit = QLineEdit(); self.dest_edit = QLineEdit()
        source_buttons = [("瀏覽", self.choose_source), ("重新整理", self.scan_source),
                          ("開啟資料夾", lambda: self.open_path(Path(self.source_edit.text())))]
        dest_buttons = [("瀏覽", self.choose_destination),
                        ("開啟資料夾", lambda: self.open_path(Path(self.dest_edit.text())))]
        for label, edit, buttons in (("來源資料夾：", self.source_edit, source_buttons),
                                     ("輸出資料夾：", self.dest_edit, dest_buttons)):
            row = QHBoxLayout(); row.addWidget(QLabel(label)); row.addWidget(edit, 1)
            for text, callback in buttons:
                button = QPushButton(text); button.clicked.connect(callback); row.addWidget(button)
            layout.addLayout(row)
        self.source_edit.editingFinished.connect(self.scan_source)
        self.dest_edit.editingFinished.connect(self.remap_destination)

        options = QGroupBox("轉換設定"); form = QFormLayout(options)
        option_row = QHBoxLayout()
        self.width_spin = QSpinBox(); self.width_spin.setRange(512, 10000)
        self.q_spin = QSpinBox(); self.q_spin.setRange(2, 31)
        self.q_spin.setToolTip("q:v 數字越小，JPEG 品質越高、容量通常越大。推薦書本照片使用 2~4。")
        self.sort_check = QCheckBox("修改時間：最舊 → 最新")
        self.sort_check.toggled.connect(self.sort_jobs)
        self.skip_check = QCheckBox("跳過已存在的輸出")
        option_row.addWidget(QLabel("最大寬度：")); option_row.addWidget(self.width_spin)
        option_row.addWidget(QLabel("JPEG q:v：")); option_row.addWidget(self.q_spin)
        option_row.addWidget(QLabel("Scaler：lanczos")); option_row.addWidget(self.sort_check)
        option_row.addWidget(self.skip_check); option_row.addStretch()
        form.addRow(option_row)
        ffrow = QHBoxLayout(); self.ffmpeg_label = QLabel()
        pick = QPushButton("選擇 ffmpeg.exe"); pick.clicked.connect(self.choose_ffmpeg)
        ffrow.addWidget(QLabel("FFmpeg：")); ffrow.addWidget(self.ffmpeg_label, 1); ffrow.addWidget(pick)
        form.addRow(ffrow); layout.addWidget(options)

        self.source_tree = QTreeWidget(); self.dest_tree = QTreeWidget()
        self.source_tree.setHeaderLabels(["Filename", "Modified", "Size", "Status"])
        self.dest_tree.setHeaderLabels(["Filename", "Size", "Status"])
        splitter = QSplitter(); splitter.addWidget(self.source_tree); splitter.addWidget(self.dest_tree)
        splitter.setSizes([650, 550]); layout.addWidget(splitter, 1)
        self.source_tree.itemDoubleClicked.connect(lambda item, _c: self.open_row(item, False))
        self.dest_tree.itemDoubleClicked.connect(lambda item, _c: self.open_row(item, True))
        QShortcut(QKeySequence(Qt.Key_Return), self.source_tree,
                  activated=lambda: self.open_current(self.source_tree, False))
        QShortcut(QKeySequence(Qt.Key_Return), self.dest_tree,
                  activated=lambda: self.open_current(self.dest_tree, True))

        bottom = QHBoxLayout(); self.start_button = QPushButton("開始轉換")
        self.stop_button = QPushButton("停止"); self.stop_button.setEnabled(False)
        self.progress = QProgressBar(); self.progress.setFormat("%v / %m  (%p%)")
        self.start_button.clicked.connect(self.start_batch); self.stop_button.clicked.connect(self.stop_batch)
        bottom.addWidget(self.start_button); bottom.addWidget(self.stop_button); bottom.addWidget(self.progress, 1)
        layout.addLayout(bottom); self.current_label = QLabel("目前：—"); layout.addWidget(self.current_label)

    def _restore(self) -> None:
        self.source_edit.setText(self.settings.source_folder)
        self.dest_edit.setText(self.settings.destination_folder)
        self.width_spin.setValue(self.settings.width); self.q_spin.setValue(self.settings.jpeg_q)
        self.sort_check.setChecked(self.settings.ascending); self.skip_check.setChecked(self.settings.skip_existing)
        candidate = self.settings.ffmpeg_path or shutil.which("ffmpeg") or ""
        self.set_ffmpeg(candidate)
        if self.settings.source_folder:
            self.scan_source()

    def choose_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇來源資料夾", self.source_edit.text())
        if path: self.source_edit.setText(path); self.scan_source()

    def choose_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾", self.dest_edit.text())
        if path: self.dest_edit.setText(path); self.remap_destination()

    def scan_source(self) -> None:
        folder = Path(self.source_edit.text())
        destination = Path(self.dest_edit.text()) if self.dest_edit.text() else Path()
        self.jobs = []
        if folder.is_dir():
            for path in folder.iterdir():
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    stat = path.stat()
                    self.jobs.append(ImageJob(path, path.name, stat.st_mtime, stat.st_size,
                                              destination / f"{path.stem}.jpg"))
            self.sort_jobs()
        else: self.render_jobs()

    def remap_destination(self) -> None:
        destination = Path(self.dest_edit.text())
        for job in self.jobs: job.remap(destination)
        self.render_jobs()

    def sort_jobs(self) -> None:
        ascending = self.sort_check.isChecked()
        self.sort_check.setText("修改時間：最舊 → 最新" if ascending else "修改時間：最新 → 最舊")
        self.jobs.sort(key=lambda j: (j.modified_time, j.source_name.lower()), reverse=not ascending)
        self.render_jobs()

    def render_jobs(self) -> None:
        self.source_tree.clear(); self.dest_tree.clear()
        for index, job in enumerate(self.jobs):
            if job.output_path.is_file() and job.status == "等待": job.status = "已存在"
            source = QTreeWidgetItem([job.source_name, datetime.fromtimestamp(job.modified_time).strftime("%Y-%m-%d %H:%M:%S"), human_size(job.size), job.status])
            output_exists = job.output_path.is_file()
            dest = QTreeWidgetItem([job.output_path.name if output_exists else "[尚未處理]",
                                    human_size(job.output_path.stat().st_size) if output_exists else "", job.status])
            source.setData(0, Qt.UserRole, index); dest.setData(0, Qt.UserRole, index)
            if job.error:
                source.setToolTip(3, job.error); dest.setToolTip(2, job.error)
            self.source_tree.addTopLevelItem(source); self.dest_tree.addTopLevelItem(dest)
        for tree in (self.source_tree, self.dest_tree):
            for column in range(tree.columnCount()): tree.resizeColumnToContents(column)

    def open_current(self, tree: QTreeWidget, destination: bool) -> None:
        if tree.currentItem(): self.open_row(tree.currentItem(), destination)

    def open_row(self, item: QTreeWidgetItem, destination: bool) -> None:
        index = item.data(0, Qt.UserRole)
        if index is None or index >= len(self.jobs): return
        path = self.jobs[index].output_path if destination else self.jobs[index].source_path
        if not path.exists(): self.statusBar().showMessage("此圖片尚未產生", 4000); return
        self.open_path(path)

    def open_path(self, path: Path) -> None:
        if not path.exists(): self.statusBar().showMessage("路徑不存在", 4000); return
        try:
            if os.name == "nt": os.startfile(path)  # type: ignore[attr-defined]
            else: subprocess.Popen(["xdg-open", os.fspath(path)])
        except OSError as exc: self.statusBar().showMessage(f"無法開啟：{exc}", 5000)

    def choose_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "選擇 ffmpeg.exe", "", "ffmpeg (ffmpeg.exe ffmpeg);;所有檔案 (*)")
        if path: self.set_ffmpeg(path)

    def set_ffmpeg(self, path: str) -> None:
        valid = False
        if path:
            try:
                valid = subprocess.run([path, "-version"], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, timeout=5).returncode == 0
            except (OSError, subprocess.TimeoutExpired): pass
        self.ffmpeg_label.setText(path if valid else "找不到或無法執行（請選擇 ffmpeg.exe）")
        self.ffmpeg_label.setProperty("path", path if valid else "")

    def start_batch(self) -> None:
        ffmpeg = self.ffmpeg_label.property("path")
        if not ffmpeg: QMessageBox.warning(self, "FFmpeg", "請先選擇有效的 ffmpeg.exe。"); return
        if not self.jobs: QMessageBox.information(self, "沒有檔案", "來源資料夾沒有支援的圖片。"); return
        if not self.dest_edit.text().strip():
            QMessageBox.warning(self, "輸出資料夾", "請先選擇輸出資料夾。"); return
        destination = Path(self.dest_edit.text())
        try: destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc: QMessageBox.critical(self, "輸出錯誤", str(exc)); return
        # Snapshot preserves the displayed order even if controls are later changed.
        self.thread = QThread(self); self.worker = ConversionWorker(list(self.jobs), FFmpegConverter(ffmpeg), self.width_spin.value(), self.q_spin.value(), self.skip_check.isChecked())
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.file_started.connect(self.file_started); self.worker.file_finished.connect(self.file_finished)
        self.worker.file_failed.connect(self.file_failed); self.worker.progress_changed.connect(self.update_progress)
        self.worker.batch_finished.connect(lambda: self.finish_batch(False)); self.worker.batch_stopped.connect(lambda: self.finish_batch(True))
        self.thread.start(); self.start_button.setEnabled(False); self.stop_button.setEnabled(True)
        self.progress.setRange(0, len(self.jobs)); self.progress.setValue(0)

    def stop_batch(self) -> None:
        if self.worker: self.worker.stop()
        self.stop_button.setEnabled(False); self.current_label.setText("正在停止…")

    def file_started(self, index: int) -> None:
        self.jobs[index].status = "轉換中"; self.current_label.setText(f"目前：{self.jobs[index].source_name} → {self.jobs[index].output_path.name}"); self.render_jobs()

    def file_finished(self, index: int, skipped: bool) -> None:
        self.jobs[index].status = "跳過" if skipped else "完成"; self.render_jobs()

    def file_failed(self, index: int, error: str) -> None:
        self.jobs[index].status = "失敗"; self.jobs[index].error = error; self.render_jobs()

    def update_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(total); self.progress.setValue(done)

    def finish_batch(self, stopped: bool) -> None:
        if self.thread:
            self.thread.quit(); self.thread.wait(); self.thread.deleteLater()
        self.thread = None; self.worker = None; self.start_button.setEnabled(True); self.stop_button.setEnabled(False)
        self.current_label.setText("已停止" if stopped else "批次完成")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker: self.worker.stop()
        if self.thread: self.thread.quit(); self.thread.wait(3000)
        self.settings = AppSettings(self.source_edit.text(), self.dest_edit.text(), self.ffmpeg_label.property("path") or "", self.width_spin.value(), self.q_spin.value(), self.sort_check.isChecked(), self.skip_check.isChecked())
        self.settings.save(); event.accept()
