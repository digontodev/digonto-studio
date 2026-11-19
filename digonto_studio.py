#!/usr/bin/env python3
"""Digonto Studio - the one icon on your desktop. Opens every Digonto program in its own window."""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

import digonto_ui as ui

APP_NAME = "Digonto Studio"
VERSION = "2.9.0"
WIN = sys.platform == "win32"

# slug, name, entry file, one line, planned (not built yet)
PROGRAMS = [
    ("digonto-images", "Digonto Images", "digonto_images.py", "Photo editor: layers, brushes, selections, filters", False),
    ("digonto-vector", "Digonto Vector", "digonto_vector.py", "Logos, shapes and illustrations. SVG, PDF, PNG", False),
    ("digonto-audio", "Digonto Audio", "digonto_audio.py", "Record and edit sound: equalizer, echo, noise remover, voice/music split", False),
    ("digonto-logo", "Digonto Logo", "digonto_logo.py", "Type a company name, pick an idea, export a brand kit", False),
    ("digonto-qr", "Digonto QR", "digonto_qr.py", "QR codes with your own styles, shapes and logo", False),
    ("digonto-tools", "Digonto Tools", "digonto_tools.py", "Capture, crop, coordinates, match, remove background (AI)", False),
    ("digonto-pdf", "Digonto PDF", "digonto_pdf.py", "Create, shrink, organize, sign and edit PDF files", False),
    ("digonto-dtfrip", "Digonto DTFRIP", "digonto_dtfrip.py", "DTF printer", False),
    ("digonto-sublimation", "Digonto Sublimation", "digonto_sublimation.py", "Sublimation transfer", False),
    ("digonto-ssh", "Digonto SSH", "digonto_ssh_app.py", "SSH terminal and SFTP, servers synced everywhere", False),
    ("digonto-write", "Digonto Write", "digonto_write.py", "Documents: letters, reports, DOCX and PDF", False),
    ("digonto-sheets", "Digonto Sheets", "digonto_sheets.py", "Spreadsheets with formulas, XLSX and CSV", False),
    # next on the build list (more will be added)
    ("digonto-browser", "Digonto Browser", "", "Web browser on Chromium, like Chrome and Firefox", True),
    ("digonto-player", "Digonto Player", "digonto_player.py", "Play video and music: play lists, shuffle, full screen", False),
    ]
OPENS = {  # file extension -> program
    ".pdf": "digonto-pdf", ".png": "digonto-images", ".jpg": "digonto-images", ".jpeg": "digonto-images",
    ".dimg": "digonto-images", ".pimg": "digonto-images", ".psd": "digonto-images", ".webp": "digonto-images", ".bmp": "digonto-images", ".svg": "digonto-vector",
    ".dvec": "digonto-vector", ".ai": "digonto-vector", ".eps": "digonto-vector", ".dlgo": "digonto-logo", ".ptlogo": "digonto-logo", ".ddoc": "digonto-write", ".docx": "digonto-write", ".odt": "digonto-write",
    ".dsht": "digonto-sheets", ".xlsx": "digonto-sheets", ".csv": "digonto-sheets", ".dqr": "digonto-qr", ".pqr": "digonto-qr",
    ".daud": "digonto-audio", ".dmix": "digonto-audio", ".paud": "digonto-audio", ".wav": "digonto-audio", ".mp3": "digonto-audio", ".flac": "digonto-audio", ".ogg": "digonto-audio", ".opus": "digonto-audio",
    ".m4a": "digonto-audio", ".aac": "digonto-audio", ".aiff": "digonto-audio", ".aif": "digonto-audio", ".wma": "digonto-audio",
    ".mp4": "digonto-player", ".m4v": "digonto-player", ".mkv": "digonto-player", ".webm": "digonto-player", ".avi": "digonto-player", ".mov": "digonto-player", ".wmv": "digonto-player", ".mpg": "digonto-player", ".mpeg": "digonto-player",
}
BY_SLUG = {p[0]: p for p in PROGRAMS}


# standalone package (made by packaging/build.py): every program is inside this package, started by its launcher
STANDALONE = os.environ.get("DIGONTO_STANDALONE") == "1" and bool(os.environ.get("DIGONTO_LAUNCHER"))
LAUNCHER = os.environ.get("DIGONTO_LAUNCHER", "")


def base_dir():
    env = (os.environ.get("DIGONTO_BASE") or os.environ.get("PROTTOY_BASE"))
    if env:
        return env
    if STANDALONE:                                     # the program folder is read-only: shared data goes to the user folder
        if WIN:
            return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Digonto")
        if sys.platform == "darwin":
            return os.path.expanduser("~/Library/Application Support/Digonto")
        return os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "digonto")
    return os.path.dirname(os.path.dirname(HERE))      # .../digonto/digonto-studio/app -> .../digonto


