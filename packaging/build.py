"""Build standalone Digonto packages (no Python, no internet needed by the user).

    python build.py --root .. --apps digonto-qr                  one program  -> Digonto QR (.deb / .dmg / .exe)
    python build.py --root .. --apps all --package digonto-studio  Studio with every program in it

Run it on the system you build for (GitHub Actions does Linux, macOS and Windows).
The build Python must already have the programs' requirements installed (see --print-requirements).
"""
import argparse
import ast
import glob
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import textwrap
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = "digonto-studio"
SYS = platform.system()
PUBLISHER = "Digonto"
HOMEPAGE = "https://digonto.dev"
# apt packages every Qt program needs on Debian / Ubuntu (the libraries themselves are inside the package)
DEB_BASE = ["libxcb-cursor0", "libxkbcommon-x11-0", "libxcb-icccm4", "libxcb-image0", "libxcb-keysyms1",
            "libxcb-randr0", "libxcb-render-util0", "libxcb-shape0", "libxcb-xinerama0", "libegl1", "libgl1",
            "libfontconfig1", "libdbus-1-3"]


def load_apps(root):
    apps = {}
    for d in sorted(os.listdir(root)):
        f = os.path.join(root, d, "digonto-app.json")
        if os.path.isfile(f):
            with open(f, encoding="utf-8") as fh:
                c = json.load(fh)
            c["_src"] = os.path.join(root, d)
            apps[c["slug"]] = c
    return apps


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


# ---------------------------------------------------------------- stage the programs
def stage(apps, slugs, dst):
    shutil.rmtree(dst, ignore_errors=True)
    for s in slugs:
        c = apps[s]
        out = os.path.join(dst, s)
        os.makedirs(out)
        for item in c["files"] + ["digonto-app.json"]:
            src = os.path.join(c["_src"], item)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(out, item), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            elif os.path.isfile(src):
                shutil.copy2(src, os.path.join(out, item))
            else:
                raise SystemExit(f"{s}: missing file {item}")



def native_libs(staged):
    """dtfrip/sublimation ship a small C library for every system. Keep only the one for this computer;
    on macOS compile it fresh with room in its header, because PyInstaller must rewrite its install name."""
    import platform
    sysn = {"Windows": "windows", "Darwin": "macos"}.get(SYS, "linux")
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
    ext = {"windows": ".dll", "macos": ".dylib"}.get(sysn, ".so")
    keep = f"libdtfcore-{sysn}-{arch}{ext}"
    for lib in glob.glob(os.path.join(staged, "*", "*", "lib")):
        if not os.path.isfile(os.path.join(os.path.dirname(lib), "csrc", "dtfcore.c")):
            continue
        for f in os.listdir(lib):
            if f.startswith("libdtfcore-") and f != keep:
                os.remove(os.path.join(lib, f))
        if sysn == "macos":
            src = os.path.join(os.path.dirname(lib), "csrc", "dtfcore.c")
            run(["cc", "-O3", "-shared", "-fPIC", "-arch", arch, "-mmacosx-version-min=11.0",
                 "-Wl,-headerpad_max_install_names", "-install_name", "@rpath/" + keep,
                 "-o", os.path.join(lib, keep), src])

