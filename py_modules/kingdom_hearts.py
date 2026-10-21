"""KINGDOM HEARTS HD 1.5+2.5 ReMIX (Steam): one install, four Nexus games.

Mods are of two kinds:
* .kh1pcpatch / .compcpatch / .kh2pcpatch / .bbspcpatch - applied to the
  game's Image/en/*.pkg by KHPCPatchManager (AntonioDePau/KHPCPatchManager;
  it finds the Steam install itself, keeps the previous pkg in
  Image/en/backup). A patch can't be taken back out: Steam's "verify files"
  restores the pkgs and the remaining patches are applied again.
* .lua scripts - run by LuaBackend Hook (Sirius902/LuaBackend: DBGHELP.dll and
  LuaBackend.toml beside the game). Its toml lists script folders per game;
  ours is Mods/scripts/<game id> in the game folder (an absolute entry), as
  well as the usual Documents one.

Pure helpers here; downloads, copies and running the tools live in main.py.
"""

from __future__ import annotations

import os
import re

COLLECTION_APP = 2552430
GAMES = {
    "kingdomheartsfinalmix": {"id": "kh1", "exe": "KINGDOM HEARTS FINAL MIX.exe",
                              "patch": ".kh1pcpatch", "name": "Kingdom Hearts Final Mix"},
    "kingdomheartsrechainofmemories": {"id": "recom", "exe": "KINGDOM HEARTS Re_Chain of Memories.exe",
                                       "patch": ".compcpatch", "name": "Re:Chain of Memories"},
    "kingdomhearts2finalmix": {"id": "kh2", "exe": "KINGDOM HEARTS II FINAL MIX.exe",
                               "patch": ".kh2pcpatch", "name": "Kingdom Hearts II Final Mix"},
    "kingdomheartsbirthbysleepfinalmix": {"id": "bbs", "exe": "KINGDOM HEARTS Birth by Sleep FINAL MIX.exe",
                                          "patch": ".bbspcpatch", "name": "Birth by Sleep Final Mix"},
}
PATCH_EXTS = tuple(g["patch"] for g in GAMES.values())
PATCH_DIR = "Mods/patches"
SCRIPTS_DIR = "Mods/scripts"
TOOL_DIR = "KHPCPatchManager"
PATCHER = {"name": "KHPCPatchManager", "repo": "AntonioDePau/KHPCPatchManager",
           "tag": r".", "asset64": r"^KHPCPatchManager\.exe$", "asset32": r"^KHPCPatchManager\.exe$",
           "prerelease": False}
LUABACKEND = {"name": "LuaBackend Hook", "repo": "Sirius902/LuaBackend",
              "tag": r".", "asset64": r"^DBGHELP\.zip$", "asset32": r"^DBGHELP\.zip$",
              "prerelease": False}


def is_kh(game: dict) -> bool:
    return (game or {}).get("nexusDomain") in GAMES


def apply_kh_profile(game: dict) -> bool:
    info = GAMES.get(game.get("nexusDomain") or "")
    if not info:
        return False
    game["engine"] = "kh"
    game["processName"] = info["exe"]
    game["modsSubdir"] = "Mods"
    game["toolApply"] = "khpatch"
    game["khGame"] = info["id"]
    game["domainChoices"] = [{"domain": d, "name": g["name"]} for d, g in GAMES.items()]
    game.pop("flatModExtensions", None)
    game.pop("mergeInto", None)
    game.pop("mergeBase", None)
    game.pop("extraFrameworks", None)
    game["framework"] = {
        "name": "KHPCPatchManager + LuaBackend",
        "nexusModId": 0,
        "detectFile": TOOL_DIR + "/KHPCPatchManager.exe",
        "url": "https://github.com/AntonioDePau/KHPCPatchManager",
        "installKind": "khTools",
        "installSubdir": "",
        "warning": (
            "Kingdom Hearts mods are patches KHPCPatchManager writes into the game's data "
            "(.kh1pcpatch and the like) and Lua scripts LuaBackend Hook runs. Step 1 gets both "
            "from their GitHub releases. Patches can't be taken back out one by one: to remove "
            "one, verify the game's files in Steam, then press Apply to put the rest back."),
    }
    game["underConstruction"] = (
        f"Experimental generic support for {info['name']} (switch the collection's game below). "
        "Patches are applied by KHPCPatchManager after each install; Lua scripts run through "
        "LuaBackend (F2 in game opens its console).")
    return True


