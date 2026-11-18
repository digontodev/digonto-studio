"""Digonto AI helper: background removal with rembg, as its own small program.

    digonto-ai check                                   prints 'ok <engine version>'
    digonto-ai mask <in.png> <out.png> [--model u2net] [--soft]
    digonto-ai serve                                   keeps running: one JSON request per line on stdin
        {"in": "...", "out": "...", "model": "u2net", "soft": false}  ->  "ok" or "error <text>" per line

The models live in a 'models' folder next to the helper, or two folders up (ai/models, shared by the helpers
for each system).  Nothing is ever downloaded.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
for _cand in (os.path.join(HERE, "models"), os.path.join(HERE, "..", "..", "models"), os.path.join(HERE, "..", "models")):
    if os.path.isdir(_cand):
        os.environ.setdefault("U2NET_HOME", os.path.abspath(_cand))
        break
os.environ.setdefault("U2NET_HOME", os.path.join(HERE, "models"))
os.environ["NO_ALBUMENTATIONS_UPDATE"] = "1"

_sessions = {}


def _without_pymatting():
    """rembg imports pymatting (and through it numba + llvmlite, ~190 MB) only for 'alpha matting', which Digonto
    never uses. A tiny stand-in keeps the helper small; asking for alpha matting gives a clear error."""
    import types

    def not_included(*_a, **_k):
        raise RuntimeError("alpha matting is not included in the Digonto AI helper")
    for name, funcs in (("pymatting", ()), ("pymatting.alpha", ()), ("pymatting.alpha.estimate_alpha_cf", ("estimate_alpha_cf",)),
                        ("pymatting.foreground", ()),
                        ("pymatting.foreground.estimate_foreground_ml", ("estimate_foreground_ml",)),
                        ("pymatting.util", ()), ("pymatting.util.util", ("stack_images",))):
        m = sys.modules.get(name) or types.ModuleType(name)
        for f in funcs:
            setattr(m, f, not_included)
        sys.modules[name] = m


try:
    import pymatting  # noqa: F401 - the real one, when it is there (developer machines)
except Exception:                                            # noqa: BLE001
    _without_pymatting()


def models():
    d = os.environ["U2NET_HOME"]
    return sorted(os.path.splitext(f)[0] for f in os.listdir(d) if f.endswith(".onnx")) if os.path.isdir(d) else []


def make_mask(src, dst, model="u2net", soft=False):
    from PIL import Image
    from rembg import new_session, remove
    if not os.path.isfile(os.path.join(os.environ["U2NET_HOME"], model + ".onnx")):
        raise RuntimeError(f"model '{model}' is not installed (have: {', '.join(models()) or 'none'})")
    if model not in _sessions:
        _sessions[model] = new_session(model)
    img = Image.open(src).convert("RGB")
    remove(img, session=_sessions[model], only_mask=True, post_process_mask=not soft).save(dst)


def main(argv):
    if not argv or argv[0] == "check":
        import onnxruntime
        print("ok", onnxruntime.__version__, " ".join(models()))
        return 0
    if argv[0] == "mask" and len(argv) >= 3:
        model = argv[argv.index("--model") + 1] if "--model" in argv else "u2net"
        make_mask(argv[1], argv[2], model, "--soft" in argv)
        return 0
    if argv[0] == "serve":
        import rembg  # noqa: F401 - load the engine once, before the first request
        print("ready", flush=True)
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if line == "quit":
                break
            try:
                r = json.loads(line)
                make_mask(r["in"], r["out"], r.get("model", "u2net"), bool(r.get("soft")))
                print("ok", flush=True)
            except Exception as e:                          # noqa: BLE001 - report and keep serving
                print("error", str(e).replace("\n", " ")[:300], flush=True)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
