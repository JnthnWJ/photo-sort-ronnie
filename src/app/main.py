from __future__ import annotations
import sys
from pathlib import Path
import threading

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QRadioButton, QCheckBox, QProgressBar, QTextEdit, QGroupBox, QComboBox
)

from photosorter.ops import Options
from photosorter.core import plan_actions, execute_actions


class Worker(QObject):
    progress = Signal(int, int, str)
    log = Signal(str)
    error = Signal(str)
    done = Signal()

    def __init__(self, opts: Options) -> None:
        super().__init__()
        self.opts = opts
        self._stop = threading.Event()

    def cancel(self):
        self._stop.set()

    def run(self):
        try:
            actions = plan_actions(self.opts)
            total = len(actions)
            self.log.emit(f"Planned {total} action(s)")
            if self.opts.dry_run:
                for i, a in enumerate(actions, 1):
                    self.log.emit(f"{a.op.upper()} {a.src} -> {a.dst} [{a.reason}]")
                    self.progress.emit(i, total, f"Planned: {a.src.name}")
                    if self._stop.is_set():
                        self.log.emit("Cancelled")
                        self.done.emit()
                        return
                self.done.emit()
                return

            def cb_prog(i, tot, msg):
                self.progress.emit(i, tot, msg)

            def cb_log(msg):
                self.log.emit(msg)

            def cb_err(msg):
                self.error.emit(msg)

            execute_actions(
                actions,
                progress=cb_prog,
                log=cb_log,
                on_error=cb_err,
                stop_flag=self._stop,
                max_workers=self.opts.max_workers,
            )
            if self._stop.is_set():
                self.log.emit("Cancelled")
            self.done.emit()
        except Exception as e:
            self.error.emit(str(e))
            self.done.emit()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Photo Sorter")
        self._build_ui()
        self._thread: QThread | None = None
        self._worker: Worker | None = None

    def _build_ui(self):
        lay = QVBoxLayout(self)

        # Source
        src_box = QGroupBox("Source Folder")
        src_lay = QHBoxLayout()
        self.src_edit = QLineEdit()
        btn_src = QPushButton("Browse…")
        btn_src.clicked.connect(self._pick_src)
        src_lay.addWidget(self.src_edit)
        src_lay.addWidget(btn_src)
        src_box.setLayout(src_lay)
        lay.addWidget(src_box)

        # Dest
        dst_box = QGroupBox("Destination Root")
        dst_lay = QHBoxLayout()
        self.dst_edit = QLineEdit()
        btn_dst = QPushButton("Browse…")
        btn_dst.clicked.connect(self._pick_dst)
        dst_lay.addWidget(self.dst_edit)
        dst_lay.addWidget(btn_dst)
        dst_box.setLayout(dst_lay)
        lay.addWidget(dst_box)

        # Options
        opt_box = QGroupBox("Options")
        opt_lay = QHBoxLayout()
        self.rb_copy = QRadioButton("Copy")
        self.rb_move = QRadioButton("Move")
        self.rb_copy.setChecked(True)
        self.cb_recursive = QCheckBox("Include subfolders")
        self.cb_recursive.setChecked(True)
        self.cb_dryrun = QCheckBox("Dry run (no changes)")
        self.cb_dryrun.setChecked(True)
        self.cb_filetime = QCheckBox("Fallback to file times when no EXIF/filename date")
        self.cb_filetime.setChecked(True)
        self.cb_convert_heic = QCheckBox("Convert HEIC to JPEG")
        self.cb_convert_heic.setChecked(False)
        self.cb_live = QComboBox()
        self.cb_live.addItems(["Preserve both", "Image only", "Video only"])
        opt_lay.addWidget(self.rb_copy)
        opt_lay.addWidget(self.rb_move)
        opt_lay.addWidget(self.cb_recursive)
        opt_lay.addWidget(self.cb_dryrun)
        opt_lay.addWidget(self.cb_filetime)
        opt_lay.addWidget(self.cb_convert_heic)
        opt_lay.addWidget(QLabel("Live Photos:"))
        opt_lay.addWidget(self.cb_live)
        opt_box.setLayout(opt_lay)
        lay.addWidget(opt_box)

        # Progress and controls
        ctrl_lay = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.prog = QProgressBar()
        self.status = QLabel("Idle")
        ctrl_lay.addWidget(self.btn_start)
        ctrl_lay.addWidget(self.btn_cancel)
        ctrl_lay.addWidget(self.prog)
        ctrl_lay.addWidget(self.status)
        lay.addLayout(ctrl_lay)

        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log)

        # Wire buttons
        self.btn_start.clicked.connect(self._start)
        self.btn_cancel.clicked.connect(self._cancel)

    def _pick_src(self):
        d = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if d:
            self.src_edit.setText(d)

    def _pick_dst(self):
        d = QFileDialog.getExistingDirectory(self, "Select Destination Root")
        if d:
            self.dst_edit.setText(d)

    def _start(self):
        src = Path(self.src_edit.text()).expanduser()
        dst = Path(self.dst_edit.text()).expanduser()
        if not src.exists() or not src.is_dir():
            self._append_log("Please choose a valid source folder")
            return
        if not dst.exists():
            try:
                dst.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self._append_log(f"Cannot create destination: {e}")
                return
        mode = "move" if self.rb_move.isChecked() else "copy"
        live_map = {0: "preserve_both", 1: "image_only", 2: "video_only"}
        live_choice = live_map.get(self.cb_live.currentIndex(), "preserve_both")
        opts = Options(
            source=src,
            dest_root=dst,
            mode=mode,
            recursive=self.cb_recursive.isChecked(),
            dry_run=self.cb_dryrun.isChecked(),
            fallback_use_file_times=self.cb_filetime.isChecked(),
            max_workers=8,
            convert_heic_to_jpeg=self.cb_convert_heic.isChecked(),
            live_photos=live_choice,
        )
        self._run_worker(opts)

    def _run_worker(self, opts: Options):
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.prog.setValue(0)
        self.status.setText("Working…")
        self._append_log("Starting…")

        self._thread = QThread()
        self._worker = Worker(opts)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._append_log)
        self._worker.error.connect(self._append_log)
        self._worker.done.connect(self._on_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.start()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()

    def _on_progress(self, i: int, total: int, msg: str):
        self.prog.setMaximum(total if total > 0 else 1)
        self.prog.setValue(i)
        self.status.setText(msg)

    def _on_done(self):
        self._append_log("Finished")
        # Ensure the worker thread fully stops before dropping references to avoid Qt abort()
        if self._thread is not None:
            try:
                # 'done' is emitted by the worker when it finishes; ensure the thread actually exits
                self._thread.quit()
                self._thread.wait()
            except Exception:
                pass
        if self._worker is not None:
            try:
                self._worker.deleteLater()
            except Exception:
                pass
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.status.setText("Idle")
        self._thread = None
        self._worker = None

    def _append_log(self, s: str):
        self.log.append(s)


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.resize(900, 500)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

