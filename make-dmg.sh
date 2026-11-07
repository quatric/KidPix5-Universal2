#!/bin/zsh
# Build a Universal 2 disk image from MacKiev's KIDPIX5Mac.dmg.
#   ./make-dmg.sh <KIDPIX5Mac.dmg> [version]
# Keeps MacKiev's installer (its options pane and Dock/preferences scripts)
# and appends a small package that installs the Universal 2 executable and
# the stamped Info.plist into /Applications/KID PIX.app, then re-signs it ad
# hoc. The image keeps the original volume name, background, layout, user
# guide and Get School Pricing app. Writes out/KIDPIX5Mac_<version>.dmg.
# Needs about 11 GB free while it runs.
set -e
cd "${0:A:h}"
TEMPLATE="${1:?usage: make-dmg.sh <KIDPIX5Mac.dmg> [version]}"
VER="${2:-5.0.3-U2B}"
PY="${PY:-.venv/bin/python}"
PKG_ID="io.github.quatric.kidpix5-universal2"
PKG_VER="5.0.3.252.1"
X86="orig/KID PIX.app/Contents/MacOS/KID PIX"
[[ -f out/KidPix.arm64 ]] || { echo "build first: ./build.sh" >&2; exit 1; }

W="$PWD/out/dmg-work"
OUT="$PWD/out/KIDPIX5Mac_${VER}.dmg"
rm -rf "$W" "$OUT"
mkdir -p "$W/tmpl" "$W/stage"
hdiutil attach -nobrowse -noautoopen -readonly -mountpoint "$W/tmpl" "$TEMPLATE" >/dev/null
trap 'hdiutil detach "$W/tmpl" -quiet 2>/dev/null || true' EXIT

# Everything on the volume except the installer, with Finder info and resource forks.
for f in .DS_Store .VolumeIcon.icns .background "Get School Pricing.app" "KID PIX User Guide.pdf"; do
  ditto "$W/tmpl/$f" "$W/stage/$f"
done
pkgutil --expand "$W/tmpl/KID PIX Installer.pkg" "$W/product"
hdiutil detach "$W/tmpl" -quiet
trap - EXIT

# Add-on component: files staged in /private/tmp, moved into the app by its postinstall.
R="$W/patchroot/private/tmp/kidpix5-universal2"
mkdir -p "$R"
lipo -create "$X86" out/KidPix.arm64 -output "$R/KID PIX"
chmod 755 "$R/KID PIX"
cp "orig/KID PIX.app/Contents/Info.plist" "$R/Info-U2B.plist"
$PY tools/set_version.py "$R/Info-U2B.plist" "$VER"
pkgbuild --root "$W/patchroot" --install-location / --scripts pkg/scripts \
  --identifier "$PKG_ID" --version "$PKG_VER" "$W/universal2.pkg"
pkgutil --expand "$W/universal2.pkg" "$W/product/KIDPIX-Universal2.pkg"
KB=$(( ($(stat -f %z "$R/KID PIX") + $(stat -f %z "$R/Info-U2B.plist")) / 1024 + 1 ))
$PY tools/add_pkg_to_distribution.py "$W/product/Distribution" "$PKG_ID" "$PKG_VER" "$KB" KIDPIX-Universal2.pkg
rm -rf "$W/patchroot" "$W/universal2.pkg"

pkgutil --flatten "$W/product" "$W/stage/KID PIX Installer.pkg"
rm -rf "$W/product"
xar -tf "$W/stage/KID PIX Installer.pkg" | grep -qx "KIDPIX-Universal2.pkg/Payload"

# hdiutil -srcfolder drops the root folder's Finder flags, so build read-write,
# set the custom-icon flag on the mounted volume (it uses .VolumeIcon.icns),
# then compress.
hdiutil create -srcfolder "$W/stage" -volname "KID PIX" -fs HFS+ -format UDRW -o "$W/rw.dmg"
rm -rf "$W/stage"
mkdir -p "$W/rw"
hdiutil attach -nobrowse -noautoopen -mountpoint "$W/rw" "$W/rw.dmg" >/dev/null
SetFile -a C "$W/rw"
GetFileInfo -aC "$W/rw" | grep -qx 1
hdiutil detach "$W/rw" -quiet
hdiutil convert "$W/rw.dmg" -format UDZO -o "$OUT"
rm -rf "$W"
hdiutil verify "$OUT" >/dev/null
echo "built $OUT"
