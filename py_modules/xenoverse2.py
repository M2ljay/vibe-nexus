"""Dragon Ball Xenoverse 2 support for experimental games.

Xenoverse 2 needs two community tools by eterniti ("Eternity Tools", hosted
on videogamemods.com, not Nexus or GitHub):

* XV2 Patcher  - bin/xinput1_3.dll plus an XV2PATCHER folder in the game
                 root. With loose_files on, the game reads a data/ folder in
                 the game root: "loose file" mods merge into it.
* xv2ins       - XV2 Mods Installer. Installs .x2m mods (characters,
                 skills, stages, costumes) by editing the game's system
                 files under data/. It takes .x2m paths on its command line;
                 with two or more it asks once to go silent, then reports.
                 It has no command-line uninstall: removing an x2m happens
                 in its window.

Pure helpers here; downloads, processes and windows live in main.py.
"""

from __future__ import annotations

import os
import re
import zipfile

DOMAIN = "dragonballxenoverse2"
EXE = "bin/DBXV2.exe"
TOOLS_PAGE = "https://videogamemods.com/the-citadel/dragon-ball-xenoverse-2/mods/eternity-tools"
PATCHER_DLL = "bin/xinput1_3.dll"
PATCHER_ALT_DLL = "bin/dinput8.dll"
PATCHER_DIR = "XV2PATCHER"
PATCHER_INI = PATCHER_DIR + "/xv2patcher.ini"
INSTALLER_EXE = "xv2ins.exe"
INSTALL_DATA = "data/InstallData"
# x2m files wait here (inert to the game) until xv2ins installs them.
X2M_STORE = "_nexus_x2m"
X2M_EXT = ".x2m"
MIN_PATCHER = 4.7

# Window titles of xv2ins dialogs that are safe to answer with Enter:
# the silent-mode question (default Yes) and its information boxes
# ("xv2ins <version>": installed / updated / N of M). Anything else - the
# clean-install or port-over choice, a language prompt, an error - is left
# for the person, because Enter there can mean "clear every mod".
_AUTO_TITLES = re.compile(r"^(Activate silent mode\?|xv2ins \d[\w.]*)$")

_ARCHIVE_NAME = re.compile(r"eternity|xv2|xenoverse", re.I)
_ARCHIVE_EXTS = (".zip", ".7z", ".rar")


def is_xv2_game(game: dict) -> bool:
    return game.get("toolApply") == "xv2ins"


def apply_xv2_profile(game: dict) -> bool:
    """Turn the Xenoverse 2 entry into a patcher + xv2ins managed one."""
    if game.get("nexusDomain") != DOMAIN:
        return False
    game["processName"] = EXE
    game["engine"] = "xv2"
    game["modsSubdir"] = X2M_STORE
    game["flatModExtensions"] = [X2M_EXT]
    game["toolApply"] = "xv2ins"
    game["mergeInto"] = "data"
    game.pop("mergeBase", None)
    game.pop("ue4ss", None)
    game.pop("extraFrameworks", None)
    game["framework"] = {
        "name": "XV2 Patcher + XV2 Mods Installer",
        "nexusModId": 0,
        "detectFile": PATCHER_DLL,
        "url": TOOLS_PAGE,
        "installKind": "xv2tools",
        "installSubdir": "",
        "warning": (
            "Xenoverse 2 mods need eterniti's XV2 Patcher and XV2 Mods "
            "Installer (Eternity Tools, from videogamemods.com - not Nexus). "
            "Step 1 puts them in the game folder; Remove takes them out. "
            "The game has EasyAntiCheat: play modded offline or in private "
            "modes - going online with changed files can get your account "
            "flagged or banned."
        ),
    }
    game["underConstruction"] = (
        "Experimental generic support. Loose-file mods go into the game's "
        "data folder. .x2m mods (characters, skills, stages) are installed "
        "by XV2 Mods Installer: after each install the plugin runs it and "
        "answers its questions; uninstalling an .x2m opens the installer's "
        "window on the desktop so you can remove it there. Mods that come "
        "as their own installer program have to be run from the desktop."
    )
    return True


# ---- Step 1: finding the tools ---------------------------------------------------