def scan_imports(staged):
    """every module the programs import, minus their own modules -> PyInstaller must collect these"""
    local, found = set(), set()
    for slug in os.listdir(staged):
        d = os.path.join(staged, slug)
        for n in os.listdir(d):
            local.add(n[:-3] if n.endswith(".py") else n)
    for dirpath, _dirs, files in os.walk(staged):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            try:
                tree = ast.parse(open(os.path.join(dirpath, fn), encoding="utf-8").read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        found.add(a.name)
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    found.add(node.module)
                    for a in node.names:
                        if a.name != "*":
                            found.add(node.module + "." + a.name)
    out = sorted(m for m in found if m.split(".")[0] not in local and not m.startswith("_"))
    return out


def write_deps(mods, path):
    lines = ["# generated: the libraries the bundled programs use (each import may be missing on some systems)"]
    for m in mods:
        lines.append(f"try:\n    import {m}  # noqa\nexcept Exception:\n    pass")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- freeze
def icon_file(app, ext):
    for cand in (f"{app['slug']}.{ext}", f"icon.{ext}"):
        p = os.path.join(app["_src"], "assets", cand)
        if os.path.isfile(p):
            return p
    return None


def freeze(apps, slugs, pkg, work):
    main = apps[pkg]
    staged = os.path.join(work, "apps")
    stage(apps, slugs, staged)
    native_libs(staged)
    with open(os.path.join(work, "default-app.txt"), "w") as f:
        f.write(pkg)
    write_deps(scan_imports(staged), os.path.join(work, "_digonto_deps.py"))
    shutil.copy2(os.path.join(HERE, "launcher.py"), os.path.join(work, "launcher.py"))
    name = main["name"] if SYS == "Darwin" else main["slug"]
    sep = os.pathsep
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
           "--name", name, "--distpath", os.path.join(work, "dist"), "--workpath", os.path.join(work, "pyi"),
           "--specpath", work, "--paths", work,
           "--add-data", f"{staged}{sep}apps", "--add-data", f"{os.path.join(work, 'default-app.txt')}{sep}.",
           "--hidden-import", "_digonto_deps"]
    if pkg == STUDIO:                       # the Studio package is also its own installer (installer/ folder)
        inst = os.path.join(work, "installer")
        shutil.copytree(os.path.join(HERE, "installer"), inst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        cmd += ["--add-data", f"{inst}{sep}installer"]
        for m in ("plistlib", "ctypes", "ast", "threading", "winreg" if SYS == "Windows" else "json"):
            cmd += ["--hidden-import", m]
    needs_tk = any(apps[s].get("needs_tk") for s in slugs)
    if not needs_tk:
        cmd += ["--exclude-module", "tkinter"]
    ico = icon_file(main, "ico" if SYS == "Windows" else "icns" if SYS == "Darwin" else "png")
    if ico:
        cmd += ["--icon", ico]
    if SYS == "Darwin":
        cmd += ["--osx-bundle-identifier", "dev.digonto." + main["slug"].replace("digonto-", "")]
    cmd.append(os.path.join(work, "launcher.py"))
    run(cmd, cwd=work)
    out = os.path.join(work, "dist", name + (".app" if SYS == "Darwin" else ""))
    if not os.path.exists(out):
        raise SystemExit("PyInstaller made nothing")
    return out


def add_ai(frozen):
    """the offline AI (background removal) next to the programs: Contents/Resources/ai on macOS, _internal/ai
    elsewhere. Built by packaging/ai/build-ai-ci.sh; the folder is given in DIGONTO_AI_DIR."""
    src = os.environ.get("DIGONTO_AI_DIR")
    if not src or not os.path.isdir(src):
        print("no AI folder (DIGONTO_AI_DIR) - building without AI background removal")
        return
    dst = os.path.join(frozen, "Contents", "Resources", "ai") if SYS == "Darwin" else os.path.join(frozen, "_internal", "ai")
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, symlinks=True)
    print("AI added:", dst, sorted(os.listdir(dst)))


