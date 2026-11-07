# KID PIX 5 — Universal 2

Runs KID PIX 5 — The S.T.E.A.M. Edition (5.0.3, build 252) natively on Apple
silicon by statically recompiling its x86_64 executable to arm64 and shipping
both slices in one Universal 2 binary. No Rosetta needed.

## How it works

- `tools/lift.py` disassembles every x86_64 function (with capstone) in the
  main executable and its private frameworks (`zUIKit`, `SMKCheckForUpdates`,
  and the bundled `libc++`, listed in `image.json`) and emits C that runs it
  against an emulated register file (`gen/lift_*.c`, functions named
  `F_<x86 address>`).
- `tools/relink.py` reproduces the original data segments and pointers
  (`gen/image.s`, `gen/image.c`, `gen/table.c`), and `tools/eh.py` translates
  the C++ exception tables.
- `tools/gensigs.py` and `tools/sigtable.py` derive a native type signature
  for each imported function from the SDK headers.
- `runtime/` is the bridge between the recompiled code and macOS:
  - `abi.c` converts arguments and return values between x86-64 SysV and arm64.
  - `rt.m` handles imports, `objc_msgSend`, printf-style variadics, `va_list`
    imports, blocks and callbacks into recompiled code.
  - `eh.c` runs the C++ exceptions thrown by the recompiled code.
  - `ctl.m` is a small test hook: with `X86RT_CTL` set, it reads commands
    (`windows`, `snap`, `click`, `drag`, `key`, `menu`, …) from `$X86RT_CTL/cmd`.

## Build

```sh
mkdir -p orig && cp -cR "/path/to/original/KID PIX.app" orig/   # x86_64-only copy
cp /path/to/libc++.dylib orig/libc++.x86_64.dylib               # an x86_64 build of LLVM's libc++
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./build.sh            # full lift + build -> out/KidPix.arm64 (about 5 minutes)
./build.sh --nolift   # after runtime/ or relink changes only
```

## Test and install

```sh
./run.sh                                # runs inside test/ (a copy of orig/), log in out/run.log
X86RT_TRACE=1 ./run.sh                  # log every bridged call
python3 tools/crash.py                  # summarize the newest KidPix.arm64 crash report
./install.sh "/Applications/KID PIX.app" # lipo x86_64 + arm64, ad-hoc sign, back up the old binary to out/
```

## Disk image

`make-dmg.sh` builds `out/KIDPIX5Mac_5.0.3-U2B.dmg` from MacKiev's
`KIDPIX5Mac.dmg`. KID PIX ships as an installer package, so the image keeps
MacKiev's installer (its school/home options and Dock scripts) and adds one
hidden component package to it. That package:

- stages the Universal 2 executable and a stamped `Info.plist` in
  `/private/tmp/kidpix5-universal2`;
- runs after MacKiev's package, and its postinstall (`pkg/scripts/postinstall`)
  moves them into `/Applications/KID PIX.app` and re-signs the app ad hoc.

The display version reads 5.0.3-U2B. `CFBundleVersion` stays 252, because the
app's update check compares it as a number.

The volume name, icon, background, window layout, user guide and Get School
Pricing app are copied unchanged from MacKiev's image.

```sh
./make-dmg.sh KIDPIX5Mac.dmg 5.0.3-U2B
```

The template is only read. The build needs about 11 GB free while it runs.

## Known issues

- The app is signed ad hoc, and the installer package is unsigned (adding a
  component removes MacKiev's signature). The first time, macOS asks before
  opening the installer: Control-click it and choose Open, or allow it in
  System Settings > Privacy & Security.
