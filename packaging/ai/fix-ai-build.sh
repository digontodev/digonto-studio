#!/bin/bash
# Rebuilds the Digonto AI helper in ~/digonto-ai-build without downloading everything again.
set -e
cd "$HOME/digonto-ai-build"
[ -f dist/digonto-ai/models/u2net.onnx ] && mv dist/digonto-ai/models/u2net.onnx ./u2net.onnx
./venv/bin/pyinstaller --noconfirm --onedir --name digonto-ai \
    --collect-all rembg --collect-all onnxruntime --collect-all pooch --collect-submodules scipy \
    --exclude-module pymatting --exclude-module numba --exclude-module llvmlite --exclude-module tkinter \
    --copy-metadata rembg --copy-metadata pooch --copy-metadata onnxruntime --copy-metadata numpy \
    --copy-metadata pillow digonto_ai.py
mkdir -p dist/digonto-ai/models && mv u2net.onnx dist/digonto-ai/models/
codesign --force --deep -s - dist/digonto-ai
./dist/digonto-ai/digonto-ai check
./venv/bin/python -c "from PIL import Image, ImageDraw; im=Image.new('RGB',(320,320),'#888'); ImageDraw.Draw(im).ellipse((80,60,240,260),fill='#c22'); im.save('test.png')"
./dist/digonto-ai/digonto-ai mask test.png test-mask.png && echo "cut-out test: OK"
rm -f "$HOME/Desktop/digonto-ai-macos-arm64.zip"
cd dist && ditto -c -k --keepParent digonto-ai "$HOME/Desktop/digonto-ai-macos-arm64.zip"
echo; echo "Done: $HOME/Desktop/digonto-ai-macos-arm64.zip  ($(du -h "$HOME/Desktop/digonto-ai-macos-arm64.zip" | cut -f1))"