# ---------------------------------------------------------------- Linux .deb
def build_deb(apps, slugs, pkg, frozen, outdir):
    main = apps[pkg]
    ver = main["version"]
    root = os.path.join(os.path.dirname(frozen), "debroot")
    shutil.rmtree(root, ignore_errors=True)
    opt = os.path.join(root, "opt", "digonto", pkg)
    shutil.copytree(frozen, opt, symlinks=True)
    exe = f"/opt/digonto/{pkg}/{pkg}"
    os.makedirs(os.path.join(root, "usr", "bin"))
    mimes = []
    for s in slugs:
        a = apps[s]
        launcher = os.path.join(root, "usr", "bin", s)
        arg = "" if s == pkg else f" --app {s}"
        with open(launcher, "w") as f:
            f.write(f'#!/bin/sh\nexec {exe}{arg} "$@"\n')
        os.chmod(launcher, 0o755)
        apps_dir = os.path.join(root, "usr", "share", "applications")
        os.makedirs(apps_dir, exist_ok=True)
        mt = list(a.get("mime") or [])
        mimes += [(m, e) for m in mt for e in a.get("extensions", []) if m.startswith("application/x-digonto")]
        with open(os.path.join(apps_dir, f"{s}.desktop"), "w") as f:
            f.write(textwrap.dedent(f"""\
                [Desktop Entry]
                Type=Application
                Name={a['name']}
                Comment={a.get('comment', '')}
                Exec=/usr/bin/{s} %F
                Icon={s}
                Terminal=false
                Categories={a.get('categories', 'Utility;')}
                Keywords={a.get('keywords', '')}
                StartupWMClass={a.get('wm_class', s)}
                MimeType={';'.join(mt) + (';' if mt else '')}
                """))
        for size in (16, 24, 32, 48, 64, 128, 256, 512):
            src = os.path.join(a["_src"], "assets", f"{s}-{size}.png")
            if not os.path.isfile(src):
                src = os.path.join(a["_src"], "assets", f"{s}.png") if size == 256 else None
            if src and os.path.isfile(src):
                d = os.path.join(root, "usr", "share", "icons", "hicolor", f"{size}x{size}", "apps")
                os.makedirs(d, exist_ok=True)
                shutil.copy2(src, os.path.join(d, f"{s}.png"))
    if mimes:
        d = os.path.join(root, "usr", "share", "mime", "packages")
        os.makedirs(d)
        with open(os.path.join(d, f"{pkg}.xml"), "w") as f:
            f.write('<?xml version="1.0"?>\n<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">\n')
            seen = set()
            for m, e in mimes:
                if m in seen:
                    continue
                seen.add(m)
                globs = "".join(f'<glob pattern="*{x}"/>' for mm, x in mimes if mm == m)
                f.write(f'  <mime-type type="{m}"><comment>{m.split("x-")[-1]} file</comment>{globs}</mime-type>\n')
            f.write("</mime-info>\n")
    deps = list(DEB_BASE)
    for s in slugs:
        deps += [p for p in apps[s].get("apt", []) if p not in deps]
    size_kb = sum(os.path.getsize(os.path.join(dp, fn)) for dp, _d, fs in os.walk(root) for fn in fs
                  if not os.path.islink(os.path.join(dp, fn))) // 1024
    deb = os.path.join(root, "DEBIAN")
    os.makedirs(deb)
    desc = main.get("comment", main["name"])
    with open(os.path.join(deb, "control"), "w") as f:
        f.write(textwrap.dedent(f"""\
            Package: {pkg}
            Version: {ver}
            Section: graphics
            Priority: optional
            Architecture: {'arm64' if platform.machine() in ('aarch64', 'arm64') else 'amd64'}
            Maintainer: Digonto <digontodev@users.noreply.github.com>
            Homepage: {HOMEPAGE}
            Installed-Size: {size_kb}
            Depends: {', '.join(sorted(set(deps)))}
            Description: {main['name']} - {desc}
             Part of the Digonto programs (digonto.dev). Works without internet.
            """))
    for name, body in (("postinst", "update-desktop-database -q /usr/share/applications 2>/dev/null || true\n"
                                    "update-mime-database /usr/share/mime 2>/dev/null || true\n"
                                    "gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true\n"),
                       ("postrm", "update-desktop-database -q /usr/share/applications 2>/dev/null || true\n"
                                  "update-mime-database /usr/share/mime 2>/dev/null || true\n")):
        p = os.path.join(deb, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\nset -e\n" + body)
        os.chmod(p, 0o755)
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"{pkg}_{ver}_{'arm64' if platform.machine() in ('aarch64', 'arm64') else 'amd64'}.deb")
    run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", root, out])
    return out