def candidate_archives(dirs: list) -> list:
    """Archives in these folders whose names look like Eternity Tools,
    the patcher or the installer, newest first."""
    found = []
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            if n.lower().endswith(_ARCHIVE_EXTS) and _ARCHIVE_NAME.search(n) and os.path.isfile(p):
                try:
                    found.append((os.path.getmtime(p), p))
                except OSError:
                    pass
    return [p for _t, p in sorted(found, reverse=True)]


def find_tools(tree: str) -> dict:
    """Where the patcher and the installer are inside an extracted tree:
    {"patcher": dir holding bin/xinput1_3.dll and XV2PATCHER,
     "installer": dir holding xv2ins.exe}; missing keys were not found."""
    out = {}
    for cur, dirs, names in os.walk(tree):
        low_dirs = {d.lower(): d for d in dirs}
        low_names = {n.lower() for n in names}
        if "patcher" not in out and "xv2patcher" in low_dirs and "bin" in low_dirs:
            bin_dir = os.path.join(cur, low_dirs["bin"])
            try:
                bins = {n.lower() for n in os.listdir(bin_dir)}
            except OSError:
                bins = set()
            if "xinput1_3.dll" in bins or "dinput8.dll" in bins:
                out["patcher"] = cur
        if "installer" not in out and INSTALLER_EXE in low_names:
            out["installer"] = cur
    return out


def patcher_files(patcher_dir: str) -> list:
    """[(source path, game-relative destination)] for the patcher."""
    out = []
    for cur, _dirs, names in os.walk(patcher_dir):
        rel_dir = os.path.relpath(cur, patcher_dir).replace(os.sep, "/")
        parts = [] if rel_dir == "." else rel_dir.split("/")
        top = parts[0].lower() if parts else ""
        for n in names:
            if top == "xv2patcher" or (top == "bin" and len(parts) == 1
                                       and n.lower() in ("xinput1_3.dll", "dinput8.dll")):
                out.append((os.path.join(cur, n), "/".join([*parts, n])))
    return out


def installer_files(installer_dir: str) -> list:
    """[(source path, game-relative destination)] for xv2ins: the exe,
    the libraries beside it, and its folders (Internal, Qt plugins).
    The patcher's folders and eterniti's other tools stay out."""
    out = []
    for cur, dirs, names in os.walk(installer_dir):
        rel_dir = os.path.relpath(cur, installer_dir).replace(os.sep, "/")
        parts = [] if rel_dir == "." else rel_dir.split("/")
        if parts and parts[0].lower() in ("bin", "xv2patcher", "data", "cpk"):
            continue
        for n in names:
            low = n.lower()
            if not parts and not (low == INSTALLER_EXE or low.endswith((".dll", ".qm"))):
                continue
            out.append((os.path.join(cur, n), "/".join([*parts, n])))
    return out


def looks_like_archive(blob: bytes) -> bool:
    return blob[:4] == b"PK\x03\x04" or blob[:6] == b"7z\xbc\xaf\x27\x1c" or blob[:4] == b"Rar!"


_HREF = re.compile(r"""(?:href|data-href|data-url|data-download|action)\s*=\s*["']([^"']+)["']""", re.I)


def download_links(html: str, base: str) -> list:
    """Links on the Eternity Tools page that may lead to the download,
    most likely first."""
    from urllib.parse import urljoin
    seen, out = set(), []
    for m in _HREF.finditer(html or ""):
        url = urljoin(base, m.group(1).replace("&amp;", "&"))
        low = url.lower()
        if not low.startswith("http") or url in seen:
            continue
        score = 0
        if "download" in low:
            score += 2
        if low.split("?")[0].endswith(_ARCHIVE_EXTS):
            score += 3
        if "eternity" in low or "xenoverse" in low:
            score += 1
        if "mega.nz" in low or "patreon" in low or "github" in low or "discord" in low:
            score = 0
        if score >= 2:
            seen.add(url)
            out.append((score, len(out), url))
    return [u for _s, _i, u in sorted(out, key=lambda t: (-t[0], t[1]))]


