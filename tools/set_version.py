"""Stamp a display version into the KID PIX bundle.

usage: set_version.py <path/KID PIX.app | path/Info.plist> <version>

Sets CFBundleShortVersionString and CFBundleGetInfoString ("5.0.3 (252)") to
<version>. CFBundleVersion stays 252, as the app and its updater expect a
number there. Where the app reads the short version as a number
(doubleValue), "5.0.3-U2B" and "5.0.3" both read as 5.0.
"""
import plistlib
import sys


def main():
    app, ver = sys.argv[1], sys.argv[2]
    info = app if app.endswith(".plist") else f"{app}/Contents/Info.plist"
    with open(info, "rb") as fh:
        fmt = plistlib.FMT_BINARY if fh.read(6) == b"bplist" else plistlib.FMT_XML
        fh.seek(0)
        p = plistlib.load(fh)
    p["CFBundleShortVersionString"] = ver
    p["CFBundleGetInfoString"] = ver
    with open(info, "wb") as fh:
        plistlib.dump(p, fh, fmt=fmt)
    print(info, "->", ver, "(CFBundleVersion", p.get("CFBundleVersion") + ")")


if __name__ == "__main__":
    main()
