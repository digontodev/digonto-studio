"""Digonto standalone launcher.

One frozen Python + Qt runtime that can start any Digonto program shipped inside it:
    digonto --app digonto-qr [files...]     start one program
    digonto some_script.py [args...]        run a helper script of a program (DTFRIP keep-alive)
    digonto [files...]                      start the default program of this package
The programs are kept as normal source folders in  <bundle>/apps/<slug>/  so they find their own files.
"""
import json
import os
import runpy
import sys

if getattr(sys, "frozen", False):
    BASE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.join(BASE, "apps")
os.environ["DIGONTO_STANDALONE"] = "1"
os.environ["DIGONTO_LAUNCHER"] = sys.executable


def user_base():
    """shared data of the Digonto programs (recent files ...): the program folder itself is read-only"""
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Digonto")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Digonto")
    return os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "digonto")


os.environ.setdefault("DIGONTO_BASE", user_base())


def default_app():
    try:
        with open(os.path.join(BASE, "default-app.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        names = sorted(os.listdir(APPS)) if os.path.isdir(APPS) else []
        return names[0] if names else ""


def run_app(slug, args):
    d = os.path.join(APPS, slug)
    with open(os.path.join(d, "digonto-app.json"), encoding="utf-8") as f:
        conf = json.load(f)
    entry = os.path.join(d, conf["entry"])
    sys.path.insert(0, d)
    sys.argv = [entry] + list(args)
    code = 0
    try:
        runpy.run_path(entry, run_name="__main__")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    if getattr(sys, "frozen", False):
        # the window is closed: end the process now, so no waiting background task keeps it running
        # ("Running in Background" in the Dock after Quit)
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:                          # noqa: BLE001
            pass
        os._exit(code)
    return code


def app_by_name():
    """a program file named after a program (Digonto Images, digonto-images.exe) opens that program"""
    exe = os.path.basename(sys.executable)
    if exe.lower().endswith(".exe"):
        exe = exe[:-4]
    if not os.path.isdir(APPS):
        return None
    for slug in os.listdir(APPS):
        try:
            with open(os.path.join(APPS, slug, "digonto-app.json"), encoding="utf-8") as f:
                name = json.load(f).get("name", "")
        except (OSError, ValueError):
            continue
        if exe.lower() in (slug.lower(), name.lower()):
            return slug
    return None


def setup_mode():
    """the Mac package is called "Install Digonto Studio.app": opened from there, it is the installer"""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return False
    bundle = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))))
    return os.path.basename(bundle).startswith("Install ")


def run_installer(welcome=False):
    sys.path.insert(0, os.path.join(BASE, "installer"))
    import digonto_installer
    import backend
    return digonto_installer.main(backend.Backend(), welcome=welcome)


def run_uninstall(slug):
    """remove one program, after asking (Studio's Uninstall button, the system's uninstall entry)"""
    sys.path.insert(0, os.path.join(BASE, "installer"))
    import backend
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        with open(os.path.join(APPS, slug, "digonto-app.json"), encoding="utf-8") as f:
            name = json.load(f)["name"]
    except (OSError, ValueError, KeyError):
        name = slug
    what = "Digonto Studio and every Digonto program" if slug == "digonto-studio" else name
    if "--yes" not in sys.argv and QMessageBox.question(
            None, "Uninstall", f"Remove {what} from this computer?\n\nYour own files are not touched.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
        return 1
    ok, msg = backend.uninstall_one(slug)
    (QMessageBox.information if ok else QMessageBox.warning)(None, "Uninstall", msg)
    del app
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    if args and args[0] == "--app" and len(args) >= 2:
        return run_app(args[1], args[2:])
    if args and args[0].endswith(".py") and os.path.isfile(args[0]):
        script = os.path.abspath(args[0])
        sys.path.insert(0, os.path.dirname(script))
        sys.argv = [script] + args[1:]
        return runpy.run_path(script, run_name="__main__")
    if args and args[0] in ("--setup", "--welcome"):
        return run_installer(welcome=args[0] == "--welcome")
    if args and args[0] == "--uninstall" and len(args) >= 2:
        return run_uninstall(args[1])
    if setup_mode():
        return run_installer()
    named = app_by_name()
    if named:
        return run_app(named, args)
    if args and args[0] in ("-m", "-c"):            # not a Python: a frozen program cannot run pip or code
        sys.stderr.write("Digonto standalone edition: running Python commands is not possible here.\n")
        sys.exit(2)
    if args and args[0] == "--list":
        print("\n".join(sorted(os.listdir(APPS))))
        return
    return run_app(default_app(), args)


if os.environ.get("DIGONTO_NEVER_SET_THIS"):      # never runs: tells PyInstaller which libraries the programs use
    import _digonto_deps  # noqa: F401

if __name__ == "__main__":
    rv = main()
    sys.exit(rv if isinstance(rv, int) else 0)