def venv_python(slug):
    v = os.path.join(base_dir(), slug, "venv")
    if WIN:
        return os.path.join(v, "Scripts", "pythonw.exe")
    return os.path.join(v, "bin", "python")


def in_bundle(slug):
    """is the program's install file kept on this computer (so it can be installed from the tile)?"""
    if STANDALONE:
        return False
    return os.path.isfile(os.path.join(base_dir(), "_bundle", slug, "digonto-app.json"))


def app_folder(slug):
    if STANDALONE:
        return os.path.join(os.path.dirname(HERE), slug)
    return os.path.join(base_dir(), slug, "app")


def is_installed(slug):
    p = BY_SLUG[slug]
    if STANDALONE:
        return os.path.isfile(os.path.join(app_folder(slug), p[2]))
    return os.path.isfile(os.path.join(app_folder(slug), p[2])) and os.path.isfile(venv_python(slug))


# ---- recent files, shared by all programs: one small JSON file
def recent_path():
    return os.path.join(base_dir(), "recent.json")


def load_recent():
    try:
        with open(recent_path(), encoding="utf-8") as f:
            return [r for r in json.load(f) if isinstance(r, dict) and os.path.exists(r.get("path", ""))]
    except (OSError, ValueError):
        return []


def add_recent(slug, path):
    items = [r for r in load_recent() if r["path"] != path]
    items.insert(0, {"app": slug, "path": path, "time": time.time()})
    try:
        os.makedirs(base_dir(), exist_ok=True)
        with open(recent_path(), "w", encoding="utf-8") as f:
            json.dump(items[:40], f)
    except OSError:
        pass


def ago(t):
    d = time.time() - t
    if d < 90:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return time.strftime("today %H:%M", time.localtime(t)) if time.localtime(t).tm_yday == time.localtime().tm_yday else f"{int(d // 3600)} h ago"
    return time.strftime("%d %b", time.localtime(t))


ICON_OF = {}


def family_icon(slug, size=64):
    slug = ICON_OF.get(slug, slug)
    for p in (os.path.join(app_folder(slug), "assets", f"{slug}-128.png"), os.path.join(HERE, "assets", "family", f"{slug}-128.png")):
        if os.path.isfile(p):
            return QPixmap(p).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    # no logo yet (program is still on the build list): a simple green placeholder with the first letter
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    from PySide6.QtGui import QColor, QFont, QPainter
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor("#C9B6D8"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, size, size, size * 0.22, size * 0.22)
    f = QFont()
    f.setPixelSize(int(size * 0.5))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(pm.rect(), Qt.AlignCenter, slug.split("-", 1)[-1][:1].upper())
    p.end()
    return pm


