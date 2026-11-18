"""The real work behind the Digonto Studio installer window: copy the programs, give every program its own icon,
file types and uninstall entry, and remove them again.  Works on macOS, Windows and Linux.

The installer runs from the downloaded package (the Mac .dmg, a temporary folder on Windows, /opt on Linux), which
is a complete Digonto Studio with every program in it.  Installing = copying that package to the install folder,
leaving out the programs that were not ticked.
"""
import json
import os
import shutil
import subprocess
import sys
import time

MAC, WIN = sys.platform == "darwin", os.name == "nt"


def apple_chip():
    """True on M1/M2/M3/M4 Macs - also when this program itself runs through Rosetta"""
    if not MAC:
        return False
    try:
        r = subprocess.run(["sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "1"
    except Exception:                                    # noqa: BLE001
        return False


def ai_dir_of(bundle):
    for d in (os.path.join(bundle, "Contents", "Resources", "ai"), os.path.join(bundle, "_internal", "ai")):
        if os.path.isdir(d):
            return d
    return None


def ai_skip(bundle, keep):
    """folders of the offline AI that this computer does not need: all of it without Digonto Tools,
    otherwise the helpers for other chips"""
    ai = ai_dir_of(bundle)
    if not ai:
        return set()
    if "digonto-tools" not in keep:
        return {ai}
    if MAC:
        mine = "macos-arm64" if apple_chip() and os.path.isdir(os.path.join(ai, "macos-arm64")) else "macos-x86_64"
        return {os.path.join(ai, d) for d in os.listdir(ai) if d.startswith("macos-") and d != mine}
    return set()
STUDIO = "digonto-studio"
STUDIO_NAME = "Digonto Studio"
PUBLISHER, HOMEPAGE = "Digonto", "https://digonto.dev"


# ------------------------------------------------------------------------------------------------- places --
def user_data():
    if WIN:
        return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Digonto")
    if MAC:
        return os.path.expanduser("~/Library/Application Support/Digonto")
    return os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "digonto")


def record_path():
    return os.path.join(user_data(), "install.json")


def read_record():
    try:
        with open(record_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_record(rec):
    os.makedirs(user_data(), exist_ok=True)
    tmp = record_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    os.replace(tmp, record_path())


def running_bundle():
    """the package the installer runs from: Mac  X.app,  Windows/Linux  the folder with the program file"""
    exe = os.path.abspath(sys.executable)
    if MAC:
        return os.path.dirname(os.path.dirname(os.path.dirname(exe)))
    return os.path.dirname(exe)


def apps_dir_of(bundle):
    if MAC:
        return os.path.join(bundle, "Contents", "Resources", "apps")
    return os.path.join(bundle, "_internal", "apps")


def exe_name():
    """the program file inside a bundle"""
    if MAC:
        return STUDIO_NAME
    return STUDIO + (".exe" if WIN else "")


def studio_target(folder):
    """where Digonto Studio itself goes inside the chosen folder"""
    if MAC:
        return os.path.join(folder, STUDIO_NAME + ".app")
    return folder


def folder_size_mb(path):
    total = 0
    for dp, _dirs, files in os.walk(path):
        for fn in files:
            fp = os.path.join(dp, fn)
            if not os.path.islink(fp):
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    return total / 1048576


def load_conf(apps_root, slug):
    try:
        with open(os.path.join(apps_root, slug, "digonto-app.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def quiet(cmd, **kw):
    kw.setdefault("stdout", subprocess.DEVNULL)
    kw.setdefault("stderr", subprocess.DEVNULL)
    if WIN:
        kw.setdefault("creationflags", 0x08000000)          # no console window
    try:
        return subprocess.run(cmd, check=False, **kw).returncode
    except OSError:
        return -1


# ------------------------------------------------------------------------------------------------ backend --
class Backend:
    def __init__(self, source=None):
        self.source = source or running_bundle()
        self.src_apps = apps_dir_of(self.source)
        self.rec = read_record()
        self.slugs = sorted((d for d in os.listdir(self.src_apps) if load_conf(self.src_apps, d)),
                            key=lambda s: (s != STUDIO, load_conf(self.src_apps, s)["name"].lower()))
        self.confs = {s: load_conf(self.src_apps, s) for s in self.slugs}
        sizes = {s: folder_size_mb(os.path.join(self.src_apps, s)) for s in self.slugs}
        shared = max(0.0, folder_size_mb(self.source) - sum(sizes.values()))
        sizes[STUDIO] = sizes.get(STUDIO, 0) + shared              # the shared runtime belongs to Studio
        self.sizes = sizes

    # ---- what is installed where
    def folder(self):
        f = self.rec.get("folder")
        if f and os.path.isdir(studio_target(f)):
            return f
        if MAC:
            return "/Applications"
        if WIN:
            return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", "Digonto")
        if self.source.startswith("/opt/"):                       # the .deb already put it in place
            return self.source
        return os.path.join(os.path.expanduser("~/.local/share"), "digonto", "studio")

    def installed_apps_root(self, folder=None):
        return apps_dir_of(studio_target(folder or self.folder()))

    def installed(self, folder=None):
        root = self.installed_apps_root(folder)
        out = {}
        in_place = os.path.realpath(studio_target(folder or self.folder())) == os.path.realpath(self.source)
        if in_place and not self.rec:            # Linux: the .deb put the files here, nothing is set up yet
            return out
        if not os.path.isfile(os.path.join(studio_target(folder or self.folder()),
                                           *(["Contents", "MacOS"] if MAC else []), exe_name())):
            return out
        for s in self.slugs:
            c = load_conf(root, s)
            if c and (os.path.isfile(os.path.join(root, s, c.get("entry", ""))) or s == STUDIO):
                if s == STUDIO or s in self.rec.get("apps", [s]) or not self.rec:
                    out[s] = c.get("version", "")
        return out

    # ---- for the window
    def apps(self):
        inst = self.installed()
        any_installed = bool(inst)
        rows = []
        for s in self.slugs:
            c = self.confs[s]
            have = s in inst
            new_v = c.get("version", "")
            outdated = have and inst[s] != new_v
            if have:
                state = f"Installed · {inst[s]}" + (f"  →  {new_v}" if outdated else "")
            else:
                state = "Always installed" if s == STUDIO else "Not installed"
            icon = os.path.join(self.src_apps, s, "assets", f"{s}-128.png")
            if not os.path.isfile(icon):
                icon = os.path.join(self.src_apps, STUDIO, "assets", "family", f"{s}-128.png")
            rows.append({"slug": s, "name": c["name"], "size_mb": self.sizes[s], "required": s == STUDIO,
                         "icon": icon, "installed": have, "outdated": outdated, "state": state,
                         "checked": have or not any_installed})
        return rows

    def default_folder(self):
        return self.folder()

    def can_change_folder(self):
        return not MAC

    def normalise_folder(self, d):
        d = os.path.abspath(d)
        if os.path.basename(d).lower() != "digonto" and not os.path.isfile(os.path.join(d, exe_name())):
            d = os.path.join(d, "Digonto")                      # D:\  ->  D:\Digonto
        return d

    # ---- the work
    def run(self, action, apps, folder, progress, cancel):
        chosen = {a["slug"] for a in apps}
        inst = set(self.installed(folder))
        if action == "uninstall":
            return self.uninstall(chosen, folder, progress)
        keep = (inst | chosen | {STUDIO}) if action == "install" else (inst | {STUDIO})
        ok, msg = self.copy_bundle(folder, keep, progress, cancel)
        if not ok:
            return ok, msg
        self.integrate(folder, keep, removed=set(self.slugs) - keep)
        progress(1.0)
        first = not inst
        if first:
            pin_studio(folder)
        self.rec = {"folder": folder, "apps": sorted(keep), "version": self.confs[STUDIO].get("version", ""),
                    "when": time.strftime("%Y-%m-%d %H:%M")}
        write_record(self.rec)
        word = {"install": "installed", "update": "updated", "repair": "repaired"}[action]
        return True, f"Digonto is {word}. Open Digonto Studio from your programs."

    def copy_bundle(self, folder, keep, progress, cancel):
        target = studio_target(folder)
        same = os.path.realpath(target) == os.path.realpath(self.source)
        if same:                                                  # Linux: the .deb already put everything here
            progress(0.85)
            return True, ""
        parent = os.path.dirname(target.rstrip(os.sep)) or target
        os.makedirs(parent, exist_ok=True)
        tmp = target.rstrip(os.sep) + ".digonto-new"
        shutil.rmtree(tmp, ignore_errors=True)
        skip = {os.path.join(self.src_apps, s) for s in self.slugs if s not in keep}
        skip |= ai_skip(self.source, keep)
        files = []
        total = 0
        for dp, dirs, fns in os.walk(self.source):
            if any(dp == k or dp.startswith(k + os.sep) for k in skip):
                dirs[:] = []
                continue
            for fn in fns:
                fp = os.path.join(dp, fn)
                files.append(fp)
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            for d in list(dirs):
                if os.path.islink(os.path.join(dp, d)):
                    files.append(os.path.join(dp, d))
                    dirs.remove(d)
        done = 0
        try:
            for i, fp in enumerate(files):
                if cancel.is_set():
                    raise InterruptedError
                rel = os.path.relpath(fp, self.source)
                out = os.path.join(tmp, rel)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                if os.path.islink(fp):
                    os.symlink(os.readlink(fp), out)
                else:
                    shutil.copy2(fp, out)
                    done += os.path.getsize(fp)
                if i % 20 == 0:
                    progress(0.8 * done / max(total, 1))
            if MAC:
                quiet(["xattr", "-cr", tmp])
                quiet(["codesign", "--force", "--deep", "--sign", "-", tmp])
            if cancel.is_set():
                raise InterruptedError
        except InterruptedError:
            shutil.rmtree(tmp, ignore_errors=True)
            return False, "The installation was stopped. Nothing was changed."
        stop_running(target)
        old = target.rstrip(os.sep) + ".digonto-old"
        shutil.rmtree(old, ignore_errors=True)
        if os.path.exists(target):
            os.replace(target, old)
        os.replace(tmp, target)
        shutil.rmtree(old, ignore_errors=True)
        progress(0.85)
        return True, ""

    def integrate(self, folder, keep, removed):
        target = studio_target(folder)
        root = apps_dir_of(target)
        for s in sorted(keep):
            c = load_conf(root, s)
            if c:
                add_program(target, folder, s, c)
        for s in sorted(removed):
            c = self.confs.get(s) or load_conf(root, s)
            if c:
                remove_program(target, folder, s, c)
        refresh_desktop()

    def uninstall(self, chosen, folder, progress):
        target = studio_target(folder)
        root = apps_dir_of(target)
        everything = STUDIO in chosen
        slugs = list(self.installed(folder)) if everything else sorted(chosen)
        for i, s in enumerate(slugs):
            c = load_conf(root, s) or self.confs.get(s)
            if c:
                remove_program(target, folder, s, c)
            in_place = not MAC and not WIN and os.path.realpath(target).startswith("/opt/")
            if not everything and not in_place:      # Linux /opt: keep the files, so it can be added again
                shutil.rmtree(os.path.join(root, s), ignore_errors=True)
            progress(0.8 * (i + 1) / max(len(slugs), 1))
        if everything:
            stop_running(target)
            unpin_studio(folder)
            if not MAC and not WIN:                  # show "Install Digonto" again
                try:
                    os.remove(os.path.expanduser(f"~/.local/share/applications/{SETUP_DESKTOP}"))
                except OSError:
                    pass
            if not (not MAC and not WIN and os.path.realpath(target).startswith("/opt/")):
                remove_tree_later(target)            # (Linux /opt belongs to the package: App Center removes it)
            try:
                os.remove(record_path())
            except OSError:
                pass
            self.rec = {}
        else:
            if MAC:
                quiet(["codesign", "--force", "--deep", "--sign", "-", target])
            self.rec["apps"] = sorted(set(self.rec.get("apps", [])) - chosen)
            self.rec.setdefault("folder", folder)
            write_record(self.rec)
        refresh_desktop()
        progress(1.0)
        if everything:
            if not MAC and not WIN and os.path.realpath(target).startswith("/opt/"):
                return True, ("Digonto's icons are removed. To remove its program files too, remove "
                              "Digonto Studio in the App Center. Your own files were not touched.")
            return True, "Digonto is removed from this computer. Your own files were not touched."
        names = ", ".join(self.confs[s]["name"] for s in slugs if s in self.confs)
        return True, f"Removed: {names}."


def uninstall_one(slug):
    """used by Digonto Studio's Uninstall button and the system's uninstall entry: remove one installed program"""
    rec = read_record()
    folder = rec.get("folder")
    if not folder:
        b = running_bundle()
        folder = os.path.dirname(b) if MAC else b
    b = Backend(source=studio_target(folder))
    ok, msg = b.uninstall({slug}, folder, lambda *_: None)
    return ok, msg


# ---------------------------------------------------------------------------------------- per system --
def program_file(target, slug):
    """what starts one program"""
    if MAC:
        return os.path.join(target, "Contents", "MacOS", exe_name())
    if WIN:
        return os.path.join(target, (slug if slug != STUDIO else STUDIO) + ".exe")
    return os.path.join(target, STUDIO)


def add_program(target, folder, slug, c):
    if MAC:
        _mac_add(target, folder, slug, c)
    elif WIN:
        _win_add(target, slug, c)
    else:
        _linux_add(target, slug, c)


def remove_program(target, folder, slug, c):
    if MAC:
        _mac_remove(folder, slug, c)
    elif WIN:
        _win_remove(target, slug, c)
    else:
        _linux_remove(slug, c)


def refresh_desktop():
    if MAC or WIN:
        if WIN:
            try:
                import ctypes
                ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
            except Exception:                                     # noqa: BLE001
                pass
        return
    apps = os.path.expanduser("~/.local/share/applications")
    quiet(["update-desktop-database", "-q", apps])
    quiet(["update-mime-database", os.path.expanduser("~/.local/share/mime")])
    quiet(["gtk-update-icon-cache", "-q", "-t", "-f", os.path.expanduser("~/.local/share/icons/hicolor")])


# ---- macOS: every program is its own small .app in Applications that uses Digonto Studio's runtime
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/"
              "Support/lsregister")


def _mac_app(folder, c):
    return os.path.join(folder, c["name"] + ".app")


def _mac_add(target, folder, slug, c):
    import plistlib
    if slug == STUDIO:
        quiet([LSREGISTER, "-f", target])
        return
    app = _mac_app(folder, c)
    shutil.rmtree(app, ignore_errors=True)
    contents = os.path.join(app, "Contents")
    os.makedirs(os.path.join(contents, "MacOS"))
    os.makedirs(os.path.join(contents, "Resources"))
    # the program file is a copy of Studio's own starter, named after the program: the starter knows by its
    # name which program to open, and macOS shows this program's own icon and name in the Dock
    shutil.copy2(os.path.join(target, "Contents", "MacOS", exe_name()), os.path.join(contents, "MacOS", c["name"]))
    os.symlink(os.path.join(target, "Contents", "Frameworks"), os.path.join(contents, "Frameworks"))
    icns = os.path.join(apps_dir_of(target), slug, "assets", f"{slug}.icns")
    if os.path.isfile(icns):
        shutil.copy2(icns, os.path.join(contents, "Resources", f"{slug}.icns"))
    exts = [e.lstrip(".") for e in c.get("extensions", [])]
    pl = {"CFBundleName": c["name"], "CFBundleDisplayName": c["name"], "CFBundleExecutable": c["name"],
          "CFBundleIdentifier": "dev.digonto." + slug.replace("digonto-", ""), "CFBundlePackageType": "APPL",
          "CFBundleIconFile": f"{slug}.icns", "CFBundleShortVersionString": c.get("version", "1.0"),
          "CFBundleVersion": c.get("version", "1.0"), "LSMinimumSystemVersion": str(c.get("macos_min", 11)),
          "NSHighResolutionCapable": True, "NSHumanReadableCopyright": "Digonto - digonto.dev - AGPL-3.0"}
    if exts:
        pl["CFBundleDocumentTypes"] = [{"CFBundleTypeName": c["name"] + " file", "CFBundleTypeRole": "Editor",
                                        "CFBundleTypeExtensions": exts, "LSHandlerRank": "Default",
                                        "LSItemContentTypes": c.get("uti", [])}]
        if c.get("uti"):
            pl["UTExportedTypeDeclarations"] = [
                {"UTTypeIdentifier": u, "UTTypeDescription": c["name"] + " file", "UTTypeConformsTo": ["public.data"],
                 "UTTypeTagSpecification": {"public.filename-extension": exts}} for u in c["uti"]]
    with open(os.path.join(contents, "Info.plist"), "wb") as f:
        plistlib.dump(pl, f)
    quiet(["codesign", "--force", "--sign", "-", app])
    quiet([LSREGISTER, "-f", app])


def _mac_remove(folder, slug, c):
    if slug == STUDIO:
        return
    app = _mac_app(folder, c)
    if os.path.isdir(app):
        quiet([LSREGISTER, "-u", app])
        shutil.rmtree(app, ignore_errors=True)


def _dock_has(path):
    try:
        out = subprocess.run(["defaults", "read", "com.apple.dock", "persistent-apps"], capture_output=True,
                             text=True, check=False).stdout
    except OSError:
        return True
    return path.rstrip("/") in out


# ---- Windows: a copy of the starter per program, Start menu shortcuts, file types and uninstall entries
def _ps(script):
    return quiet(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script])


def _start_menu():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Digonto")


def _shortcut(lnk, exe, icon, workdir):
    q = lambda s: s.replace("'", "''")                       # noqa: E731
    _ps(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');$s.TargetPath='{q(exe)}';"
        f"$s.WorkingDirectory='{q(workdir)}';$s.IconLocation='{q(icon)},0';$s.Save()")


def _win_add(target, slug, c):
    import winreg
    exe = program_file(target, slug)
    if slug != STUDIO:
        shutil.copy2(os.path.join(target, STUDIO + ".exe"), exe)
    ico = os.path.join(apps_dir_of(target), slug, "assets", f"{slug}.ico")
    if not os.path.isfile(ico):
        ico = exe
    os.makedirs(_start_menu(), exist_ok=True)
    _shortcut(os.path.join(_start_menu(), c["name"] + ".lnk"), exe, ico, target)
    if slug == STUDIO:
        desk = os.path.join(os.path.expanduser("~"), "Desktop", c["name"] + ".lnk")
        _shortcut(desk, exe, ico, target)
    for e in c.get("extensions", []):
        prog = f"Digonto.{slug}{e}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{e}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, prog)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, c["name"] + " file")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog}\DefaultIcon") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, ico)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog}\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{exe}" "%1"')
    key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\Digonto-{slug}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        for name, val in (("DisplayName", c["name"]), ("DisplayVersion", c.get("version", "")),
                          ("Publisher", PUBLISHER), ("URLInfoAbout", HOMEPAGE), ("DisplayIcon", ico),
                          ("InstallLocation", target),
                          ("UninstallString", f'"{os.path.join(target, STUDIO + ".exe")}" --uninstall {slug}')):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        try:
            kb = int(folder_size_mb(os.path.join(apps_dir_of(target), slug)) * 1024)
            winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, max(kb, 1))
        except OSError:
            pass


