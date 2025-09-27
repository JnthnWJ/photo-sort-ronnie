# Photo Sorter (Python + Qt)

Cross-platform photo sorting tool that organizes images into YYYY/MM folders based on EXIF, filename patterns, or file timestamps. Supports JPG/JPEG, PNG, and HEIC. GUI with dry-run and progress.

## Features
- Copy or move into `YYYY/MM/` under a chosen destination root
- Dry-run preview (no changes)
- Duplicate-safe filenames with numeric suffixes
- Recursively process nested folders
- EXIF date preferred; fallback to filename patterns; then filesystem times; else `unknown/`
- Progress bar and log output

## Requirements
- Python 3.10+
- Dependencies: PySide6, Pillow, pillow-heif

Install deps:

```bash
pip install -r requirements.txt
```

## Run the GUI

```bash
# macOS/Linux
PYTHONPATH=src python -m app.main
# Windows (PowerShell)
$env:PYTHONPATH="src"; python -m app.main
# Windows (cmd)
set PYTHONPATH=src && python -m app.main
```

## Notes
- HEIC support is enabled by `pillow-heif` which registers an Image opener. If a HEIC fails to read EXIF, the app falls back to filename and then file times.
- Dry-run is on by default. Uncheck it to actually copy/move files.
- Destination structure is created under the selected destination root; originals are preserved when using Copy mode (default).

## Packaging (Windows .exe and macOS .app)

PyInstaller builds must be done on the target OS (no cross-compiling from macOS to Windows).

### Build a Windows .exe locally
1) Open a terminal in the project root and create a venv
   - PowerShell:
     ```powershell
     py -3 -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   - cmd:
     ```cmd
     py -3 -m venv .venv
     .\.venv\Scripts\activate.bat
     ```
2) Install dependencies and PyInstaller
   ```powershell
   pip install -r requirements.txt
   pip install pyinstaller
   ```
3) Build the exe
   - PowerShell:
     ```powershell
     pyinstaller --noconfirm --windowed --onefile --name PhotoSorter --paths src \
       --collect-all PySide6 --collect-all PIL --collect-all pillow_heif \
       src/app/main.py
     ```
   - cmd:
     ```cmd
     pyinstaller --noconfirm --windowed --onefile --name PhotoSorter --paths src \
       --collect-all PySide6 --collect-all PIL --collect-all pillow_heif \
       src\app\main.py
     ```
4) Run it: `dist/PhotoSorter.exe` (Windows SmartScreen may warn; use "More info" → "Run anyway").

### Build a macOS .app locally
1) In a venv on macOS:
   ```bash
   pip install -r requirements.txt
   pip install pyinstaller
   ```
2) Build the app bundle:
   ```bash
   pyinstaller --noconfirm --windowed --name PhotoSorter --paths src \
     --collect-all PySide6 --collect-all PIL --collect-all pillow_heif \
     src/app/main.py
   ```
3) Run it: `dist/PhotoSorter.app`
   - For distribution outside your machine, consider code signing and notarization.

### Optional: GitHub Actions to build Windows exe
You can automate Windows builds and download the artifact:

```yaml
name: build-windows
on: [workflow_dispatch]
jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pyinstaller
      - name: Build exe
        run: |
          pyinstaller --noconfirm --windowed --onefile --name PhotoSorter --paths src \
            --collect-all PySide6 --collect-all PIL --collect-all pillow_heif \
            src/app/main.py
      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: PhotoSorter-windows
          path: dist/PhotoSorter.exe
```

Notes:
- `--collect-all` ensures Qt plugins, Pillow plugins, and pillow-heif’s native libraries are bundled.
- If PyInstaller reports missing modules, re-run adding hidden imports, e.g. `--hidden-import pillow_heif --hidden-import PIL._imaging`.

