# SMGFlow — HEIC 批次轉 JPG

Windows 桌面工具，針對 Samsung／手機 HEIC Tile Grid 使用兩段 FFmpeg pipeline：第一段先把完整 grid 解碼成 PNG pipe，第二段才保持比例縮放並編碼成 JPEG。程式不使用 shell、OpenCV 或裁切。

## 安裝與執行

1. 安裝 Python 3.10 以上版本。
2. 執行 `python -m pip install -r requirements.txt`（唯一 Python dependency 是 PySide6）。
3. 安裝含 HEIC/HEVC decoder 的 FFmpeg，加入 `PATH`，或在 GUI 選擇 `ffmpeg.exe`。
4. 執行 `python main.py`。

設定會透過 `QSettings` 保存。來源支援 HEIC、HEIF、JPEG 與 PNG；輸出固定為 JPG。

## Tile Grid 驗證

準備一張 `4128x3096` Samsung HEIC，選擇空的輸出資料夾，保持寬度 `2560`、q:v `3`，執行轉換後用以下指令檢查：

```powershell
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 output.jpg
```

預期為 `2560x1920`，並以圖片程式目視確認是完整照片而非 `512x384` 左上 tile。可把來源及輸出資料夾放在含中文和空白的路徑測試；所有 subprocess 都使用 argument list，因此無須自行加引號。

## 檔案職責

* `main.py`：建立 QApplication 與主視窗。
* `main_window.py`：GUI、資料夾掃描、排序、列表同步、圖片開啟和 QThread lifecycle。
* `models.py`：一一對應來源與輸出的 `ImageJob` model。
* `conversion_worker.py`：依畫面順序執行批次並以 Qt signals 回報。
* `ffmpeg_converter.py`：安全的雙 FFmpeg pipe、stderr drain、中止及錯誤處理。
* `settings.py`：QSettings 的載入與保存。
