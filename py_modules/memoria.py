"""FINAL FANTASY IX (Steam) through Memoria (Albeoris/Memoria, MIT).

* Step 1: Memoria.Patcher.exe from the project's GitHub releases, run as
  `Memoria.Patcher.exe "<game folder>"`; it patches the game's managed
  assemblies and writes Memoria.ini beside FF9_Launcher.exe. A Steam
  update or file check undoes the patch, so it is run again then.
* Mods are folders in the game folder (ModDescription.xml and/or
  StreamingAssets/, FF9_Data/ inside). A folder loads only when its name is
  in Memoria.ini's [Mod] FolderNames; the first one listed wins.

Pure helpers here; downloads and running the patcher live in main.py.
"""

from __future__ import annotations

import re

DOMAIN = "finalfantasy9"
PATCHER = {"name": "Memoria", "repo": "Albeoris/Memoria", "tag": r".",
           "asset64": r"^Memoria\.Patcher\.exe$", "asset32": r"^Memoria\.Patcher\.exe$",
           "prerelease": False}
PATCHED_DLL = "x64/FF9_Data/Managed/Assembly-CSharp.dll"
_MARKERS = ("streamingassets", "ff9_data")


def apply_ff9_profile(game: dict) -> bool:
    if game.get("nexusDomain") != DOMAIN:
        return False
    game["engine"] = "memoria"
    game["processName"] = "x64/FF9.exe"
    game["modsSubdir"] = "Mods"
    game["toolApply"] = "memoria"
    for k in ("flatModExtensions", "mergeInto", "mergeBase", "extraFrameworks"):
        game.pop(k, None)
    game["framework"] = {
        "name": "Memoria",
        "nexusModId": 0,
        "detectFile": "Memoria.ini",
        "url": "https://github.com/Albeoris/Memoria",
        "installKind": "memoria",
        "installSubdir": "",
        "warning": (
            "Final Fantasy IX's mods run through Memoria, a patch to the game's code. Step 1 "
            "downloads it from its GitHub releases and runs its patcher; after a game update "
            "or a file check the plugin runs it again. Each mod is a folder in the game "
            "folder, and the plugin keeps Memoria's list of active mods in step."),
    }
    game["underConstruction"] = (
        "Experimental generic support for Final Fantasy IX through Memoria. Mods installed "
        "later take priority over earlier ones where they change the same things.")
    return True


def mod_folders(rel_files: list) -> list:
    """Folders of an archive that are Memoria mods: the ones holding a
    ModDescription.xml, else the ones with StreamingAssets/ or FF9_Data/
    directly inside. "" means the archive's top level is the mod."""
    files = [f.replace("\\", "/").strip("/") for f in rel_files or [] if f]
    described = sorted({f.rsplit("/", 1)[0] if "/" in f else "" for f in files
                        if f.split("/")[-1].lower() == "moddescription.xml"})
    if described:
        # Only the outermost: a mod's own option folders hold no second one
        # that should load by itself.
        return [d for d in described
                if not any(o != d and (o == "" or d.startswith(o + "/")) for o in described)]
    found = set()
    for f in files:
        parts = f.split("/")
        for i, p in enumerate(parts[:-1]):
            if p.lower() in _MARKERS:
                found.add("/".join(parts[:i]))
                break
    return sorted(d for d in found if not any(o != d and (o == "" or d.startswith(o + "/")) for o in found))


def folder_name(path: str, fallback: str) -> str:
    name = (path.split("/")[-1] if path else "") or fallback
    return re.sub(r'[<>:"/\\|?*]+', "_", name).strip(" .") or "Mod"


def plan(rel_files: list, fallback: str) -> list:
    """[(archive path, game-relative destination)]: each mod folder of the
    archive into the game folder under its own name."""
    files = [f.replace("\\", "/").strip("/") for f in rel_files or [] if f]
    out = []
    for d in mod_folders(files):
        name = folder_name(d, fallback)
        pre = d + "/" if d else ""
        for f in files:
            if f.startswith(pre):
                out.append((f, f"{name}/{f[len(pre):]}"))
    return out


def set_folder_names(ini_text: str, ours_on: list, ours_all: set) -> str:
    """Memoria.ini with [Mod] FolderNames = our switched-on folders (newest
    first, so later installs win), then any the user listed themselves."""
    lines = (ini_text or "").splitlines()
    section, done, out = "", False, []
    ours_low = {o.lower() for o in ours_all}
    for line in lines:
        s = line.strip()
        m = re.match(r"^\[(.+)\]$", s)
        if m:
            if section == "mod" and not done:
                out.append(_folder_line(ours_on, []))
                done = True
            section = m.group(1).strip().lower()
            out.append(line)
            continue
        if section == "mod" and re.match(r"(?i)^foldernames\s*=", s):
            theirs = [n for n in _parse_list(s.split("=", 1)[1]) if n.lower() not in ours_low]
            out.append(_folder_line(ours_on, theirs))
            done = True
            continue
        out.append(line)
    if not done:
        if section != "mod":
            out += ["", "[Mod]"] if out else ["[Mod]"]
        out.append(_folder_line(ours_on, []))
    return "\n".join(out) + "\n"


def _parse_list(value: str) -> list:
    return [m.group(1) for m in re.finditer(r'"([^"]*)"', value)] or \
        [v.strip() for v in value.split(",") if v.strip()]


def _folder_line(ours: list, theirs: list) -> str:
    names = list(dict.fromkeys(list(ours) + list(theirs)))
    return "FolderNames = " + ", ".join(f'"{n}"' for n in names)


def patch_ok(output: str) -> bool:
    low = (output or "").lower()
    return "could only complete" not in low and "unexpected error" not in low and \
        "failed to get a game location" not in low
