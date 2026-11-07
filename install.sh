#!/bin/zsh
# Merge the original x86_64 executable with out/KidPix.arm64 and install the
# Universal 2 executable into an existing copy of the app, keeping a backup.
#   ./install.sh "/Applications/KID PIX.app"
set -e
cd "${0:A:h}"
DEST="${1:?usage: install.sh <path to KID PIX.app>}"
X86="orig/KID PIX.app/Contents/MacOS/KID PIX"
E="$DEST/Contents/MacOS/KID PIX"
[[ -f "$E" ]] || { echo "no executable at $E" >&2; exit 1; }
[[ -f out/KidPix.arm64 ]] || { echo "build first: ./build.sh" >&2; exit 1; }
cp -p "$E" "out/KID PIX.backup-$(date +%Y%m%d-%H%M%S)"
lipo -create "$X86" out/KidPix.arm64 -output out/universal.tmp
rm -f "$E" && mv out/universal.tmp "$E" && chmod 755 "$E"
codesign --force --deep --sign - "$DEST"
lipo -info "$E"
codesign --verify --deep --strict "$DEST" && echo "installed and verified: $DEST"