def kh_plan(rel_files: list, game_id: str) -> list:
    """[(archive path, game-relative destination)] for a Kingdom Hearts mod:
    pcpatch files into Mods/patches, Lua scripts (and the files beside them)
    into Mods/scripts/<game id>."""
    files = [f.replace("\\", "/") for f in rel_files or [] if f and not f.endswith("/")]
    out = []
    for f in files:
        if f.lower().endswith(PATCH_EXTS):
            out.append((f, f"{PATCH_DIR}/{f.split('/')[-1]}"))
    luas = [f for f in files if f.lower().endswith(".lua")]
    if luas:
        dirs = [f.rsplit("/", 1)[0] if "/" in f else "" for f in luas]
        base = os.path.commonpath(dirs).replace(os.sep, "/") if all(dirs) else ""
        # A script with its own folder of data (KHPCStatInventoryModifier/
        # Main.lua + input.txt) keeps that folder; loose scripts go flat.
        keep_folder = len(set(dirs)) == 1 and base and any(
            not f.lower().endswith((".lua", ".txt", ".md", ".png", ".jpg")) or f.lower().endswith("input.txt")
            for f in files if f.startswith(base + "/") and not f.lower().endswith(PATCH_EXTS))
        pre = (base.rsplit("/", 1)[0] + "/" if "/" in base else "") if keep_folder else (base + "/" if base else "")
        for f in files:
            low = f.lower()
            if not f.startswith(pre) or low.endswith(PATCH_EXTS):
                continue
            if low.endswith((".png", ".jpg", ".jpeg", ".url", ".pdf")) or low.split("/")[-1].startswith("readme"):
                continue
            rest = f[len(pre):]
            out.append((f, f"{SCRIPTS_DIR}/{game_id}/{rest}"))
    return out


def patch_kind(name: str) -> str:
    low = name.lower()
    for g in GAMES.values():
        if low.endswith(g["patch"]):
            return g["patch"]
    return ""


def patcher_finished(line: str) -> bool:
    """KHPCPatchManager's last line for a run, good or bad."""
    s = (line or "").strip()
    return s == "Done!" or s.startswith(("Could not find any folder", "There was an error", "Error:")) \
        or s.startswith("You have selected different types of patches")


def patcher_succeeded(out: str) -> bool:
    lines = [ln.strip() for ln in (out or "").splitlines()]
    return "Done!" in lines and not any(
        ln.startswith(("Could not find any folder", "There was an error", "Error:"))
        or (ln.startswith("System.") and "Exception" in ln.split(":")[0]) for ln in lines)


def luabackend_toml(text: str, game_root: str) -> str:
    """LuaBackend.toml for the Steam version (game_docs under My Games) with
    the plugin's Mods/scripts/<id> folder added to each game's scripts."""
    out, section = [], ""
    for line in (text or "").splitlines():
        s = line.strip()
        m = re.match(r"^\[(\w+)\]$", s)
        if m:
            section = m.group(1)
            out.append(line)
            continue
        if s.startswith("game_docs") and "My Games/" not in s:
            line = re.sub(r'"(KINGDOM HEARTS[^"]*)"', r'"My Games/\1"', line)
        if s.startswith("scripts") and section:
            ours = (game_root.rstrip("\\/") + "\\" + SCRIPTS_DIR.replace("/", "\\") + "\\" + section).replace("\\", "\\\\")
            if ours not in s:
                line = line.rstrip()
                if line.endswith("]"):
                    line = line[:-1].rstrip()
                    line += f', {{ path = "{ours}", relative = false }}]'
        out.append(line)
    return "\n".join(out) + "\n"


def plan_patches(present: list, applied: list, reset: bool) -> tuple:
    """(patches to apply, removed ones) - after a reset (pkgs restored by
    Steam) everything present is applied again."""
    if reset:
        return sorted(present), []
    return sorted(p for p in present if p not in applied), sorted(p for p in applied if p not in present)