# ---------------------------------------------------------------- macOS .app + .dmg
def build_dmg(apps, slugs, pkg, frozen, outdir):
    main = apps[pkg]
    plist_path = os.path.join(frozen, "Contents", "Info.plist")
    with open(plist_path, "rb") as f:
        pl = plistlib.load(f)
    pl.update({"CFBundleName": main["name"], "CFBundleDisplayName": main["name"],
               "CFBundleShortVersionString": main["version"], "CFBundleVersion": main["version"],
               "LSMinimumSystemVersion": str(main.get("macos_min", 11)), "NSHighResolutionCapable": True,
               "NSHumanReadableCopyright": "Digonto - digonto.dev - AGPL-3.0"})
    docs, utis = [], []
    for s in slugs if len(slugs) == 1 else [pkg]:
        a = apps[s]
        exts = [e.lstrip(".") for e in a.get("extensions", [])]
        if exts:
            docs.append({"CFBundleTypeName": a["name"] + " file", "CFBundleTypeRole": "Editor",
                         "CFBundleTypeExtensions": exts, "LSHandlerRank": "Default",
                         "LSItemContentTypes": a.get("uti", [])})
            for u in a.get("uti", []):
                utis.append({"UTTypeIdentifier": u, "UTTypeDescription": a["name"] + " file",
                             "UTTypeConformsTo": ["public.data"], "UTTypeTagSpecification": {"public.filename-extension": exts}})
    if docs:
        pl["CFBundleDocumentTypes"] = docs
    if utis:
        pl["UTExportedTypeDeclarations"] = utis
    with open(plist_path, "wb") as f:
        plistlib.dump(pl, f)
    # ad-hoc signature, so Apple silicon Macs start it (users still confirm once: right-click > Open)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", frozen], check=False)
    stage_dir = os.path.join(os.path.dirname(frozen), "dmgroot")
    shutil.rmtree(stage_dir, ignore_errors=True)
    os.makedirs(stage_dir)
    shutil.copytree(frozen, os.path.join(stage_dir, os.path.basename(frozen)), symlinks=True)
    os.symlink("/Applications", os.path.join(stage_dir, "Applications"))
    with open(os.path.join(stage_dir, "READ ME FIRST.txt"), "w") as f:
        f.write(f"Drag {main['name']} into Applications, then open it.\n\n"
                "The first time, macOS says it cannot verify the program (it is not signed by Apple yet):\n"
                "open System Settings > Privacy & Security, scroll down and click Open Anyway,\n"
                "then open the program again. This is needed only once.\n\n"
                "On Macs with an M chip, click Install if macOS asks to install Rosetta.\n")
    os.makedirs(outdir, exist_ok=True)
    arch = "arm64" if platform.machine() == "arm64" else "x86_64"
    out = os.path.join(outdir, f"{main['name'].replace(' ', '-')}-{main['version']}-macOS-{arch}.dmg")
    if os.path.exists(out):
        os.remove(out)
    for attempt in range(5):                      # hdiutil often fails with 'Resource busy' on build machines
        try:
            run(["hdiutil", "create", "-volname", main["name"], "-srcfolder", stage_dir, "-ov", "-format", "UDZO", out]); break
        except subprocess.CalledProcessError:
            if attempt == 4: raise
            time.sleep(10 * (attempt + 1))
    return out


