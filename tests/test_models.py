from pathlib import Path

from models import ImageJob, SUPPORTED_EXTENSIONS


def test_extensions_are_case_insensitive_when_caller_lowers_suffix():
    assert {".heic", ".heif", ".jpg", ".jpeg", ".png"} == SUPPORTED_EXTENSIONS
    assert Path("照片.HEIC").suffix.lower() in SUPPORTED_EXTENSIONS


def test_remap_preserves_source_basename(tmp_path):
    source = tmp_path / "來源" / "圖片 01.heic"
    output = tmp_path / "輸出"
    job = ImageJob(source, source.name, 10.0, 123, Path("old.jpg"))
    job.remap(output)
    assert job.output_path == output / "圖片 01.jpg"