def _win_del_tree(root, path):
    import winreg
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _win_del_tree(root, path + "\\" + sub)
        winreg.DeleteKey(root, path)
    except OSError:
        pass


def _win_remove(target, slug, c):
    import winreg
    for lnk in (os.path.join(_start_menu(), c["name"] + ".lnk"),
                os.path.join(os.path.expanduser("~"), "Desktop", c["name"] + ".lnk")):
        try:
            os.remove(lnk)
        except OSError:
            pass
    if slug != STUDIO:
        try:
            os.remove(program_file(target, slug))
        except OSError:
            pass
    for e in c.get("extensions", []):
        prog = f"Digonto.{slug}{e}"
        _win_del_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog}")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{e}", 0, winreg.KEY_ALL_ACCESS) as k:
                if winreg.QueryValueEx(k, "")[0] == prog:
                    winreg.DeleteValue(k, "")
        except OSError:
            pass
    _win_del_tree(winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\Digonto-{slug}")


# ---- Linux: a menu entry, icons and file types for every program, in the user's own folders
def _linux_add(target, slug, c):
    apps = os.path.expanduser("~/.local/share/applications")
    os.makedirs(apps, exist_ok=True)
    exe = os.path.join(target, STUDIO)
    arg = "" if slug == STUDIO else f" --app {slug}"
    mt = list(c.get("mime") or [])
    with open(os.path.join(apps, f"{slug}.desktop"), "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\n"
                f"Name={c['name']}\nComment={c.get('comment', '')}\n"
                f'Exec="{exe}"{arg} %F\nIcon={slug}\nTerminal=false\n'
                f"Categories={c.get('categories', 'Utility;')}\nKeywords={c.get('keywords', '')}\n"
                f"StartupWMClass={c.get('wm_class', slug)}\n"
                f"MimeType={';'.join(mt) + (';' if mt else '')}\n")
    src = os.path.join(apps_dir_of(target), slug, "assets")
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        p = os.path.join(src, f"{slug}-{size}.png")
        if os.path.isfile(p):
            d = os.path.expanduser(f"~/.local/share/icons/hicolor/{size}x{size}/apps")
            os.makedirs(d, exist_ok=True)
            shutil.copy2(p, os.path.join(d, f"{slug}.png"))
    own = [m for m in mt if m.startswith("application/x-digonto")]
    if own and c.get("extensions"):
        d = os.path.expanduser("~/.local/share/mime/packages")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{slug}.xml"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0"?>\n<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">\n')
            for m in own:
                globs = "".join(f'<glob pattern="*{x}"/>' for x in c["extensions"])
                f.write(f'  <mime-type type="{m}"><comment>{c["name"]} file</comment>{globs}</mime-type>\n')
            f.write("</mime-info>\n")
    if slug == STUDIO:                          # the "Install Digonto" icon is not needed any more
        _linux_hide_setup()


def _linux_remove(slug, c):
    for p in (os.path.expanduser(f"~/.local/share/applications/{slug}.desktop"),
              os.path.expanduser(f"~/.local/share/mime/packages/{slug}.xml")):
        try:
            os.remove(p)
        except OSError:
            pass
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        try:
            os.remove(os.path.expanduser(f"~/.local/share/icons/hicolor/{size}x{size}/apps/{slug}.png"))
        except OSError:
            pass


SETUP_DESKTOP = "digonto-studio-setup.desktop"


def _linux_favorites():
    try:
        out = subprocess.run(["gsettings", "get", "org.gnome.shell", "favorite-apps"], capture_output=True,
                             text=True, check=False).stdout.strip()
        import ast
        return ast.literal_eval(out.replace("@as ", "")) if out.startswith(("[", "@as")) else None
    except (OSError, ValueError, SyntaxError):
        return None


def _linux_set_favorites(favs):
    quiet(["gsettings", "set", "org.gnome.shell", "favorite-apps", str(list(favs))])


def _linux_hide_setup():
    apps = os.path.expanduser("~/.local/share/applications")
    os.makedirs(apps, exist_ok=True)
    with open(os.path.join(apps, SETUP_DESKTOP), "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\nName=Install Digonto\nNoDisplay=true\nExec=true\n")
    favs = _linux_favorites()
    if favs and SETUP_DESKTOP in favs:
        _linux_set_favorites([x for x in favs if x != SETUP_DESKTOP])


def pin_studio(folder):
    """keep Digonto Studio in the Dock (macOS) or the dock's favourites (Ubuntu); Windows does not allow it"""
    if MAC:
        path = studio_target(folder)
        if _dock_has(path):
            return
        tile = ("<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key>"
                f"<string>file://{path}/</string><key>_CFURLStringType</key><integer>15</integer>"
                "</dict></dict></dict>")
        quiet(["defaults", "write", "com.apple.dock", "persistent-apps", "-array-add", tile])
        quiet(["killall", "Dock"])
    elif not WIN:
        favs = _linux_favorites()
        if favs is not None and f"{STUDIO}.desktop" not in favs:
            _linux_set_favorites([x for x in favs if x != SETUP_DESKTOP] + [f"{STUDIO}.desktop"])


def unpin_studio(folder):
    if MAC:
        return                                   # macOS removes Dock tiles of deleted programs by itself
    if not WIN:
        favs = _linux_favorites()
        if favs and f"{STUDIO}.desktop" in favs:
            _linux_set_favorites([x for x in favs if x != f"{STUDIO}.desktop"])


def stop_running(target):
    """close Digonto programs that run from the folder that is being replaced (not this installer)"""
    me = os.getpid()
    if WIN:
        tgt = target.replace("'", "''")
        _ps(f"Get-Process | Where-Object {{ $_.Path -like '{tgt}\\*' -and $_.Id -ne {me} }} | Stop-Process -Force")
    else:
        try:
            out = subprocess.run(["pgrep", "-f", target], capture_output=True, text=True, check=False).stdout.split()
        except OSError:
            out = []
        for pid in out:
            if pid.isdigit() and int(pid) != me:
                try:
                    os.kill(int(pid), 15)
                except OSError:
                    pass
    time.sleep(0.5)


def remove_tree_later(path):
    """remove a folder; on Windows a running program file can't be deleted, so a helper finishes it after exit"""
    shutil.rmtree(path, ignore_errors=True)
    if WIN and os.path.exists(path):
        subprocess.Popen(["cmd", "/c", f'ping -n 4 127.0.0.1 >nul & rmdir /s /q "{path}"'],
                         creationflags=0x08000000, close_fds=True)