# ---------------------------------------------------------------- Windows .exe (Inno Setup)
def build_exe(apps, slugs, pkg, frozen, outdir):
    main = apps[pkg]
    exe = f"{pkg}.exe"
    iss = os.path.join(os.path.dirname(frozen), f"{pkg}.iss")
    ico = icon_file(main, "ico")
    lines = [
        "[Setup]",
        f"AppId={{{{Digonto-{pkg}}}}}",
        f"AppName={main['name']}",
        f"AppVersion={main['version']}",
        f"AppPublisher={PUBLISHER}",
        f"AppPublisherURL={HOMEPAGE}",
        f"DefaultDirName={{localappdata}}\\Programs\\Digonto\\{main['name']}",
        "DefaultGroupName=Digonto",
        "DisableProgramGroupPage=yes",
        "PrivilegesRequired=lowest",
        "ChangesAssociations=yes",
        "ArchitecturesInstallIn64BitMode=x64compatible",
        "ArchitecturesAllowed=x64compatible",
        f"OutputDir={outdir}",
        f"OutputBaseFilename={main['name'].replace(' ', '-')}-{main['version']}-Windows-Setup",
        "Compression=lzma2/max",
        "SolidCompression=yes",
        "WizardStyle=modern",
        f"UninstallDisplayIcon={{app}}\\{exe}",
        f"LicenseFile={os.path.join(HERE, 'LICENSE.txt')}",
    ]
    if ico:
        lines.append(f"SetupIconFile={ico}")
    lines += ["", "[Tasks]", 'Name: "desktopicon"; Description: "Make shortcuts on the desktop"; GroupDescription: "Shortcuts:"',
              "", "[Files]", f'Source: "{frozen}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs', "",
              "[Icons]"]
    reg = []
    for s in slugs:
        a = apps[s]
        args = "" if s == pkg else f'; Parameters: "--app {s}"'
        icon = f'; IconFilename: "{{app}}\\_internal\\apps\\{s}\\assets\\{s}.ico"' if icon_file(a, "ico") else ""
        lines.append(f'Name: "{{group}}\\{a["name"]}"; Filename: "{{app}}\\{exe}"{args}{icon}')
        lines.append(f'Name: "{{autodesktop}}\\{a["name"]}"; Filename: "{{app}}\\{exe}"{args}{icon}; Tasks: desktopicon')
        inner = f'"{{app}}\\{exe}" ' + ("" if s == pkg else f"--app {s} ") + '"%1"'
        cmdline = inner.replace('"', '""')                 # Inno Setup: quotes inside a value are doubled
        for e in a.get("extensions", []):
            prog = f"Digonto.{s}{e}"
            reg += [f'Root: HKCU; Subkey: "Software\\Classes\\{e}"; ValueType: string; ValueName: ""; ValueData: "{prog}"; Flags: uninsdeletevalue',
                    f'Root: HKCU; Subkey: "Software\\Classes\\{prog}"; ValueType: string; ValueName: ""; ValueData: "{a["name"]} file"; Flags: uninsdeletekey',
                    f'Root: HKCU; Subkey: "Software\\Classes\\{prog}\\shell\\open\\command"; ValueType: string; ValueName: ""; ValueData: "{cmdline}"']
    lines.append(f'Name: "{{group}}\\Uninstall {main["name"]}"; Filename: "{{uninstallexe}}"')
    if reg:
        lines += ["", "[Registry]"] + reg
    lines += ["", "[Run]", f'Filename: "{{app}}\\{exe}"; Description: "Open {main["name"]}"; Flags: nowait postinstall skipifsilent']
    with open(iss, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    os.makedirs(outdir, exist_ok=True)
    run([iscc, iss])
    return os.path.join(outdir, f"{main['name'].replace(' ', '-')}-{main['version']}-Windows-Setup.exe")



# ---------------------------------------------------------------- Digonto Studio: our own installer on every system
INST = os.path.join(HERE, "installer")
README = os.path.join(INST, "assets", "READ ME FIRST.txt")


def _bg_png(path, scale):
    """the horizon background of the first window, drawn by the installer's own code"""
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from PySide6.QtWidgets import QApplication\n"
            "app = QApplication([])\n"
            "import digonto_installer as d\n"
            "d.render_background(%r, scale=%d)\n") % (INST, path, scale)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    run([sys.executable, "-c", code], env=env)


