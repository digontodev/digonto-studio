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
./venv/bin/pip install -q --only-binary=:all: --no-deps "rembg==2.0.87"
./venv/bin/pip install -q --only-binary=:all: "jsonschema>=4.25.1,<5" "numpy>=2.3,<3" "pillow>=12.3,<14" \
    "pooch>=1.8.2,<2" "scikit-image>=0.26,<0.27" "scipy>=1.16.3,<2" "tqdm>=4.67.1,<5" onnxruntime pyinstaller
./venv/bin/pyinstaller --noconfirm --onedir --name digonto-ai \
    --collect-all rembg --collect-all onnxruntime --collect-all pooch --collect-submodules scipy \
    --exclude-module pymatting --exclude-module numba --exclude-module llvmlite --exclude-module tkinter \
    --copy-metadata rembg --copy-metadata pooch --copy-metadata onnxruntime --copy-metadata numpy \
    --copy-metadata pillow digonto_ai.py
codesign --force --deep -s - dist/digonto-ai
# test with the small model (the models themselves are added by the Studio build, not kept in the zip)
mkdir -p dist/digonto-ai/models
curl -fsSL -o dist/digonto-ai/models/u2netp.onnx https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx
./dist/digonto-ai/digonto-ai check
./venv/bin/python -c "from PIL import Image, ImageDraw; im=Image.new('RGB',(320,320),'#888'); ImageDraw.Draw(im).ellipse((80,60,240,260),fill='#c22'); im.save('test.png')"
./dist/digonto-ai/digonto-ai mask test.png test-mask.png --model u2netp
echo "cut-out test: OK"
ANS=$(printf '{"in":"test.png","out":"t2.png","model":"u2netp"}\nquit\n' | ./dist/digonto-ai/digonto-ai serve)
echo "$ANS" | grep -q '^ok' || { echo "serve test FAILED: $ANS"; exit 1; }
echo "serve test: OK"
rm -rf dist/digonto-ai/models
rm -f "$HOME/Desktop/digonto-ai-macos-arm64.zip"
cd dist && ditto -c -k --keepParent digonto-ai "$HOME/Desktop/digonto-ai-macos-arm64.zip"
echo; echo "Done: $HOME/Desktop/digonto-ai-macos-arm64.zip  ($(du -h "$HOME/Desktop/digonto-ai-macos-arm64.zip" | cut -f1))"
