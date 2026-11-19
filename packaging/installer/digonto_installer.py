"""Digonto Studio installer window.

A small, phone-sized window: splash, Digonto header, an animated horizon strip, the list of programs with their
sizes, a progress bar, the install folder, the language and the buttons Install / Update / Repair / Uninstall /
Cancel / Quit.  The real work (copying, icons, uninstall entries) is done by a Backend object, so the window looks
and behaves the same on macOS, Windows and Linux.
"""
import math
import os
import sys
import threading

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGraphicsOpacityEffect,
                               QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QStackedLayout, QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
WIDTH, HEIGHT = 400, 740

NIGHT, PLUM, WINE = "#1D1548", "#4A1F6E", "#8A2150"
PINK, AMBER, INK = "#FF6F8E", "#FFB05A", "#2A1241"
SOFT, LINE, CARD = "#6B5F86", "#E7E1F0", "#FFFFFF"

STYLE = f"""
QWidget#root {{ background: #F7F4FB; }}
QLabel {{ color: {INK}; }}
QLabel.caption {{ color: {SOFT}; font-size: 12px; font-weight: 600; }}
QFrame#box {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ width: 8px; background: transparent; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: #D6CDE4; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QCheckBox {{ spacing: 10px; color: {INK}; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1.5px solid #B9AFD3; background: white; }}
QCheckBox::indicator:checked {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {PINK}, stop:1 {AMBER});
                               border-color: {PINK}; image: url(CHECK); }}
QCheckBox::indicator:disabled {{ background: #EEE9F4; border-color: #DDD5E8; }}
QLineEdit, QComboBox {{ background: white; border: 1px solid {LINE}; border-radius: 8px; padding: 6px 9px;
                        color: {INK}; font-size: 13px; }}
QLineEdit:read-only {{ background: #FBFAFD; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QProgressBar {{ background: #ECE6F3; border: none; border-radius: 4px; height: 8px; }}
QProgressBar::chunk {{ border-radius: 4px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {PINK}, stop:1 {AMBER}); }}
QPushButton {{ background: white; border: 1px solid #D9D0E6; border-radius: 9px; padding: 8px 6px;
               color: {INK}; font-weight: 600; font-size: 13px; }}
QPushButton:hover {{ background: #F4EEFA; }}
QPushButton:disabled {{ color: #B7AECB; background: #F8F6FB; border-color: #ECE6F3; }}
QPushButton#primary {{ border: none; color: {INK};
                       background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {PINK}, stop:1 {AMBER}); }}
QPushButton#primary:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #FF86A1, stop:1 #FFC273); }}
QPushButton#primary:disabled {{ background: #EFE9F5; color: #B7AECB; }}
QPushButton#danger {{ color: #B4234A; }}
QPushButton#danger:disabled {{ color: #B7AECB; }}
"""


def asset(*parts):
    for base in (os.path.join(HERE, "assets"), HERE):
        p = os.path.join(base, *parts)
        if os.path.exists(p):
            return p
    return os.path.join(HERE, "assets", *parts)


def fmt_size(mb):
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