def patcher_ini(text: str) -> str:
    """xv2patcher.ini with loose files and character mods switched on
    (what xv2ins sets on its first run), everything else kept."""
    want = {"loose_files": "true", "unlock_chara_mods": "true"}
    lines = (text or "").splitlines()
    out, section, done = [], "", set()
    patches_at = None
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if section == "patches":
                for k, v in want.items():
                    if k not in done:
                        out.append(f"{k} = {v}")
                        done.add(k)
            section = s[1:-1].strip().lower()
            if section == "patches":
                patches_at = len(out)
            out.append(line)
            continue
        key = s.split("=", 1)[0].strip().lower() if "=" in s and not s.startswith(";") else ""
        if section == "patches" and key in want:
            out.append(f"{key} = {want[key]}")
            done.add(key)
            continue
        out.append(line)
    if section == "patches":
        for k, v in want.items():
            if k not in done:
                out.append(f"{k} = {v}")
                done.add(k)
    if patches_at is None:
        out += ["", "[Patches]", *(f"{k} = {v}" for k, v in want.items())]
    return "\n".join(out) + "\n"


def installer_ini(text: str, game_dir: str) -> str:
    """xv2ins.ini (in %APPDATA%\\XV2INS) pointing at the game and with the
    language question answered (opted out, the safe choice), so the first
    run asks nothing. Other settings kept."""
    game_dir = game_dir.replace("\\", "/").rstrip("/")
    sections, order = {}, []
    cur = ""
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1].strip()
            if cur not in sections:
                sections[cur] = []
                order.append(cur)
            continue
        sections.setdefault(cur, [])
        if cur not in order:
            order.append(cur)
        sections[cur].append(line)

    def put(section, key, value, only_if_missing=False):
        lines = sections.setdefault(section, [])
        if section not in order:
            order.append(section)
        for i, line in enumerate(lines):
            if "=" in line and line.split("=", 1)[0].strip().lower() == key.lower():
                if not only_if_missing:
                    lines[i] = f"{key} = {value}"
                return
        lines.append(f"{key} = {value}")

    put("General", "game_directory", game_dir)
    put("General", "global_lang", "-1", only_if_missing=True)
    put("Installer", "language_asked", "true", only_if_missing=True)
    out = []
    for name in order:
        if name:
            out.append(f"[{name}]")
        out += [line for line in sections[name] if line.strip()]
        out.append("")
    return "\n".join(out)


# ---- x2m mods ---------------------------------------------------------------------

def x2m_info(path: str) -> dict:
    """{"name", "guid"} from an .x2m's x2m.xml ("" when unreadable)."""
    try:
        with zipfile.ZipFile(path) as z:
            member = next((n for n in z.namelist() if n.lower() == "x2m.xml"), None)
            text = z.read(member).decode("utf-8", "replace") if member else ""
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError):
        text = ""

    def tag(name):
        m = re.search(r"<" + name + r"\s+value\s*=\s*\"([^\"]*)\"", text, re.I)
        return m.group(1).strip() if m else ""

    return {"name": tag("MOD_NAME"), "guid": tag("MOD_GUID").lower()}


def installed_guids(install_data_names: list) -> set:
    """GUIDs xv2ins has on record, from the file names in data/InstallData."""
    out = set()
    rx = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
    for n in install_data_names or []:
        m = rx.search(n)
        if m:
            out.add(m.group(0).lower())
    return out


def plan_x2m(present: dict, applied: dict) -> tuple:
    """What xv2ins has to do.

    present: {x2m path: fingerprint} for the enabled .x2m files now.
    applied: {x2m path: {"fp", "name", "guid"}} installed by an earlier run.
    Returns (to install: [paths], gone: [applied entries no longer wanted])."""
    install = [p for p, fp in sorted(present.items())
               if (applied.get(p) or {}).get("fp") != fp]
    gone = [{"path": p, **v} for p, v in sorted(applied.items()) if p not in present]
    return install, gone


def installer_args(paths: list) -> list:
    """xv2ins arguments. One file means a confirmation question and a
    question per choice; two or more means one "silent mode?" question
    whose default is Yes. So a single mod is passed twice: the second
    pass is a silent reinstall of the same mod."""
    if len(paths) == 1:
        return [paths[0], paths[0]]
    return list(paths)


def auto_answer(title: str) -> bool:
    return bool(_AUTO_TITLES.match(title or ""))


def patcher_version(dll: bytes) -> float:
    """The "XV2PATCHER VERSION x.y" string inside the patcher dll, or -1."""
    m = re.search(rb"XV2PATCHER VERSION (\d+(?:\.\d+)?)", dll or b"")
    try:
        return float(m.group(1)) if m else -1.0
    except ValueError:
        return -1.0
