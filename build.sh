#!/bin/zsh
# Build the arm64 slice of KID PIX from its x86_64 executable and private frameworks (image.json).
#   ./build.sh           lift, relink and compile everything
#   ./build.sh --nolift  reuse gen/lift_*.c (runtime or relink changes only)
set -e
cd "${0:A:h}"
APP_BIN="${APP_BIN:-image.json}"
PY="${PY:-.venv/bin/python}"
for f in "orig/KID PIX.app/Contents/MacOS/KID PIX" orig/libc++.x86_64.dylib; do
  [[ -f "$f" ]] || { echo "missing $f: see README (Build)" >&2; exit 1; }
done
if ! lipo -info "orig/KID PIX.app/Contents/MacOS/KID PIX" | grep -q "architecture: x86_64"; then
  echo "orig/KID PIX.app must be the original x86_64-only app, not a universal build" >&2
  exit 1
fi
OPT="${OPT:--O1}"
mkdir -p gen obj out
if [[ "$1" != "--nolift" && "$1" != "--link" ]]; then
  $PY tools/lift.py "$APP_BIN" gen
fi
$PY tools/relink.py "$APP_BIN" gen
$PY tools/gensigs.py gen
CF=(-arch arm64 -mmacosx-version-min=11.0 -Iruntime -Igen -g0)
ls gen/lift_*.c | xargs -P "$(sysctl -n hw.ncpu)" -I{} sh -c 'f={}; o=obj/$(basename $f .c).o; [ "$o" -nt "$f" ] || clang '"$OPT ${CF[*]}"' -c $f -o $o'
clang $OPT $CF -c gen/table.c -o obj/table.o
clang $OPT $CF -c gen/image.c -o obj/image_c.o
clang $CF -c gen/image.s -o obj/image.o
clang $CF -c gen/tramp.s -o obj/tramp.o
clang $CF -c runtime/stubs.s -o obj/stubs.o
clang $OPT $CF -c runtime/abi.c -o obj/abi.o
clang $OPT $CF -c runtime/eh.c -o obj/eh.o
clang $OPT $CF -fno-objc-arc -c runtime/rt.m -o obj/rt.o
clang $OPT $CF -fobjc-arc -c runtime/ctl.m -o obj/ctl.o
clang++ $CF -std=c++17 -O0 -I"$(xcrun --show-sdk-path)/usr/include/libxml2" gen/sigs.mm $(cat fw.txt) -o gen/dumpsigs
gen/dumpsigs | $PY tools/sigtable.py gen
clang $OPT $CF -c gen/sigs_table.c -o obj/sigs.o
clang++ $CF obj/*.o $(cat fw.txt) $(sed 's/^/-Wl,-U,/' gen/weak.txt) -Wl,-no_objc_category_merging -Wl,-platform_version,macos,11.0,10.15 -o out/KidPix.arm64
echo built out/KidPix.arm64
