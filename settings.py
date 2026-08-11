from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings


@dataclass
class AppSettings:
    source_folder: str = ""
    destination_folder: str = ""
    ffmpeg_path: str = ""
    width: int = 2560
    jpeg_q: int = 3
    ascending: bool = True
    skip_existing: bool = True

    @classmethod
    def load(cls) -> "AppSettings":
        store = QSettings("SMGFlow", "HEIC Batch to JPG")
        return cls(
            source_folder=store.value("source_folder", "", str),
            destination_folder=store.value("destination_folder", "", str),
            ffmpeg_path=store.value("ffmpeg_path", "", str),
            width=store.value("width", 2560, int),
            jpeg_q=store.value("jpeg_q", 3, int),
            ascending=store.value("ascending", True, bool),
            skip_existing=store.value("skip_existing", True, bool),
        )

    def save(self) -> None:
        store = QSettings("SMGFlow", "HEIC Batch to JPG")
        for key, value in self.__dict__.items():
            store.setValue(key, value)
