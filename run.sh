#!/bin/zsh
# Launch out/KidPix.arm64 inside a copy of the original bundle (test/), logging to out/run.log.
# Set X86RT_TRACE=1 to log every bridged call. runtime/ctl.m reads commands from $CTL/cmd.
cd "${0:A:h}"
B="test/KID PIX.app"
D="$B/Contents/MacOS"
if [[ ! -d "$B" ]]; then
  mkdir -p test && cp -cR "orig/KID PIX.app" test/
fi
for p in $(pgrep -x KidPix.arm64); do kill $p; done
# rm first: overwriting in place breaks the binary's signature.
rm -f "$D/KidPix.arm64" && cp -c out/KidPix.arm64 "$D/KidPix.arm64"
CTL="${CTL:-$PWD/out/ctl}"; mkdir -p "$CTL"
LOG="${LOG:-$PWD/out/run.log}"
cd "$D" && (X86RT_CTL="$CTL" ./KidPix.arm64 -ApplePersistenceIgnoreState YES > "$LOG" 2>&1 &)
