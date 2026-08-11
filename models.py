from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SUPPORTED_EXTENSIONS = {".heic", ".heif", ".jpg", ".jpeg", ".png"}


@dataclass
class ImageJob:
    source_path: Path
    source_name: str
    modified_time: float
    size: int
    output_path: Path
    status: str = "等待"
    error: str | None = None

    def remap(self, destination: Path) -> None:
        self.output_path = destination / f"{self.source_path.stem}.jpg"
        self.status = "已存在" if self.output_path.is_file() else "等待"
        self.error = None