# ----------------------------------------------------------------------------------------------------- drawing --
class HorizonStrip(QWidget):
    """the animated horizon: a dusk sky, a sun rising and setting slowly on the horizon line, soft moving waves"""

    def __init__(self, height=46, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.t = 0.0
        self.timer = QTimer(self, interval=33, timeout=self._tick)
        self.timer.start()

    def _tick(self):
        self.t += 0.033
        self.update()

    def paintEvent(self, _):
        w, h, t = self.width(), self.height(), self.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        sky = QLinearGradient(0, 0, 0, h)
        sky.setColorAt(0, QColor(NIGHT))
        sky.setColorAt(0.55, QColor(PLUM))
        sky.setColorAt(1, QColor(WINE))
        p.fillRect(self.rect(), sky)
        horizon = h * 0.66
        # the sun slowly travels across and gently rises and sets
        sx = (0.12 + 0.76 * (0.5 - 0.5 * math.cos(t * 0.35))) * w
        sy = horizon - 4 - 7 * math.sin(t * 0.7)
        glow = QRadialGradient(QPointF(sx, sy), h * 0.9)
        glow.setColorAt(0, QColor(255, 176, 90, 150))
        glow.setColorAt(0.4, QColor(255, 111, 142, 60))
        glow.setColorAt(1, QColor(255, 111, 142, 0))
        p.fillRect(self.rect(), glow)
        p.save()
        p.setClipRect(QRectF(0, 0, w, horizon))
        sun = QLinearGradient(0, sy - 13, 0, sy + 13)
        sun.setColorAt(0, QColor(AMBER))
        sun.setColorAt(1, QColor(PINK))
        p.setPen(Qt.NoPen)
        p.setBrush(sun)
        p.drawEllipse(QPointF(sx, sy), 13, 13)
        p.restore()
        # a few stars
        p.setPen(Qt.NoPen)
        for i in range(14):
            x = (i * 97.3 % 1) * w if False else ((i * 61) % 400) / 400 * w
            y = ((i * 37) % 23) / 23 * horizon * 0.7 + 3
            a = int(70 + 60 * math.sin(t * 1.3 + i))
            p.setBrush(QColor(255, 255, 255, max(0, a)))
            p.drawEllipse(QPointF(x, y), 1.0, 1.0)
        # the water below the horizon, with moving light lines
        water = QLinearGradient(0, horizon, 0, h)
        water.setColorAt(0, QColor(110, 30, 90))
        water.setColorAt(1, QColor(NIGHT))
        p.fillRect(QRectF(0, horizon, w, h - horizon), water)
        p.setPen(QPen(QColor(255, 190, 130, 210), 1.4))
        p.drawLine(QPointF(0, horizon), QPointF(w, horizon))
        for k in range(3):
            y = horizon + 4 + k * 4.2
            path = QPainterPath()
            path.moveTo(0, y)
            for x in range(0, w + 8, 8):
                path.lineTo(x, y + 1.2 * math.sin(x / 26.0 + t * (1.4 + k * 0.5) + k))
            p.setPen(QPen(QColor(255, 160, 120, 90 - k * 25), 1.0))
            p.drawPath(path)
        # the reflection of the sun on the water
        p.setPen(Qt.NoPen)
        for k in range(4):
            rw = 18 - k * 4 + 2 * math.sin(t * 2 + k)
            p.setBrush(QColor(255, 180, 110, 120 - k * 25))
            p.drawRoundedRect(QRectF(sx - rw / 2, horizon + 3 + k * 3.5, rw, 1.6), 1, 1)


class Header(QWidget):
    """Digonto header: the banner logo on the dusk gradient"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(92)
        self.banner = QPixmap(asset("digonto-banner.png"))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        g = QLinearGradient(0, 0, self.width(), 0)
        g.setColorAt(0, QColor(NIGHT))
        g.setColorAt(0.55, QColor(PLUM))
        g.setColorAt(1, QColor(WINE))
        p.fillRect(self.rect(), g)
        if not self.banner.isNull():
            bh = 70
            bw = self.banner.width() * bh / self.banner.height()
            p.drawPixmap(QRectF((self.width() - bw) / 2, (self.height() - bh) / 2, bw, bh), self.banner,
                         QRectF(self.banner.rect()))


class Splash(QWidget):
    """the opening animation: the sun rises over the horizon, then the Digonto logo fades in"""

    done = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.t = 0.0
        self.setting = False
        self.banner = QPixmap(asset("digonto-banner.png"))
        self.timer = QTimer(self, interval=16, timeout=self._tick)

    def start(self, setting=False):
        """sunrise (opening) or sunset (closing)"""
        self.setting = setting
        self.t = 0.0
        self.timer.start()

    def _tick(self):
        self.t += 0.016
        self.update()
        if self.t >= (1.5 if self.setting else 2.1):
            self.timer.stop()
            self.done.emit()

    def mousePressEvent(self, _):
        """a click skips the animation"""
        if self.timer.isActive():
            self.timer.stop()
            self.done.emit()

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        # sunset = the sunrise played backwards: logo fades out first, then the sun goes down
        t = (2.1 - self.t * 1.4) if self.setting else self.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        sky = QLinearGradient(0, 0, 0, h)
        sky.setColorAt(0, QColor(NIGHT))
        sky.setColorAt(0.6, QColor(PLUM))
        sky.setColorAt(1, QColor(WINE))
        p.fillRect(self.rect(), sky)
        horizon = h * 0.62
        rise = min(1.0, t / 1.2)
        ease = 1 - (1 - rise) ** 3
        r = 46
        sy = horizon + r - ease * (r + 30)
        glow = QRadialGradient(QPointF(w / 2, sy), 260)
        glow.setColorAt(0, QColor(255, 176, 90, int(160 * ease)))
        glow.setColorAt(1, QColor(255, 111, 142, 0))
        p.fillRect(self.rect(), glow)
        p.save()
        p.setClipRect(QRectF(0, 0, w, horizon))
        g = QLinearGradient(0, sy - r, 0, sy + r)
        g.setColorAt(0, QColor(AMBER))
        g.setColorAt(1, QColor(PINK))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(w / 2, sy), r, r)
        p.restore()
        # stars that come out as the sky darkens
        p.setPen(Qt.NoPen)
        for i in range(40):
            x = ((i * 89) % 400) / 400 * w
            y = ((i * 53) % 97) / 97 * horizon * 0.75 + 6
            a = int((60 + 70 * math.sin(self.t * 2.2 + i)) * (1.15 - ease))
            p.setBrush(QColor(255, 255, 255, max(0, min(255, a))))
            p.drawEllipse(QPointF(x, y), 1.2 if i % 5 else 1.7, 1.2 if i % 5 else 1.7)
        # the water, with moving light lines
        water = QLinearGradient(0, horizon, 0, h)
        water.setColorAt(0, QColor(110, 30, 90))
        water.setColorAt(1, QColor(NIGHT))
        p.fillRect(QRectF(0, horizon, w, h - horizon), water)
        p.setPen(QPen(QColor(255, 190, 130, 220), 2))
        p.drawLine(QPointF(0, horizon), QPointF(w, horizon))
        for k in range(9):
            y = horizon + 10 + k * k * 4.5
            amp = 1.5 + k * 0.6
            path = QPainterPath()
            path.moveTo(0, y)
            for x in range(0, w + 10, 10):
                path.lineTo(x, y + amp * math.sin(x / (30.0 + k * 6) + self.t * (1.2 + k * 0.25) + k))
            p.setPen(QPen(QColor(255, 160, 120, max(10, 80 - k * 8)), 1.2))
            p.drawPath(path)
        # the sun's reflection: shimmering bars under the sun, brighter while the sun is up
        vis = max(0.0, min(1.0, (horizon - (sy - r)) / (2 * r)))      # how much of the sun is above water
        p.setPen(Qt.NoPen)
        for k in range(12):
            rw = (r * 1.6 - k * 6) + 6 * math.sin(self.t * 3 + k * 1.7)
            if rw <= 4:
                continue
            a = int((150 - k * 11) * vis)
            p.setBrush(QColor(255, 180, 110, max(0, a)))
            yy = horizon + 6 + k * (6 + k * 0.8)
            p.drawRoundedRect(QRectF(w / 2 - rw / 2 + 3 * math.sin(self.t * 2 + k), yy, rw, 2.6), 1.3, 1.3)
        fade = max(0.0, min(1.0, (t - 0.9) / 0.7))
        if fade > 0 and not self.banner.isNull():
            p.setOpacity(fade)
            bw = 250
            bh = self.banner.height() * bw / self.banner.width()
            p.drawPixmap(QRectF((w - bw) / 2, h * 0.22, bw, bh), self.banner, QRectF(self.banner.rect()))
            p.setOpacity(fade)
            p.setPen(QColor(255, 255, 255))
            f = QFont(self.font())
            f.setPointSizeF(13.5)
            f.setWeight(QFont.DemiBold)          # semi-bold: softer than bold, still easy to read
            p.setFont(f)
            p.drawText(QRectF(0, h * 0.8, w, 30), Qt.AlignCenter,
                       "See you soon" if self.setting else "Digonto Studio Setup")


# --------------------------------------------------------------------------------------------------- the list --
class AppRow(QWidget):
    toggled = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 7, 14, 7)
        lay.setSpacing(10)
        self.box = QCheckBox()
        self.box.setChecked(app.get("checked", True))
        self.box.toggled.connect(lambda *_: self.toggled.emit())
        if app.get("required"):
            self.box.setChecked(True)
            self.box.setEnabled(False)
        icon = QLabel()
        pm = QPixmap(app.get("icon", ""))
        if not pm.isNull():
            pm = pm.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(2.0)
            icon.setPixmap(pm)
        icon.setFixedSize(32, 32)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel(app["name"])
        name.setStyleSheet("font-weight:600; font-size:13.5px;")
        state = app.get("state", "")
        self.sub = QLabel(state)
        self.sub.setStyleSheet(f"color:{SOFT}; font-size:11.5px;")
        text.addWidget(name)
        text.addWidget(self.sub)
        size = QLabel(fmt_size(app["size_mb"]))
        size.setStyleSheet(f"color:{SOFT}; font-size:12px;")
        size.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.box)
        lay.addWidget(icon)
        lay.addLayout(text, 1)
        lay.addWidget(size)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if self.box.isEnabled():
            self.box.toggle()
        super().mouseReleaseEvent(e)


class Done(QDialog):
    def __init__(self, parent, title, text):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setFixedSize(300, 190)
        self.setStyleSheet(STYLE + f"QDialog {{ background: white; border: 1px solid {LINE}; border-radius: 14px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        sun = HorizonStrip(34)
        lay.addWidget(sun)
        t = QLabel(title)
        t.setStyleSheet("font-size:16px; font-weight:700; margin-top:8px;")
        t.setAlignment(Qt.AlignCenter)
        m = QLabel(text)
        m.setWordWrap(True)
        m.setAlignment(Qt.AlignCenter)
        m.setStyleSheet(f"color:{SOFT}; font-size:12.5px;")
        ok = QPushButton("OK")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        lay.addWidget(t)
        lay.addWidget(m)
        lay.addStretch(1)
        lay.addWidget(ok)


# ------------------------------------------------------------------------------------------------- the window --
class Worker(QObject):
    progress = Signal(float)
    finished = Signal(bool, str)        # ok, message


class InstallerWindow(QWidget):
    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.cancel_event = threading.Event()
        self.busy = False
        self.setWindowTitle("Digonto Studio Setup")
        self.setFixedSize(WIDTH, HEIGHT)
        icon = asset("digonto-studio-256.png")
        if os.path.isfile(icon):
            self.setWindowIcon(QIcon(icon))
        check = asset("check.svg").replace("\\", "/")
        self.setStyleSheet(STYLE.replace("CHECK", check))
        self.setObjectName("root")

        self.stack = QStackedLayout(self)
        self.splash = Splash()
        self.splash.done.connect(self._splash_done)
        self.leaving = False
        self.main = QWidget()
        self.main.setObjectName("root")
        self.stack.addWidget(self.splash)
        self.stack.addWidget(self.main)
        self._build_main()
        self.worker = Worker()
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)

    # ------------------------------------------------------------------ layout
    def _build_main(self):
        v = QVBoxLayout(self.main)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(Header())
        v.addWidget(HorizonStrip(46))
        body = QVBoxLayout()
        body.setContentsMargins(18, 14, 18, 16)
        body.setSpacing(8)
        v.addLayout(body, 1)

        top = QHBoxLayout()
        cap = QLabel("Programs")
        cap.setProperty("class", "caption")
        top.addWidget(cap)
        top.addStretch(1)
        self.total = QLabel()
        self.total.setStyleSheet(f"color:{SOFT}; font-size:12px;")
        top.addWidget(self.total)
        body.addLayout(top)

        box = QFrame()
        box.setObjectName("box")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 4, 0, 4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.rows_lay = QVBoxLayout(inner)
        self.rows_lay.setContentsMargins(0, 0, 0, 0)
        self.rows_lay.setSpacing(0)
        scroll.setWidget(inner)
        bl.addWidget(scroll)
        body.addWidget(box, 1)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        body.addSpacing(4)
        body.addWidget(self.bar)
        body.addSpacing(6)

        cap = QLabel("Install to")
        cap.setProperty("class", "caption")
        body.addWidget(cap)
        row = QHBoxLayout()
        self.folder = QLineEdit(self.backend.default_folder())
        self.folder.setReadOnly(True)
        self.change = QPushButton("Change…")
        self.change.setFixedWidth(86)
        self.change.clicked.connect(self._choose_folder)
        self.change.setVisible(self.backend.can_change_folder())
        row.addWidget(self.folder, 1)
        row.addWidget(self.change)
        body.addLayout(row)

        cap = QLabel("Language")
        cap.setProperty("class", "caption")
        body.addWidget(cap)
        self.lang = QComboBox()
        self.lang.addItems(["English"])
        body.addWidget(self.lang)
        body.addSpacing(8)

        grid = QHBoxLayout()
        grid.setSpacing(7)
        self.b_install = QPushButton("Install")
        self.b_install.setObjectName("primary")
        self.b_update = QPushButton("Update")
        self.b_repair = QPushButton("Repair")
        self.b_uninstall = QPushButton("Uninstall")
        self.b_uninstall.setObjectName("danger")
        for b in (self.b_install, self.b_update, self.b_repair, self.b_uninstall):
            grid.addWidget(b)
        body.addLayout(grid)
        row2 = QHBoxLayout()
        row2.setSpacing(7)
        self.b_cancel = QPushButton("Cancel")
        self.b_quit = QPushButton("Quit")
        row2.addWidget(self.b_cancel)
        row2.addWidget(self.b_quit)
        body.addLayout(row2)

        self.b_install.clicked.connect(lambda: self._run("install"))
        self.b_update.clicked.connect(lambda: self._run("update"))
        self.b_repair.clicked.connect(lambda: self._run("repair"))
        self.b_uninstall.clicked.connect(lambda: self._run("uninstall"))
        self.b_cancel.clicked.connect(self._cancel)
        self.b_quit.clicked.connect(self.close)
        self._fill()

    def _fill(self):
        while self.rows_lay.count():
            it = self.rows_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.rows = []
        apps = self.backend.apps()
        for i, a in enumerate(apps):
            r = AppRow(a)
            r.toggled.connect(self._update_state)
            self.rows.append(r)
            self.rows_lay.addWidget(r)
            if i < len(apps) - 1:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background:{LINE}; margin: 0 12px;")
                self.rows_lay.addWidget(sep)
        self.rows_lay.addStretch(1)
        self._update_state()

    # ------------------------------------------------------------------ state
    def selected(self):
        return [r.app for r in self.rows if r.box.isChecked()]

    def _update_state(self):
        sel = self.selected()
        mb = sum(a["size_mb"] for a in sel)
        self.total.setText(f"{len(sel)} selected · {fmt_size(mb)}")
        installed = any(a.get("installed") for a in sel)
        outdated = any(a.get("installed") and a.get("outdated") for a in sel)
        new = any(not a.get("installed") for a in sel)
        idle = not self.busy
        self.b_install.setEnabled(idle and new)
        self.b_update.setEnabled(idle and outdated)
        self.b_repair.setEnabled(idle and installed)
        self.b_uninstall.setEnabled(idle and installed)
        self.b_cancel.setEnabled(self.busy)
        self.b_quit.setEnabled(idle)
        self.change.setEnabled(idle and not any(a.get("installed") for a in self.backend.apps()))
        for r in self.rows:
            r.box.setEnabled(idle and not r.app.get("required"))

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Install Digonto to", self.folder.text())
        if d:
            self.folder.setText(self.backend.normalise_folder(d))

    # ------------------------------------------------------------------ work
    def _run(self, action):
        sel = self.selected()
        if not sel:
            return
        self.busy = True
        self.cancel_event.clear()
        self.bar.setValue(0)
        self._update_state()
        folder = self.folder.text()

        def work():
            try:
                ok, msg = self.backend.run(action, sel, folder, self.worker.progress.emit, self.cancel_event)
            except Exception as e:                                   # noqa: BLE001
                ok, msg = False, str(e)
            self.worker.finished.emit(ok, msg)

        threading.Thread(target=work, daemon=True).start()

    def _cancel(self):
        self.cancel_event.set()
        self.b_cancel.setEnabled(False)

    def _on_progress(self, frac):
        self.bar.setValue(int(max(0.0, min(1.0, frac)) * 1000))

    def _on_finished(self, ok, msg):
        self.busy = False
        if ok:
            self.bar.setValue(1000)
        self._fill()
        cancelled = self.cancel_event.is_set()
        if cancelled:
            title, text = "Stopped", msg or "Nothing was changed."
        elif ok:
            title, text = "All done", msg or "Installation is finished."
        else:
            title, text = "Something went wrong", msg
        Done(self, title, text).exec()
        if not ok or cancelled:
            self.bar.setValue(0)

    def closeEvent(self, e):
        if self.busy:
            e.ignore()
            return
        if not self.leaving:                     # first the sunset, then close
            e.ignore()
            self.leaving = True
            self.stack.setCurrentWidget(self.splash)
            self.splash.start(setting=True)
            return
        super().closeEvent(e)
        if callable(getattr(self, "closed", None)):
            self.closed()

    def _splash_done(self):
        if self.leaving:
            self.close()
        else:
            self._show_main()

    def start(self):
        self.stack.setCurrentWidget(self.splash)
        self.splash.start()

    def _show_main(self):
        eff = QGraphicsOpacityEffect(self.main)
        self.main.setGraphicsEffect(eff)
        self.stack.setCurrentWidget(self.main)
        self._fade = QPropertyAnimation(eff, b"opacity", self)
        self._fade.setDuration(350)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.finished.connect(lambda: self.main.setGraphicsEffect(None))
        self._fade.start()


# ---------------------------------------------------------------------------------- the 600 x 400 first window --
WELCOME_W, WELCOME_H = 600, 400


def paint_welcome(p, w, h, t=1.0, text=True):
    """the horizon background of the first window (also saved as the Mac .dmg background)"""
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    sky = QLinearGradient(0, 0, 0, h)
    sky.setColorAt(0, QColor(NIGHT))
    sky.setColorAt(0.6, QColor(PLUM))
    sky.setColorAt(1, QColor(WINE))
    p.fillRect(QRectF(0, 0, w, h), sky)
    horizon = h * 0.76
    sx, sy, r = w / 2, horizon + 6, 58 * h / 400
    glow = QRadialGradient(QPointF(sx, sy), w * 0.55)
    glow.setColorAt(0, QColor(255, 176, 90, 120))
    glow.setColorAt(0.5, QColor(255, 111, 142, 40))
    glow.setColorAt(1, QColor(255, 111, 142, 0))
    p.fillRect(QRectF(0, 0, w, h), glow)
    p.setPen(Qt.NoPen)
    for i in range(46):
        x = ((i * 89) % 600) / 600 * w
        y = ((i * 53) % 97) / 97 * horizon * 0.8 + 6
        a = int(70 + 60 * math.sin(t * 2.0 + i))
        p.setBrush(QColor(255, 255, 255, max(0, a)))
        d = 1.7 if i % 5 == 0 else 1.1
        p.drawEllipse(QPointF(x, y), d, d)
    p.save()
    p.setClipRect(QRectF(0, 0, w, horizon))
    g = QLinearGradient(0, sy - r, 0, sy + r)
    g.setColorAt(0, QColor(AMBER))
    g.setColorAt(1, QColor(PINK))
    p.setBrush(g)
    p.setOpacity(0.55)
    p.drawEllipse(QPointF(sx, sy + r * 0.35), r * 1.25, r * 1.25)
    p.setOpacity(1.0)
    p.restore()
    water = QLinearGradient(0, horizon, 0, h)
    water.setColorAt(0, QColor(110, 30, 90))
    water.setColorAt(1, QColor(NIGHT))
    p.fillRect(QRectF(0, horizon, w, h - horizon), water)
    p.setPen(QPen(QColor(255, 190, 130, 220), 1.6))
    p.drawLine(QPointF(0, horizon), QPointF(w, horizon))
    for k in range(6):
        y = horizon + 8 + k * k * 3.2
        path = QPainterPath()
        path.moveTo(0, y)
        for x in range(0, int(w) + 10, 10):
            path.lineTo(x, y + (1.3 + k * 0.5) * math.sin(x / (34.0 + k * 7) + t * (1.2 + k * 0.3) + k))
        p.setPen(QPen(QColor(255, 150, 120, max(8, 46 - k * 7)), 1.0))
        p.drawPath(path)
    p.setPen(Qt.NoPen)
    for k in range(8):
        rw = (r * 1.7 - k * 9) + 5 * math.sin(t * 3 + k * 1.7)
        if rw > 4:
            p.setBrush(QColor(255, 180, 110, max(0, 130 - k * 15)))
            p.drawRoundedRect(QRectF(sx - rw / 2, horizon + 5 + k * (5 + k * 0.7), rw, 2.4), 1.2, 1.2)
    if text:
        f = QFont()
        f.setPointSizeF(15 * h / 400)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(0, h * 0.565, w, h * 0.08), Qt.AlignCenter, "Double-click to install")


class WelcomeWindow(QWidget):
    """the first window on Windows and Linux, like the Mac .dmg window: horizon background, the Studio icon,
    "Double-click to install"; no toolbar, no address bar, fixed 600 x 400"""

    open_installer = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Digonto Studio")
        self.setFixedSize(WELCOME_W, WELCOME_H)
        icon = asset("digonto-studio-256.png")
        self.icon = QPixmap(icon)
        if os.path.isfile(icon):
            self.setWindowIcon(QIcon(icon))
        self.t = 0.0
        self.hover = False
        self.hover_doc = False
        self.setMouseTracking(True)
        self.timer = QTimer(self, interval=40, timeout=self._tick)
        self.timer.start()

    def _tick(self):
        self.t += 0.04
        self.update()

    def icon_rect(self):
        s = 120
        return QRectF((self.width() - s) / 2, 65, s, s)        # same place as the icon on the Mac disk

    def readme_rect(self):
        """READ ME FIRST.txt in the bottom right corner, like on the Mac disk"""
        return QRectF(self.width() - 118, self.height() - 92, 104, 80)

    @staticmethod
    def paint_doc(p, r, hover=False):
        if hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 34))
            p.drawRoundedRect(r.adjusted(-4, -4, 4, 4), 10, 10)
        w, h = 30, 38
        x, y = r.center().x() - w / 2, r.top() + 4
        page = QPainterPath()
        page.moveTo(x, y)
        page.lineTo(x + w - 9, y)
        page.lineTo(x + w, y + 9)
        page.lineTo(x + w, y + h)
        page.lineTo(x, y + h)
        page.closeSubpath()
        p.setPen(QPen(QColor(200, 190, 220), 1))
        p.setBrush(QColor(250, 248, 252))
        p.drawPath(page)
        p.setPen(QPen(QColor(170, 160, 195), 1.2))
        for i in range(4):
            p.drawLine(QPointF(x + 6, y + 14 + i * 5), QPointF(x + w - 6 - (i == 3) * 8, y + 14 + i * 5))
        f = QFont()
        f.setPointSizeF(9)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(r.left() - 10, y + h + 4, r.width() + 20, 18), Qt.AlignCenter, "READ ME FIRST.txt")

    def paintEvent(self, _):
        p = QPainter(self)
        paint_welcome(p, self.width(), self.height(), self.t)
        r = self.icon_rect()
        if self.hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 38))
            p.drawRoundedRect(r.adjusted(-10, -10, 10, 10), 22, 22)
        if not self.icon.isNull():
            p.drawPixmap(r, self.icon, QRectF(self.icon.rect()))
        f = QFont()
        f.setPointSizeF(10)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(0, r.bottom() + 8, self.width(), 18), Qt.AlignCenter, "Install Digonto Studio")
        self.paint_doc(p, self.readme_rect(), self.hover_doc)

    def mouseMoveEvent(self, e):
        h = self.icon_rect().adjusted(-10, -10, 10, 10).contains(e.position())
        d = self.readme_rect().contains(e.position())
        if (h, d) != (self.hover, self.hover_doc):
            self.hover, self.hover_doc = h, d
            self.setCursor(Qt.PointingHandCursor if (h or d) else Qt.ArrowCursor)
            self.update()

    def mouseDoubleClickEvent(self, e):
        if self.icon_rect().adjusted(-10, -10, 10, 10).contains(e.position()):
            self.open_installer.emit()
        elif self.readme_rect().contains(e.position()):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(asset("READ ME FIRST.txt")))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.open_installer.emit()
        super().keyPressEvent(e)


def render_background(path, scale=2):
    """save the 600 x 400 background (with the text) as a picture, for the Mac .dmg window"""
    from PySide6.QtGui import QImage
    img = QImage(WELCOME_W * scale, WELCOME_H * scale, QImage.Format_ARGB32)
    p = QPainter(img)
    p.scale(scale, scale)
    paint_welcome(p, WELCOME_W, WELCOME_H, 1.0)
    p.end()
    img.save(path)


# --------------------------------------------------------------------------------------- a demo backend (test) --
class DemoBackend:
    NAMES = [("digonto-studio", "Digonto Studio", 62, True), ("digonto-images", "Digonto Images", 38, False),
             ("digonto-vector", "Digonto Vector", 34, False), ("digonto-pdf", "Digonto PDF", 41, False),
             ("digonto-write", "Digonto Write", 29, False), ("digonto-sheets", "Digonto Sheets", 27, False),
             ("digonto-audio", "Digonto Audio", 31, False), ("digonto-player", "Digonto Player", 26, False),
             ("digonto-logo", "Digonto Logo", 33, False), ("digonto-qr", "Digonto QR", 22, False),
             ("digonto-tools", "Digonto Tools", 236, False), ("digonto-ssh", "Digonto SSH", 30, False),
             ("digonto-dtfrip", "Digonto DTFRIP", 44, False), ("digonto-sublimation", "Digonto Sublimation", 40, False)]

    def __init__(self, installed=()):
        self.installed = set(installed)

    def apps(self):
        out = []
        for slug, name, mb, req in self.NAMES:
            inst = slug in self.installed
            out.append({"slug": slug, "name": name, "size_mb": mb, "required": req,
                        "icon": asset("family", f"{slug}-128.png"), "installed": inst, "outdated": False,
                        "state": "Installed · 2.8.8" if inst else ("Always installed" if req else "Not installed")})
        return out

    def default_folder(self):
        return "/Applications" if sys.platform == "darwin" else (
            r"C:\Program Files\Digonto" if os.name == "nt" else os.path.expanduser("~/.local/share/digonto"))

    def can_change_folder(self):
        return sys.platform != "darwin"

    def normalise_folder(self, d):
        return d

    def run(self, action, apps, folder, progress, cancel):
        import time
        n = 60
        for i in range(n):
            if cancel.is_set():
                return False, "The installation was stopped. Nothing was changed."
            time.sleep(0.03)
            progress((i + 1) / n)
        slugs = {a["slug"] for a in apps}
        if action == "uninstall":
            self.installed -= slugs
            return True, "The selected programs were removed."
        self.installed |= slugs
        return True, "Digonto is installed. Open Digonto Studio from your programs."


def main(backend=None, welcome=False):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)
    win = InstallerWindow(backend or DemoBackend())
    win.destroyed.connect(app.quit)
    state = {}

    def show_installer():
        if "welcome" in state:
            state["welcome"].hide()
        win.show()
        win.raise_()
        win.activateWindow()
        win.start()

    def installer_closed():
        app.quit()

    win.closed = installer_closed
    if welcome:
        w = WelcomeWindow()
        state["welcome"] = w
        w.open_installer.connect(show_installer)
        w.closeEvent = lambda e: app.quit()
        w.show()
    else:
        show_installer()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