class Tile(QFrame):
    def __init__(self, win, prog):
        super().__init__()
        self.win, self.prog = win, prog
        slug, name, _e, line, planned = prog
        self.installed = is_installed(slug)
        self.setObjectName("tile")
        self.setCursor(Qt.PointingHandCursor if self.installed else Qt.ArrowCursor)
        self.setMinimumHeight(170)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 14)
        v.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(family_icon(slug, 56))
        ic.setFixedHeight(58)
        ic.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        v.addWidget(ic)
        t = QLabel(name)
        t.setStyleSheet("font-size:16px; font-weight:700; color:#1B1040; background:transparent;")
        v.addWidget(t)
        d = QLabel(line)
        d.setWordWrap(True)
        d.setStyleSheet("font-size:12px; color:#5B5278; background:transparent;")
        v.addWidget(d, 1)
        bottom = QHBoxLayout()
        self.chip = QLabel()
        bottom.addWidget(self.chip, 0, Qt.AlignLeft)
        bottom.addStretch(1)
        self.btn = QPushButton()
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(self.on_button)
        bottom.addWidget(self.btn)
        v.addLayout(bottom)
        self.refresh()

    def on_button(self):
        self.win.run_setup(self.prog[0], "uninstall" if self.installed else "install")

    def refresh(self):
        slug, _n, _e, _l, planned = self.prog
        self.installed = is_installed(slug)
        running = self.win.running(slug)
        can_install = in_bundle(slug)
        green = "QPushButton{background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF6F8E, stop:1 #FFB05A); color:#2A1241;border:none;border-radius:7px;padding:5px 14px;font-weight:600;} QPushButton:hover{background:#FF6F8E;} QPushButton:disabled{background:#B398C8;}"
        plain = "QPushButton{background:white;color:#8A1C2B;border:1px solid #E5B8BE;border-radius:7px;padding:5px 12px;} QPushButton:hover{background:#FBE4E6;} QPushButton:disabled{color:#B9A0A4;}"
        busy = self.win.setup_running()
        self.btn.setEnabled(not busy and not running)
        self.btn.setVisible(False)
        if self.installed:
            text, bg, fg = ("Open now", "#E8DBF3", "#8A2150") if not running else ("Running", "#FFF1CC", "#7A5A00")
            if slug != "digonto-studio":
                self.btn.setText("Uninstall")
                self.btn.setStyleSheet(plain)
                self.btn.setVisible(in_bundle(slug) or True)
        elif can_install:
            text, bg, fg = "Not installed", "#FBE4E6", "#8A1C2B"
            self.btn.setText("Install")
            self.btn.setStyleSheet(green)
            self.btn.setVisible(True)
        elif planned:
            text, bg, fg = "Coming soon", "#ECEFEE", "#65596E"
        else:
            text, bg, fg = "Not installed", "#FBE4E6", "#8A1C2B"
        self.chip.setText(text)
        self.chip.setStyleSheet(f"font-size:11px; font-weight:600; color:{fg}; background:{bg}; border-radius:9px; padding:3px 10px;")
        self.setCursor(Qt.PointingHandCursor if self.installed else Qt.ArrowCursor)
        if self.installed:
            self.setStyleSheet("#tile{background:white; border:1px solid #DDD3E9; border-radius:12px;}"
                               "#tile:hover{border:1px solid #C2395C; background:#F7FCF9;}")
        else:
            self.setStyleSheet("#tile{background:#F7F9F8; border:1px dashed #D0C4E1; border-radius:12px;}")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.installed:
            self.win.open_program(self.prog[0])


