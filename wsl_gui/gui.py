"""Qt (PySide6) front end."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget, QHeaderView, QAbstractItemView,
)

from . import __version__
from .layers import LayerError, UILayer, import_layer, load_layers, user_layers_dir
from .wsl import Wsl, WslError


class Worker(QThread):
    """Runs a callable off the UI thread. The callable receives a ``log`` function."""

    log = Signal(str)
    done = Signal(bool, str)

    def __init__(self, fn, parent: QObject | None = None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.fn(self.log.emit)
            self.done.emit(True, "")
        except Exception as e:  # noqa: BLE001 - surface anything to the user
            self.done.emit(False, str(e))


class OnlineDistroDialog(QDialog):
    def __init__(self, wsl: Wsl, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Install a Linux distribution")
        self.resize(480, 380)
        self.list = QListWidget()
        try:
            self.items = wsl.list_online()
        except WslError as e:
            self.items = []
            QMessageBox.warning(self, "WSL", str(e))
        for d in self.items:
            self.list.addItem(f"{d.name} — {d.friendly_name}")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Choose a distribution to install:"))
        lay.addWidget(self.list)
        lay.addWidget(buttons)

    def selected(self) -> str | None:
        row = self.list.currentRow()
        return self.items[row].name if row >= 0 else None


class MainWindow(QMainWindow):
    def __init__(self, wsl: Wsl | None = None):
        super().__init__()
        self.wsl = wsl or Wsl()
        self.layers: list[UILayer] = []
        self.workers: set[Worker] = set()
        self.setWindowTitle(f"WSL-GUI {__version__}")
        self.resize(980, 660)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_distros_tab(), "Distros")
        self.tabs.addTab(self._build_desktop_tab(), "Desktop / UI layers")
        self.tabs.addTab(self._build_tools_tab(), "Apps && Terminal")
        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setMaximumBlockCount(5000)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.tabs)
        split.addWidget(self.log_view)
        split.setSizes([460, 200])
        self.setCentralWidget(split)
        self.reload_layers()
        self.refresh()

    # --- helpers -----------------------------------------------------------
    def log(self, text: str):
        self.log_view.appendPlainText(text)

    def run_task(self, title: str, fn, then=None):
        self.log(f"▶ {title}")
        w = Worker(fn, self)
        self.workers.add(w)
        w.log.connect(self.log)

        def finished(ok: bool, err: str):
            self.workers.discard(w)
            self.log("✔ done" if ok else f"✘ failed: {err}")
            if not ok:
                QMessageBox.warning(self, title, err)
            if then:
                then(ok)
            self.refresh()

        w.done.connect(finished)
        w.start()

    def current_distro(self) -> str | None:
        row = self.table.currentRow()
        if row >= 0:
            return self.table.item(row, 0).text()
        return None

    def target_distro(self, combo: QComboBox) -> str | None:
        name = combo.currentText()
        if not name:
            QMessageBox.information(self, "WSL-GUI", "Install or select a distribution first.")
        return name or None

    # --- distros tab -------------------------------------------------------
    def _build_distros_tab(self) -> QWidget:
        w = QWidget()
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "State", "WSL version", "Default"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        btns = QHBoxLayout()
        for label, fn in [
            ("Install from store…", self.on_install), ("Install from URL…", self.on_install_url),
            ("Install from file…", self.on_import), ("Open GUI ▶", self.on_open_gui), ("Set default", self.on_set_default),
            ("Stop", self.on_terminate), ("Export…", self.on_export),
            ("Delete", self.on_unregister),
            ("Update WSL", self.on_update), ("Refresh", self.refresh),
        ]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            btns.addWidget(b)
        lay = QVBoxLayout(w)
        lay.addWidget(self.table)
        lay.addLayout(btns)
        return w

    def refresh(self, *_):
        try:
            distros = self.wsl.list_installed()
        except WslError as e:
            self.log(str(e))
            distros = []
        keep = self.current_distro()
        self.table.setRowCount(len(distros))
        for i, d in enumerate(distros):
            for c, v in enumerate([d.name, d.state, str(d.version), "★" if d.default else ""]):
                self.table.setItem(i, c, QTableWidgetItem(v))
            if d.name == keep:
                self.table.selectRow(i)
        for combo in (self.desktop_distro, self.tools_distro):
            prev = combo.currentText()
            combo.clear()
            combo.addItems([d.name for d in distros])
            if prev:
                combo.setCurrentText(prev)

    def _need_selection(self) -> str | None:
        name = self.current_distro()
        if not name:
            QMessageBox.information(self, "WSL-GUI", "Select a distribution in the table first.")
        return name

    def on_install(self):
        dlg = OnlineDistroDialog(self.wsl, self)
        if dlg.exec() and (name := dlg.selected()):
            self.run_task(f"Installing {name}", lambda log: self.wsl.install(name))

    def on_set_default(self):
        if name := self._need_selection():
            self.run_task("Set default", lambda log: self.wsl.set_default(name))

    def on_terminate(self):
        if name := self._need_selection():
            self.run_task(f"Stopping {name}", lambda log: self.wsl.terminate(name))

    def on_export(self):
        if name := self._need_selection():
            path, _ = QFileDialog.getSaveFileName(self, "Export to", f"{name}.tar", "Tar (*.tar)")
            if path:
                self.run_task(f"Exporting {name}", lambda log: self.wsl.export(name, path))

    def on_import(self):
        tar, _ = QFileDialog.getOpenFileName(self, "Distro image", "", "Distro (*.tar *.tar.gz *.tar.xz *.wsl *.vhdx)")
        if not tar:
            return
        name, ok = QInputDialog.getText(self, "Import", "Name for the new distro:")
        dest = QFileDialog.getExistingDirectory(self, "Install location") if ok and name else ""
        if dest:
            self.run_task(f"Installing {name} from file",
                          lambda log: self.wsl.install_from_file(name, str(Path(dest) / name), tar))

    def on_unregister(self):
        name = self._need_selection()
        if name and QMessageBox.question(
            self, "Delete distribution",
            f"Permanently delete '{name}' and ALL its files?",
        ) == QMessageBox.Yes:
            self.run_task(f"Deleting {name}", lambda log: self.wsl.unregister(name))

    def on_install_url(self):
        url, ok = QInputDialog.getText(self, "Install from URL", "URL of a rootfs .tar/.tar.gz/.wsl/.vhdx:")
        if not ok or not url.strip():
            return
        name, ok = QInputDialog.getText(self, "Install from URL", "Name for the new distro:")
        if not ok or not name.strip():
            return
        dest = QFileDialog.getExistingDirectory(self, "Install location")
        if dest:
            self.run_task(f"Installing {name} from URL",
                          lambda log: self.wsl.install_from_url(name.strip(), str(Path(dest) / name.strip()), url.strip(), log))

    def on_open_gui(self):
        """One click: pick layer, auto-install it if needed, then show the distro's desktop."""
        name = self._need_selection()
        if not name:
            return
        self.desktop_distro.setCurrentText(name)
        self.tabs.setCurrentIndex(1)
        self.on_layer_launch(auto_install=True)

    def on_update(self):
        self.run_task("Updating WSL", lambda log: self.wsl.update())

    # --- desktop tab -------------------------------------------------------
    def _build_desktop_tab(self) -> QWidget:
        w = QWidget()
        self.desktop_distro = QComboBox()
        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self._show_layer)
        self.layer_info = QLabel(wordWrap=True)
        install = QPushButton("Install selected layer")
        launch = QPushButton("Launch")
        add = QPushButton("Add custom layer (.json)…")
        folder = QPushButton("Open layers folder")
        install.clicked.connect(self.on_layer_install)
        launch.clicked.connect(lambda: self.on_layer_launch())
        add.clicked.connect(self.on_layer_add)
        folder.clicked.connect(self.on_layers_folder)
        row = QHBoxLayout()
        for b in (install, launch, add, folder):
            row.addWidget(b)
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Distribution:"))
        lay.addWidget(self.desktop_distro)
        lay.addWidget(QLabel("UI layer (desktop environment / Wayland compositor / custom):"))
        lay.addWidget(self.layer_combo)
        lay.addWidget(self.layer_info)
        lay.addLayout(row)
        lay.addStretch()
        return w

    def reload_layers(self):
        self.layers = load_layers()
        self.layer_combo.clear()
        for l in self.layers:
            self.layer_combo.addItem(l.name + ("" if l.builtin else "  (custom)"), l.id)
        self._show_layer()

    def _layer(self) -> UILayer | None:
        i = self.layer_combo.currentIndex()
        return self.layers[i] if 0 <= i < len(self.layers) else None

    def _show_layer(self, *_):
        l = self._layer()
        if l:
            self.layer_info.setText(
                f"{l.description}\nMode: {l.mode}. Install recipes for: {', '.join(l.install) or 'none'}."
            )

    def on_layer_install(self):
        distro, layer = self.target_distro(self.desktop_distro), self._layer()
        if distro and layer:
            self._install_layer(distro, layer)

    def _install_layer(self, distro: str, layer: UILayer, then=None):
        def job(log):
            pm = self.wsl.detect_package_manager(distro)
            if not pm:
                raise WslError("Could not detect a supported package manager in this distro.")
            log(f"Package manager: {pm}")
            for line in self.wsl.stream(distro, layer.install_command(pm), user="root"):
                log(line)

        self.run_task(f"Installing {layer.name} in {distro}", job, then)

    def on_layer_launch(self, auto_install: bool = False):
        distro, layer = self.target_distro(self.desktop_distro), self._layer()
        if not distro or not layer:
            return

        def start(_ok=True):
            if not _ok:
                return
            if not self.wsl.wslg_available(distro):
                QMessageBox.warning(
                    self, "WSLg not detected",
                    "WSLg (/mnt/wslg) is missing. Run 'wsl --update' on Windows 11 / recent Windows 10, "
                    "then restart WSL.")
                return
            self.log(f"Launching {layer.name} in {distro}")
            self.wsl.spawn_gui(distro, layer.launch_command())

        if layer.check and not self.wsl.has_command(distro, layer.check):
            if auto_install or QMessageBox.question(
                self, "Not installed", f"{layer.name} is not installed in {distro}. Install it now?"
            ) == QMessageBox.Yes:
                self._install_layer(distro, layer, then=start)
            return
        start()

    def on_layer_add(self):
        path, _ = QFileDialog.getOpenFileName(self, "Layer definition", "", "JSON (*.json)")
        if not path:
            return
        try:
            layer = import_layer(Path(path))
        except (LayerError, ValueError, OSError) as e:
            QMessageBox.warning(self, "Invalid layer", str(e))
            return
        self.log(f"Added layer '{layer.name}'")
        self.reload_layers()

    def on_layers_folder(self):
        d = user_layers_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    # --- tools tab ---------------------------------------------------------
    def _build_tools_tab(self) -> QWidget:
        w = QWidget()
        self.tools_distro = QComboBox()
        self.cmd = QLineEdit(placeholderText="Command, e.g. firefox   or   ls -la ~")
        gui_btn = QPushButton("Launch as GUI app")
        run_btn = QPushButton("Run and show output")
        term = QPushButton("Open terminal")
        files = QPushButton("Browse files in Explorer")
        gui_btn.clicked.connect(self.on_run_gui)
        run_btn.clicked.connect(self.on_run_cmd)
        term.clicked.connect(lambda: (d := self.target_distro(self.tools_distro)) and self.wsl.open_terminal(d))
        files.clicked.connect(self.on_files)
        self.cmd.returnPressed.connect(self.on_run_gui)
        row = QHBoxLayout()
        for b in (gui_btn, run_btn, term, files):
            row.addWidget(b)
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Distribution:"))
        lay.addWidget(self.tools_distro)
        lay.addWidget(self.cmd)
        lay.addLayout(row)
        lay.addStretch()
        return w

    def on_run_gui(self):
        d = self.target_distro(self.tools_distro)
        if d and self.cmd.text().strip():
            self.wsl.spawn_gui(d, self.cmd.text())

    def on_run_cmd(self):
        d, cmd = self.target_distro(self.tools_distro), self.cmd.text().strip()
        if d and cmd:
            def job(log):
                for line in self.wsl.stream(d, cmd):
                    log(line)
            self.run_task(f"{d}$ {cmd}", job)

    def on_files(self):
        if d := self.target_distro(self.tools_distro):
            QDesktopServices.openUrl(QUrl.fromLocalFile(Wsl.explorer_path(d)))


def main() -> int:
    app = QApplication(sys.argv)
    if sys.platform == "win32" and not shutil.which("wsl.exe"):
        QMessageBox.critical(None, "WSL-GUI", "wsl.exe not found. Enable WSL first: 'wsl --install'.")
        return 1
    win = MainWindow()
    win.show()
    return app.exec()
