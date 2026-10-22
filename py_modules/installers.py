"""What kind of Windows installer a mod's .exe is, and how to run it
without its window.

* Self-extracting archives (7-Zip, WinRAR, zip SFX) are just archives with
  a stub in front: they are unpacked and installed like any other mod.
* Inno Setup and NSIS installers - what most mod installers are built with -
  have documented unattended modes with a target folder:
    Inno:  /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR=<folder>
    NSIS:  /S /D=<folder>   (/D last, unquoted, even with spaces)
  and Windows Installer packages:  msiexec /i <msi> /qn TARGETDIR=<folder>.
* Anything else is a program of its own (a mod manager, an editor) and is
  left for the user to run.
"""

from __future__ import annotations

import os
import re

SEVEN_SIG = b"7z\xbc\xaf\x27\x1c"
RAR_SIG = b"Rar!\x1a\x07"
INNO_MARK = b"Inno Setup Setup Data"
NSIS_MARK = b"NullsoftInst"
SCAN = 8 << 20

# Programs that are applications in their own right, not mod installers:
# installing them silently into the game folder would be wrong.
_APP_WORDS = re.compile(r"manager|launcher|editor|unpacker|repacker|randomi[sz]er|toolkit|"
                        r"\btools?\b|studio|viewer|creator|maker", re.I)


def kind(path: str) -> str:
    """'7z', 'rar', 'zip' (self-extracting), 'inno', 'nsis', 'msi',
    'clickteam' or ''."""
    low = path.lower()
    if low.endswith(".msi"):
        return "msi"
    if not low.endswith(".exe"):
        return ""
    try:
        with open(path, "rb") as f:
            head = f.read(SCAN)
            size = os.path.getsize(path)
            f.seek(max(0, size - 65536))
            tail = f.read()
    except OSError:
        return ""
    if head[:2] != b"MZ":
        return ""
    if INNO_MARK in head or "Inno Setup".encode("utf-16-le") in head:
        return "inno"
    if NSIS_MARK in head:
        return "nsis"
    if b"clickteam.com" in head.lower():
        return "clickteam"  # Install Creator: no documented target-folder switch, so run by hand
    off = sfx_offset(head)
    if off is not None:
        return "7z" if head[off:off + 6] == SEVEN_SIG else "rar"
    if b"PK\x05\x06" in tail:
        return "zip"
    return ""


def sfx_offset(head: bytes):
    """Where the archive starts inside a self-extracting .exe, or None."""
    if head[:2] != b"MZ":
        return None
    for sig in (SEVEN_SIG, RAR_SIG):
        i = head.find(sig, 512)
        while i != -1:
            # A 7z signature must be followed by version 0.x; a RAR one by 0/1.
            nxt = head[i + len(sig):i + len(sig) + 2]
            if (sig == SEVEN_SIG and nxt[:1] == b"\x00") or (sig == RAR_SIG and nxt[:1] in (b"\x00", b"\x01")):
                return i
            i = head.find(sig, i + 1)
    return None


def silent_args(k: str, exe: str, target: str) -> list:
    target = target.rstrip("\\/")
    if k == "inno":
        return [exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/NOICONS",
                f"/DIR={target}"]
    if k == "nsis":
        return [exe, "/S", f"/D={target}"]
    if k == "msi":
        return ["msiexec", "/i", exe, "/qn", "/norestart", f"TARGETDIR={target}", f"INSTALLDIR={target}"]
    return []


def auto_ok(k: str, mod_name: str, exe_name: str) -> bool:
    """Run this installer by itself, silently into the game folder?"""
    if k not in ("inno", "nsis", "msi"):
        return False
    return not _APP_WORDS.search(f"{mod_name} {os.path.basename(exe_name)}")
