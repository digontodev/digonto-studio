#!/bin/bash
# Builds the native Apple-chip (M1/M2/M3/M4) Digonto AI helper.  Run it on an M-chip Mac:
#     bash build-ai-mac-arm.sh
# Result on your Desktop: digonto-ai-macos-arm64.zip
set -e
cd "$(dirname "$0")"
if [ "$(uname -m)" != "arm64" ]; then echo "Run this on an M-chip Mac (this one is $(uname -m))."; exit 1; fi
PY=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)
if [ "$("$PY" -c 'import platform;print(platform.machine())')" != "arm64" ]; then
  echo "Your python3 is an Intel version. Install Python 3.12 from https://www.python.org/downloads/macos/ and run again."; exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo "Your Python is $("$PY" --version 2>&1) - too old (the Mac's built-in one). Install Python 3.12 from https://www.python.org/downloads/macos/ and run again."; exit 1
fi
WORK="$HOME/digonto-ai-build"; rm -rf "$WORK"; mkdir -p "$WORK"
cp digonto_ai.py "$WORK/"; cd "$WORK"
"$PY" -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -q "rembg==2.0.87" onnxruntime pillow numpy pyinstaller
./venv/bin/pyinstaller --noconfirm --onedir --name digonto-ai \
    --collect-all rembg --collect-all onnxruntime --collect-all pooch --collect-submodules scipy \
    --exclude-module pymatting --exclude-module numba --exclude-module llvmlite --exclude-module tkinter \
    --copy-metadata rembg --copy-metadata pooch --copy-metadata onnxruntime --copy-metadata numpy \
    --copy-metadata pillow digonto_ai.py
mkdir -p dist/digonto-ai/models
curl -L -o dist/digonto-ai/models/u2net.onnx https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx
codesign --force --deep -s - dist/digonto-ai
./dist/digonto-ai/digonto-ai check
# real test: cut out a red circle on a grey background
./venv/bin/python -c "from PIL import Image, ImageDraw; im=Image.new('RGB',(320,320),'#888'); ImageDraw.Draw(im).ellipse((80,60,240,260),fill='#c22'); im.save('test.png')"
./dist/digonto-ai/digonto-ai mask test.png test-mask.png && echo "cut-out test: OK"
cd dist && ditto -c -k --keepParent digonto-ai "$HOME/Desktop/digonto-ai-macos-arm64.zip"
echo; echo "Done: $HOME/Desktop/digonto-ai-macos-arm64.zip  ($(du -h "$HOME/Desktop/digonto-ai-macos-arm64.zip" | cut -f1))"