def studio_dmg(apps, slugs, pkg, frozen, outdir):
    """macOS: a disk whose window (600 x 400, no toolbar) shows the horizon background, the
    "Install Digonto Studio" icon and READ ME FIRST.txt; the icon opens our installer window"""
    build_dmg_plist(apps, slugs, pkg, frozen)
    work = os.path.dirname(frozen)
    inst_app = os.path.join(work, "Install Digonto Studio.app")
    shutil.rmtree(inst_app, ignore_errors=True)
    shutil.copytree(frozen, inst_app, symlinks=True)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", inst_app], check=False)
    bg1, bg2, tif = (os.path.join(work, n) for n in ("bg.png", "bg@2x.png", "bg.tiff"))
    _bg_png(bg1, 1)
    _bg_png(bg2, 2)
    run(["tiffutil", "-cathidpicheck", bg1, bg2, "-out", tif])
    settings = os.path.join(work, "dmg_settings.py")
    with open(settings, "w") as f:
        f.write(textwrap.dedent(f"""\
            format = "UDZO"
            files = [{inst_app!r}, {README!r}]
            symlinks = {{}}
            background = {tif!r}
            window_rect = ((200, 140), (600, 400))
            default_view = "icon-view"
            show_toolbar = False
            show_status_bar = False
            show_tab_view = False
            show_pathbar = False
            show_sidebar = False
            show_icon_preview = False
            icon_size = 120
            text_size = 13
            icon_locations = {{"Install Digonto Studio.app": (300, 125), "READ ME FIRST.txt": (530, 262)}}
            """))
    main = apps[pkg]
    os.makedirs(outdir, exist_ok=True)
    arch = "arm64" if platform.machine() == "arm64" else "x86_64"
    out = os.path.join(outdir, f"{main['name'].replace(' ', '-')}-{main['version']}-macOS-{arch}.dmg")
    if os.path.exists(out):
        os.remove(out)
    for attempt in range(5):                      # hdiutil (used by dmgbuild) is often busy on build machines
        try:
            run([sys.executable, "-m", "dmgbuild", "-s", settings, main["name"], out]); break
        except subprocess.CalledProcessError:
            if attempt == 4: raise
            time.sleep(10 * (attempt + 1))
    try:
        small_readme_icon(out, work)
    except Exception as e:                        # noqa: BLE001 - a big README icon is no reason to fail the build
        print("README icon not changed:", e)
    return out


def small_readme_icon(dmg, work):
    """Finder shows a text file as a big page preview; give READ ME FIRST.txt a small plain file icon instead"""
    from PIL import Image, ImageDraw
    png = os.path.join(work, "readme-icon.png")
    im = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x0, y0, w, h, fold = 186, 262, 140, 180, 40                 # a small page at the bottom of the icon, near its name
    d.polygon([(x0, y0), (x0 + w - fold, y0), (x0 + w, y0 + fold), (x0 + w, y0 + h), (x0, y0 + h)],
              fill=(250, 248, 252, 255), outline=(200, 190, 220, 255))
    d.polygon([(x0 + w - fold, y0), (x0 + w - fold, y0 + fold), (x0 + w, y0 + fold)], fill=(226, 218, 238, 255))
    for i in range(6):
        y = y0 + 62 + i * 18
        d.rounded_rectangle([x0 + 22, y, x0 + w - 22 - (36 if i == 5 else 0), y + 6], 3, fill=(185, 175, 210, 255))
    im.save(png)
    rw = os.path.join(work, "rw.sparseimage")
    if os.path.exists(rw):
        os.remove(rw)
    run(["hdiutil", "convert", dmg, "-format", "UDSP", "-o", rw])
    mnt = os.path.join(work, "mnt")
    os.makedirs(mnt, exist_ok=True)
    run(["hdiutil", "attach", rw, "-mountpoint", mnt, "-nobrowse", "-noverify", "-noautoopen"])
    try:
        target = os.path.join(mnt, "READ ME FIRST.txt")
        js = ("ObjC.import('AppKit');"
              f"var img=$.NSImage.alloc.initWithContentsOfFile({json.dumps(png)});"
              f"$.NSWorkspace.sharedWorkspace.setIconForFileOptions(img,{json.dumps(target)},0);")
        run(["osascript", "-l", "JavaScript", "-e", js])
    finally:
        for attempt in range(5):
            if subprocess.run(["hdiutil", "detach", mnt]).returncode == 0:
                break
            time.sleep(5)
    os.remove(dmg)
    run(["hdiutil", "convert", rw, "-format", "UDZO", "-imagekey", "zlib-level=9", "-o", dmg])
    os.remove(rw)


def build_dmg_plist(apps, slugs, pkg, frozen):
    main = apps[pkg]
    plist_path = os.path.join(frozen, "Contents", "Info.plist")
    with open(plist_path, "rb") as f:
        pl = plistlib.load(f)
    pl.update({"CFBundleName": main["name"], "CFBundleDisplayName": main["name"],
               "CFBundleShortVersionString": main["version"], "CFBundleVersion": main["version"],
               "LSMinimumSystemVersion": str(main.get("macos_min", 11)), "NSHighResolutionCapable": True,
               "NSHumanReadableCopyright": "Digonto - digonto.dev - AGPL-3.0"})
    with open(plist_path, "wb") as f:
        plistlib.dump(pl, f)