class Grid(QWidget):
    """tiles in 1-4 columns, as many as fit"""

    def __init__(self):
        super().__init__()
        self.tiles = []
        self.g = QGridLayout(self)
        self.g.setContentsMargins(0, 0, 0, 0)
        self.g.setSpacing(16)
        self.cols = 0

    def set_tiles(self, tiles):
        for t in self.tiles:
            t.setParent(None)
        self.tiles = tiles
        self.cols = 0
        self.relayout()

    def relayout(self):
        cols = max(1, min(4, (self.width() + 16) // (200 + 16)))
        if cols == self.cols:
            return
        self.cols = cols
        for i in reversed(range(self.g.count())):
            self.g.takeAt(i)
        for i, t in enumerate(self.tiles):
            self.g.addWidget(t, i // cols, i % cols)
            t.show()
        for c in range(4):
            self.g.setColumnStretch(c, 1 if c < cols else 0)
        self.g.setRowStretch(len(self.tiles) // cols + 1, 1)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.procs = {}
        self.setWindowTitle(APP_NAME)
        self.icon = ui.app_icon(HERE, "digonto-studio")
        self.setWindowIcon(self.icon)
        ui.fit_window(self, 1240, 780)
        self.setMinimumSize(560, 420)
        self.setStyleSheet("QMainWindow{background:#F6F2FA;} QMenuBar{background:#EDE6F4; color:#1B1040;} QMenu{background:white; color:#1B1040;} QMenu::item:selected{background:#FBDCE5;} QStatusBar{background:#EDE6F4;color:#5B5278;}")
        mb = self.menuBar()
        fm = mb.addMenu("File")
        a = QAction("Open file ...", self, shortcut="Ctrl+O", triggered=self.open_file)
        fm.addAction(a)
        fm.addSeparator()
        fm.addAction(QAction("Install, repair or remove programs ...", self, triggered=self.open_installer))
        fm.addSeparator()
        fm.addAction(QAction("Exit", self, shortcut="Ctrl+Q", triggered=self.close))
        vm = mb.addMenu("View")
        vm.addAction(QAction("Refresh", self, shortcut="F5", triggered=self.refresh))
        hm = mb.addMenu("Help")
        hm.addAction(QAction("About Digonto Studio", self, triggered=self.about))

        body = QWidget()
        h = QHBoxLayout(body)
        h.setContentsMargins(24, 20, 24, 14)
        h.setSpacing(22)
        left = QVBoxLayout()
        title = QLabel("What do you want to make today?")
        title.setStyleSheet("font-size:24px; font-weight:700; color:#1B1040;")
        left.addWidget(title)
        self.grid = Grid()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
        sc.setWidget(self.grid)
        left.addWidget(sc, 1)
        h.addLayout(left, 3)

        right = QFrame()
        right.setObjectName("recent")
        right.setStyleSheet("#recent{background:white; border:1px solid #DDD3E9; border-radius:12px;}")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(16, 14, 16, 10)
        top = QHBoxLayout()
        rt = QLabel("Recent files")
        rt.setStyleSheet("font-size:15px; font-weight:700; color:#1B1040;")
        top.addWidget(rt, 1)
        ob = QPushButton("Open file ...")
        ob.clicked.connect(self.open_file)
        top.addWidget(ob)
        rv.addLayout(top)
        self.recent = QListWidget()
        self.recent.setFrameShape(QFrame.NoFrame)
        self.recent.setStyleSheet("QListWidget{background:white; color:#1B1040;} QMenu{background:white; color:#1B1040;} QListWidget::item{padding:8px 4px; border-bottom:1px solid #EAE3F2;} QListWidget::item:selected{background:#E8DBF3;color:#1B1040;}")
        self.recent.itemActivated.connect(self.open_recent)
        self.recent.itemDoubleClicked.connect(self.open_recent)
        rv.addWidget(self.recent, 1)
        self.empty = QLabel("Files you open with Digonto programs show up here.")
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet("color:#65596E; font-size:12px;")
        rv.addWidget(self.empty)
        h.addWidget(right, 1)

        hd = ui.make_header(APP_NAME, "All your Digonto programs in one place", self.icon, self.about, slim=False)
        ui.wrap_with_header(self, hd, body)
        self.timer = QTimer(self, interval=2000, timeout=self.tick)
        self.timer.start()
        self.refresh()

    def closeEvent(self, ev):
        self.timer.stop()
        ev.accept()
        app = QApplication.instance()
        app.quit()
        import threading
        threading.Timer(0.25, lambda: os._exit(0)).start()      # never linger in the background (a thread: works even if Qt is stuck)

    # ---- state
    def running(self, slug):
        p = self.procs.get(slug)
        return p is not None and p.poll() is None

    def tick(self):
        changed = False
        for t in self.grid.tiles:
            before = t.chip.text()
            t.refresh()
            changed |= before != t.chip.text()
        if len(load_recent()) != self.recent.count():
            self.fill_recent()

    def refresh(self):
        self.grid.set_tiles([Tile(self, p) for p in PROGRAMS])
        self.fill_recent()
        n = sum(is_installed(p[0]) for p in PROGRAMS)
        self.statusBar().showMessage(f"{n} of {len(PROGRAMS)} programs installed")

    def fill_recent(self):
        self.recent.clear()
        items = load_recent()
        for r in items:
            name = BY_SLUG.get(r["app"], (0, r["app"]))[1]
            it = QListWidgetItem(f"{os.path.basename(r['path'])}\n{name}  -  {ago(r['time'])}")
            it.setData(Qt.UserRole, r)
            it.setToolTip(r["path"])
            it.setIcon(QIcon(family_icon(r["app"], 32)))
            self.recent.addItem(it)
        self.empty.setVisible(not items)

    # ---- install / uninstall one program from its tile (opens the Digonto installer window for that program)
    def setup_running(self):
        p = getattr(self, "setup_proc", None)
        return p is not None and p.poll() is None

    def open_installer(self):
        """the Digonto Studio installer window: add programs, update, repair or remove everything"""
        if not (STANDALONE and LAUNCHER and os.path.exists(LAUNCHER)):
            QMessageBox.information(self, APP_NAME, "The installer is part of the Digonto Studio download from digonto.dev.")
            return
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if WIN:
            kw["creationflags"] = 0x00000008 | 0x00000200
        else:
            kw["start_new_session"] = True
        try:
            subprocess.Popen([LAUNCHER, "--setup"], **kw)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"The installer did not start:\n{e}")

    def run_setup(self, slug, action):
        prog = BY_SLUG[slug]
        if STANDALONE:                       # the installed Digonto removes one program itself (it asks first)
            if action != "uninstall":
                r = QMessageBox.question(self, APP_NAME, f"Open the Digonto Studio installer to add {prog[1]}?\n"
                                         "(Also in the File menu: Install, repair or remove programs.)")
                if r == QMessageBox.Yes:
                    self.open_installer()
                return
            kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if WIN:
                kw["creationflags"] = 0x00000008 | 0x00000200
            else:
                kw["start_new_session"] = True
            try:
                self.setup_proc = subprocess.Popen([LAUNCHER, "--uninstall", slug], **kw)
            except OSError as e:
                QMessageBox.warning(self, APP_NAME, f"Could not start the uninstaller:\n{e}")
                return
            self.tick()
            return
        script = os.path.join(base_dir(), "_bundle", "digonto_setup.py")
        if not os.path.isfile(script):
            QMessageBox.information(self, APP_NAME, "The install files are not on this computer. Run \"Install Digonto\" from the downloaded folder.")
            return
        if action == "uninstall" and QMessageBox.question(
                self, APP_NAME, f"Remove {prog[1]} from this computer?\n\nYour own files are not touched.") != QMessageBox.Yes:
            return
        py = sys.executable
        kw = {"cwd": os.path.dirname(script), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if WIN:
            kw["creationflags"] = 0x00000008 | 0x00000200
        else:
            kw["start_new_session"] = True
        try:
            self.setup_proc = subprocess.Popen([py, script, "--gui", slug, "--action", action], **kw)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Could not start the installer:\n{e}")
            return
        self.tick()

    # ---- opening
    def open_program(self, slug, files=()):
        prog = BY_SLUG[slug]
        if not is_installed(slug):
            msg = "is coming in a later version." if prog[4] else "is not installed on this computer. Run the Digonto installer again to add it."
            QMessageBox.information(self, APP_NAME, f"{prog[1]} {msg}")
            return False
        if self.running(slug) and not files:
            self.statusBar().showMessage(f"{prog[1]} is already open - look for its window.", 5000)
            return True
        cmd = [venv_python(slug), os.path.join(app_folder(slug), prog[2]), *files]
        if STANDALONE:
            cmd = [LAUNCHER, "--app", slug, *files]
            # the program's own starter (its own Dock / taskbar icon), made by the Digonto installer
            mac_app = os.path.join("/Applications", f"{prog[1]}.app")
            if sys.platform == "darwin" and os.path.isfile(os.path.join(mac_app, "Contents", "MacOS", prog[1])):
                # through macOS itself: the program runs as its own app (its own Dock icon, and macOS asks for
                # permissions such as Screen Recording for that program, not for Studio). -W: wait while it runs
                cmd = ["open", "-W", "-a", mac_app] + (["--args", *files] if files else [])
            own = os.path.join(os.path.dirname(LAUNCHER), f"{slug}.exe") if WIN else ""
            if own and os.path.isfile(own):
                cmd = [own, *files]
        elif sys.platform == "darwin":          # through the program's own .app, so the Dock shows its name and icon (not "Python")
            for d in ("/Applications", os.path.expanduser("~/Applications")):
                ex = os.path.join(d, f"{prog[1]}.app", "Contents", "MacOS", prog[1])
                if os.path.isfile(ex):
                    cmd = [ex, *files]
                    break
        kw = {"cwd": app_folder(slug), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if WIN:
            kw["creationflags"] = 0x00000008 | 0x00000200
        else:
            kw["start_new_session"] = True
        try:
            self.procs[slug] = subprocess.Popen(cmd, **kw)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Could not start {prog[1]}:\n{e}")
            return False
        self.statusBar().showMessage(f"Opening {prog[1]} ...", 4000)
        QTimer.singleShot(1500, self.tick)
        return True

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open file")
        if path:
            self.open_path(path)

    def open_path(self, path):
        slug = OPENS.get(os.path.splitext(path)[1].lower())
        if not slug:
            QMessageBox.information(self, APP_NAME, "No Digonto program opens this kind of file yet.")
            return
        if self.open_program(slug, [path]):
            add_recent(slug, path)
            self.fill_recent()

    def open_recent(self, item):
        r = item.data(Qt.UserRole)
        if os.path.exists(r["path"]) and self.open_program(r["app"], [r["path"]]):
            add_recent(r["app"], r["path"])

    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<h3>{APP_NAME} {VERSION}</h3><p>The one icon on your desktop. Each program opens in its own window with its own "
                          "menu and its own icon, so you can also keep any of them in the Dock or taskbar.</p>"
                          "<p>Exit closes only this window; programs that are open keep running.</p>"
                          "<p>Built with Qt for Python (PySide6-Essentials), locked with SHA-256 hashes.</p>")


def main():
    if "--version" in sys.argv:
        print(VERSION)
        return
    ui.mac_app_name(APP_NAME)
    app = QApplication(sys.argv)
    ui.setup_app(app, APP_NAME, "digonto-studio", ui.app_icon(HERE, "digonto-studio"))
    w = Main()
    w.show()
    for a in sys.argv[1:]:
        if os.path.isfile(a):
            w.open_path(a)
    app.setQuitOnLastWindowClosed(True)
    rc = app.exec()
    sys.stdout.flush()
    os._exit(rc)


if __name__ == "__main__":
    main()
