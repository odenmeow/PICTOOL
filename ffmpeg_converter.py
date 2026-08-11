from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path


class ConversionError(RuntimeError):
    pass


class ConversionStopped(ConversionError):
    pass


class FFmpegConverter:
    """Runs the two-process pipeline needed to materialize an HEIC tile grid."""

    def __init__(self, ffmpeg_path: str) -> None:
        self.ffmpeg_path = ffmpeg_path
        self._lock = threading.Lock()
        self._processes: list[subprocess.Popen] = []

    def _set_processes(self, *processes: subprocess.Popen) -> None:
        with self._lock:
            self._processes = list(processes)

    def stop(self) -> None:
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic() + 1.5
        for process in processes:
            if process.poll() is None:
                try:
                    process.wait(max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    process.kill()

    def convert(
        self,
        input_path: Path,
        output_path: Path,
        width: int = 2560,
        jpeg_q: int = 3,
        stop_event: threading.Event | None = None,
    ) -> None:
        if not 512 <= width <= 10000 or not 2 <= jpeg_q <= 31:
            raise ValueError("Invalid width or JPEG q:v value")
        if input_path.resolve() == output_path.resolve():
            raise ConversionError("來源與輸出檔案不可為同一路徑")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command1 = [
            self.ffmpeg_path, "-hide_banner", "-i", os.fspath(input_path),
            "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-",
        ]
        command2 = [
            self.ffmpeg_path, "-hide_banner", "-f", "image2pipe", "-i", "pipe:0",
            "-vf", f"scale={width}:-2:flags=lanczos", "-frames:v", "1",
            "-q:v", str(jpeg_q), "-y", os.fspath(output_path),
        ]
        p1 = p2 = None
        stderr1: list[bytes] = []
        try:
            p1 = subprocess.Popen(command1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert p1.stdout is not None
            try:
                p2 = subprocess.Popen(command2, stdin=p1.stdout, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE)
            except Exception:
                p1.kill()
                p1.wait()
                raise
            p1.stdout.close()  # p2 owns the read end; enables SIGPIPE propagation.
            self._set_processes(p1, p2)

            def drain_first_stderr() -> None:
                assert p1 is not None and p1.stderr is not None
                stderr1.append(p1.stderr.read())

            drain = threading.Thread(target=drain_first_stderr, daemon=True)
            drain.start()
            while p2.poll() is None:
                if stop_event is not None and stop_event.is_set():
                    self.stop()
                    break
                time.sleep(0.05)
            stderr2 = p2.communicate()[1] or b""
            p1.wait()
            drain.join()
            stopped = stop_event is not None and stop_event.is_set()
            if stopped:
                raise ConversionStopped("使用者已停止轉換")
            if p1.returncode or p2.returncode:
                details = b"\n".join(stderr1 + [stderr2]).decode(errors="replace")[-12000:]
                raise ConversionError(details.strip() or "FFmpeg conversion failed")
            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise ConversionError("FFmpeg did not create a valid output file")
        except FileNotFoundError as exc:
            raise ConversionError(f"找不到 FFmpeg：{self.ffmpeg_path}") from exc
        except OSError as exc:
            raise ConversionError(f"無法執行或寫入檔案：{exc}") from exc
        except BaseException:
            if p1 is not None or p2 is not None:
                self.stop()
            if output_path.exists() and (stop_event is not None and stop_event.is_set()):
                output_path.unlink(missing_ok=True)
            raise
        finally:
            self._set_processes()
