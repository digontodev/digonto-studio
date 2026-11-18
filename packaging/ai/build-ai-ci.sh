#!/bin/bash
# CI: builds the Digonto AI helper for this computer and collects everything into one folder:
#     <out>/models/*.onnx                       the AI models (shared)
#     <out>/<system>-<chip>/digonto-ai/         the helper for each system
# On macOS (Intel runner) it also takes the Apple-chip helper from the 'ai-engines' release.
set -euo pipefail
OUT="$1"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
case "$(uname -s)" in
  Darwin) SYS=macos ;;
  MINGW*|MSYS*|CYGWIN*) SYS=windows ;;
  *) SYS=linux ;;
esac
ARCH=x86_64
mkdir -p "$OUT/models"

# 1. models (rembg's own release files): u2net (all-round), isnet-general-use (best edges), u2netp (fast)
for m in u2net isnet-general-use u2netp; do
  [ -f "$OUT/models/$m.onnx" ] || curl -fsSL --retry 3 -o "$OUT/models/$m.onnx" \
    "https://github.com/danielgatis/rembg/releases/download/v0.0.0/$m.onnx"
done
ls -la "$OUT/models"

# 2. the helper for this computer (own venv: does not touch the Studio build libraries)
cp "$HERE/digonto_ai.py" "$WORK/"
cd "$WORK"
python -m venv venv
if [ "$SYS" = windows ]; then PY=venv/Scripts/python.exe; else PY=venv/bin/python; fi
ORT=onnxruntime
[ "$SYS" = macos ] && ORT="onnxruntime==1.23.2"      # the last version made for Intel Macs
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q "rembg==2.0.87" "$ORT" pillow numpy "pyinstaller==6.22.3"
"$PY" -m PyInstaller --noconfirm --onedir --name digonto-ai \
    --collect-all rembg --collect-all onnxruntime --collect-all pooch --collect-submodules scipy \
    --exclude-module pymatting --exclude-module numba --exclude-module llvmlite --exclude-module tkinter \
    --copy-metadata rembg --copy-metadata pooch --copy-metadata onnxruntime --copy-metadata numpy \
    --copy-metadata pillow digonto_ai.py
mkdir -p "$OUT/$SYS-$ARCH"
rm -rf "$OUT/$SYS-$ARCH/digonto-ai"
mv dist/digonto-ai "$OUT/$SYS-$ARCH/"
EXE="$OUT/$SYS-$ARCH/digonto-ai/digonto-ai"; [ "$SYS" = windows ] && EXE="$EXE.exe"
"$EXE" check
python -c "from PIL import Image, ImageDraw; im=Image.new('RGB',(320,320),'#888'); ImageDraw.Draw(im).ellipse((80,60,240,260),fill='#c22'); im.save('t.png')" 2>/dev/null \
  || "$PY" -c "from PIL import Image, ImageDraw; im=Image.new('RGB',(320,320),'#888'); ImageDraw.Draw(im).ellipse((80,60,240,260),fill='#c22'); im.save('t.png')"
"$EXE" mask t.png t-mask.png --model u2netp && echo "cut-out test: OK"

# 3. macOS: the Apple-chip helper, built once on an M-chip Mac and kept on the 'ai-engines' release
if [ "$SYS" = macos ]; then
  gh release download ai-engines -R "$GITHUB_REPOSITORY" -p "digonto-ai-macos-arm64.zip" -D "$WORK"
  rm -rf "$OUT/macos-arm64"; mkdir -p "$OUT/macos-arm64"
  ditto -x -k "$WORK/digonto-ai-macos-arm64.zip" "$OUT/macos-arm64"
  A="$OUT/macos-arm64/digonto-ai"
  if [ -d "$A/models" ]; then                         # its model goes to the shared folder; a link stays behind
    for f in "$A"/models/*.onnx; do [ -f "$OUT/models/$(basename "$f")" ] || mv "$f" "$OUT/models/"; done
    rm -rf "$A/models"
  fi
  ln -s ../../models "$A/models"
  file "$A/digonto-ai" | grep -q arm64 && echo "Apple-chip helper: OK"
fi
du -sh "$OUT"/*