def studio_exe(apps, slugs, pkg, frozen, outdir):
    """Windows: one .exe that unpacks Digonto Studio to a temporary folder and opens our welcome window
    (600 x 400, horizon background) - double-clicking the icon there opens the installer window"""
    main = apps[pkg]
    work = os.path.dirname(frozen)
    ico = icon_file(main, "ico")
    name = f"{main['name'].replace(' ', '-')}-{main['version']}-Windows-Setup.exe"
    os.makedirs(outdir, exist_ok=True)
    nsi = os.path.join(work, "studio.nsi")
    with open(nsi, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(f"""\
            Unicode true
            Name "{main['name']}"
            OutFile "{os.path.join(outdir, name)}"
            RequestExecutionLevel user
            SilentInstall silent
            SetCompressor /SOLID lzma
            {'Icon "' + ico + '"' if ico else ''}
            VIProductVersion "{'.'.join((main['version'].split('.') + ['0', '0', '0'])[:4])}"
            VIAddVersionKey "ProductName" "{main['name']} Setup"
            VIAddVersionKey "CompanyName" "Digonto"
            VIAddVersionKey "FileDescription" "{main['name']} Setup"
            VIAddVersionKey "FileVersion" "{main['version']}"
            VIAddVersionKey "LegalCopyright" "AGPL-3.0 - digonto.dev"
            Section
              InitPluginsDir
              Banner::show /NOUNLOAD /set 76 "{main['name']}" "Getting the setup ready..."
              SetOutPath "$PLUGINSDIR\\digonto"
              File /r "{frozen}\\*.*"
              Banner::destroy
              ExecWait '"$PLUGINSDIR\\digonto\\{pkg}.exe" --welcome'
              SetOutPath "$TEMP"
            SectionEnd
            """))
    makensis = shutil.which("makensis") or r"C:\Program Files (x86)\NSIS\makensis.exe"
    run([makensis, "/V2", nsi])
    return os.path.join(outdir, name)


def studio_deb(apps, slugs, pkg, frozen, outdir):
    """Linux: the .deb puts Digonto Studio in /opt and adds one "Install Digonto" icon; that opens our welcome
    window, and the installer window then gives every chosen program its own icon"""
    main = apps[pkg]
    ver = main["version"]
    root = os.path.join(os.path.dirname(frozen), "debroot")
    shutil.rmtree(root, ignore_errors=True)
    opt = os.path.join(root, "opt", "digonto", pkg)
    shutil.copytree(frozen, opt, symlinks=True)
    exe = f"/opt/digonto/{pkg}/{pkg}"
    appdir = os.path.join(root, "usr", "share", "applications")
    os.makedirs(appdir)
    with open(os.path.join(appdir, "digonto-studio-setup.desktop"), "w") as f:
        f.write(textwrap.dedent(f"""\
            [Desktop Entry]
            Type=Application
            Name=Install Digonto
            Comment=Choose which Digonto programs to install
            Exec={exe} --welcome
            Icon={pkg}
            Terminal=false
            Categories=System;Settings;
            StartupWMClass={pkg}
            """))
    for s in slugs:
        a = apps[s]
        for size in (16, 24, 32, 48, 64, 128, 256, 512):
            src = os.path.join(a["_src"], "assets", f"{s}-{size}.png")
            if os.path.isfile(src):
                d = os.path.join(root, "usr", "share", "icons", "hicolor", f"{size}x{size}", "apps")
                os.makedirs(d, exist_ok=True)
                shutil.copy2(src, os.path.join(d, f"{s}.png"))
    deps = list(DEB_BASE)
    for s in slugs:
        deps += [p for p in apps[s].get("apt", []) if p not in deps]
    size_kb = sum(os.path.getsize(os.path.join(dp, fn)) for dp, _d, fs in os.walk(root) for fn in fs
                  if not os.path.islink(os.path.join(dp, fn))) // 1024
    deb = os.path.join(root, "DEBIAN")
    os.makedirs(deb)
    arch = "arm64" if platform.machine() in ("aarch64", "arm64") else "amd64"
    with open(os.path.join(deb, "control"), "w") as f:
        f.write(textwrap.dedent(f"""\
            Package: {pkg}
            Version: {ver}
            Section: graphics
            Priority: optional
            Architecture: {arch}
            Maintainer: Digonto <digontodev@users.noreply.github.com>
            Homepage: {HOMEPAGE}
            Installed-Size: {size_kb}
            Depends: {', '.join(sorted(set(deps)))}
            Description: {main['name']} - {main.get('comment', main['name'])}
             Part of the Digonto programs (digonto.dev). Works without internet.
             After installing, click "Install Digonto" to choose the programs.
            """))
    # after installing: put "Install Digonto" in the dock of the person who is logged in (best effort)
    pin = textwrap.dedent("""\
        for s in $(loginctl list-sessions --no-legend 2>/dev/null | awk '{print $1}'); do
          u=$(loginctl show-session "$s" -p Name --value 2>/dev/null); a=$(loginctl show-session "$s" -p Active --value 2>/dev/null)
          [ "$a" = "yes" ] && [ -n "$u" ] && [ "$u" != "root" ] || continue
          uid=$(id -u "$u") || continue
          bus="unix:path=/run/user/$uid/bus"
          cur=$(runuser -u "$u" -- env DBUS_SESSION_BUS_ADDRESS="$bus" gsettings get org.gnome.shell favorite-apps 2>/dev/null) || continue
          case "$cur" in *digonto-studio*) continue;; esac
          new=$(echo "$cur" | sed "s/]$/, 'digonto-studio-setup.desktop']/; s/\\[, /[/; s/@as \\[\\]/['digonto-studio-setup.desktop']/")
          runuser -u "$u" -- env DBUS_SESSION_BUS_ADDRESS="$bus" gsettings set org.gnome.shell favorite-apps "$new" 2>/dev/null || true
        done
        """)
    for name, body in (("postinst", "update-desktop-database -q /usr/share/applications 2>/dev/null || true\n"
                                    "gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true\n" + pin),
                       ("postrm", "update-desktop-database -q /usr/share/applications 2>/dev/null || true\n")):
        p = os.path.join(deb, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + body + "exit 0\n")
        os.chmod(p, 0o755)
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"{pkg}_{ver}_{arch}.deb")
    run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", root, out])
    return out


# ---------------------------------------------------------------- main
def requirements_for(apps, slugs):
    return [os.path.join(apps[s]["_src"], apps[s]["requirements"]) for s in slugs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(HERE), help="folder with the digonto-* program folders")
    ap.add_argument("--apps", required=True, help="slugs separated by commas, or 'all'")
    ap.add_argument("--package", help="the program the package is named after (default: the first)")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--work", default=os.path.join(HERE, "work"))
    ap.add_argument("--print-requirements", action="store_true")
    ap.add_argument("--freeze-only", action="store_true")
    a = ap.parse_args()
    apps = load_apps(os.path.abspath(a.root))
    slugs = sorted(apps) if a.apps == "all" else [s.strip() for s in a.apps.split(",")]
    for s in slugs:
        if s not in apps:
            raise SystemExit(f"unknown program {s}; have: {', '.join(apps)}")
    pkg = a.package or slugs[0]
    if pkg not in slugs:
        slugs.insert(0, pkg)
    if a.print_requirements:
        print("\n".join(requirements_for(apps, slugs)))
        return
    work = os.path.join(os.path.abspath(a.work), pkg)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    frozen = freeze(apps, slugs, pkg, work)
    if pkg == STUDIO:
        add_ai(frozen)
    if a.freeze_only:
        print(frozen)
        return
    out = os.path.abspath(a.out)
    if pkg == STUDIO:
        made = {"Linux": studio_deb, "Darwin": studio_dmg, "Windows": studio_exe}[SYS](apps, slugs, pkg, frozen, out)
    else:
        made = {"Linux": build_deb, "Darwin": build_dmg, "Windows": build_exe}[SYS](apps, slugs, pkg, frozen, out)
    print("MADE", made)


if __name__ == "__main__":
    main()
