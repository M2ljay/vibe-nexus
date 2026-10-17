"""Experimental "any game" support: pure helpers, no I/O beyond the filesystem.

The curated games in src/games.ts carry hand-tuned install rules. This module
lets the plugin offer a generic tier for every other Steam game:

* match the running game to a Nexus Mods game domain by name, and
* look at the installed files to guess where drop-in mods belong
  (Unreal Content/Paks/~mods, BepInEx/plugins, MelonLoader Mods, an existing
  Mods folder), so the normal folder-mode installer - with its install
  records, enable/disable and uninstall - can place them.

Everything here is a guess and is labelled as one in the UI. Nothing in this
module writes to a game folder.
"""

from __future__ import annotations

import difflib
import os
import re

# Words that differ between a Steam store name and a Nexus game name without
# changing which game it is.
_EDITION_WORDS = (
    "definitive edition", "game of the year edition", "goty edition",
    "enhanced edition", "complete edition", "deluxe edition",
    "anniversary edition", "special edition", "ultimate edition",
    "remastered", "director's cut", "directors cut", "edition",
)

_SKIP_DIRS = {
    "engine", "__installer", "_commonredist", "commonredist", "redist",
    "redistributables", "directx", "vcredist", "support", "_redist",
    "easyanticheat", "battleye", "launcher", "crashreportclient",
}

_EXE_SKIP = re.compile(
    r"(unins|setup|crash|report|launcher|redist|vc_?redist|dxsetup|ue4prereq|"
    r"uninstall|helper|eac|battleye|cefprocess|handler|update)", re.I)


def normalize(name: str) -> str:
    """Lower-case alphanumerics only; '&' becomes 'and', marks are dropped."""
    s = (name or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[™®©]", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def _strip_editions(name: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"[™®©]", "", s)
    s = re.sub(r"\s*[-:–—]\s*", " ", s)
    for w in _EDITION_WORDS:
        s = re.sub(r"\b" + re.escape(w) + r"\b", " ", s)
    return normalize(s)


def _game_fields(g: dict) -> tuple:
    """(name, domain, mod_count) from a v1 games.json or data-dump entry."""
    name = str(g.get("name") or "")
    domain = str(g.get("domain_name") or g.get("domainName") or "")
    mods = g.get("mods")
    if not isinstance(mods, int):
        mods = g.get("file_count") or g.get("modCount") or 0
    try:
        mods = int(mods)
    except (TypeError, ValueError):
        mods = 0
    return name, domain, mods


def match_games(games: list, display_name: str, limit: int = 8) -> dict:
    """Find the Nexus game for a Steam name.

    Returns {"exact": {...} | None, "candidates": [...]}, each entry
    {"domain", "name", "mods"}. "exact" is set only when the normalized names
    agree (with or without edition words) - anything looser is offered as a
    choice, never applied silently.
    """
    target = normalize(display_name)
    target_bare = _strip_editions(display_name)
    exact = None
    scored = []
    for g in games or []:
        if not isinstance(g, dict):
            continue
        name, domain, mods = _game_fields(g)
        if not name or not re.fullmatch(r"[a-z0-9_-]+", domain):
            continue
        n = normalize(name)
        entry = {"domain": domain, "name": name, "mods": mods}
        if n and (n == target or _strip_editions(name) == target_bare
                  or domain == target):
            if exact is None or mods > exact["mods"]:
                exact = entry
            continue
        ratio = difflib.SequenceMatcher(None, target_bare, _strip_editions(name)).ratio()
        if target_bare and n and (target_bare in n or n in target_bare):
            ratio = max(ratio, 0.75)
        if ratio >= 0.5:
            scored.append((ratio, mods, entry))
    scored.sort(key=lambda t: (-round(t[0], 2), -t[1]))
    candidates = [e for _r, _m, e in scored[:limit]]
    return {"exact": exact, "candidates": candidates}


def guess_domains(display_name: str) -> list:
    """Likely Nexus domain names for a Steam name, best first.

    Used only when no games list can be fetched; each guess is verified
    against the API before it is offered.
    """
    out = []
    for cand in (normalize(display_name), _strip_editions(display_name)):
        if cand and cand not in out:
            out.append(cand)
    # "Marvel's Midnight Suns" -> "marvelsmidnightsuns" and "midnightsuns"
    words = re.findall(r"[a-z0-9]+", (display_name or "").lower().replace("'", ""))
    if len(words) > 1:
        tail = "".join(words[1:])
        if tail not in out:
            out.append(tail)
    return out[:4]


def read_appmanifest(path: str) -> dict:
    """installdir and name from a Steam appmanifest_<id>.acf."""
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'\s*"(installdir|name)"\s+"(.*)"\s*$', line)
                if m and m.group(1) not in out:
                    out[m.group(1)] = m.group(2).replace("\\\\", "\\")
    except OSError:
        return {}
    return out


def _walk_dirs(root: str, max_depth: int):
    """(rel_dir, abs_dir, filenames) breadth-limited, skipping redist trees."""
    root = os.path.normpath(root)
    base_depth = root.count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath.count(os.sep) - base_depth
        dirnames[:] = [
            d for d in dirnames
            if d.lower() not in _SKIP_DIRS and not d.startswith(".")
        ] if depth < max_depth else []
        rel = os.path.relpath(dirpath, root)
        yield ("" if rel == "." else rel.replace(os.sep, "/")), dirpath, filenames


def _dir_bytes(path: str, names: list, exts: tuple) -> int:
    total = 0
    for n in names:
        if n.lower().endswith(exts):
            try:
                total += os.path.getsize(os.path.join(path, n))
            except OSError:
                pass
    return total


def _find_child(path: str, name: str) -> str:
    """Case-insensitive child lookup; returns the real name or ''."""
    try:
        for n in os.listdir(path):
            if n.lower() == name.lower():
                return n
    except OSError:
        pass
    return ""


def _guess_exe(install_path: str, rel_dirs: list) -> str:
    """The game's main exe relative to the install dir (largest plausible)."""
    best = ("", -1)
    for rel in rel_dirs:
        d = os.path.join(install_path, *rel.split("/")) if rel else install_path
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if not n.lower().endswith(".exe") or _EXE_SKIP.search(n):
                continue
            try:
                size = os.path.getsize(os.path.join(d, n))
            except OSError:
                continue
            if n.lower().endswith("-win64-shipping.exe"):
                size += 1 << 40  # Unreal's real binary always wins
            if size > best[1]:
                best = ((rel + "/" + n) if rel else n, size)
    return best[0]


def inspect_install(install_path: str) -> dict:
    """Guess the engine and the drop-in mods folder for an installed game.

    Returns {"engine", "modsSubdir", "processName", "note", and optionally
    "ue4ss", "flatModExtensions"}. modsSubdir is relative to install_path
    with forward slashes.
    """
    if not os.path.isdir(install_path):
        return {"engine": "missing", "modsSubdir": "", "processName": "",
                "note": "The game folder was not found."}

    # Unreal: the game's own Content/Paks (the one holding the most pak data).
    best_paks = ("", 0)
    unity_data = ""
    for rel, absdir, files in _walk_dirs(install_path, 4):
        parts = rel.split("/") if rel else []
        if len(parts) >= 2 and parts[-1].lower() == "paks" and parts[-2].lower() == "content":
            size = _dir_bytes(absdir, files, (".pak", ".utoc", ".ucas"))
            if size > best_paks[1]:
                best_paks = (rel, size)
        if len(parts) == 1 and parts[0].lower().endswith("_data") and (
            "globalgamemanagers" in [f.lower() for f in files]
            or "data.unity3d" in [f.lower() for f in files]
        ):
            unity_data = parts[0]

    if best_paks[0]:
        paks = best_paks[0]
        project = paks.rsplit("/", 2)[0]  # the folder holding Content/
        exe = _guess_exe(install_path, [project + "/Binaries/Win64", ""])
        out = {
            "engine": "unreal",
            "modsSubdir": paks + "/~mods",
            "processName": exe,
            "note": (
                "Unreal Engine game: .pak mods go in "
                + paks.replace("/", "\\") + "\\~mods. Mods that need UE4SS, "
                "or replace files outside the paks folder, need setting up "
                "by hand."
            ),
        }
        win64 = os.path.join(install_path, *project.split("/"), "Binaries", "Win64")
        ue4ss = ""
        for cand in ("ue4ss/Mods", "Mods"):
            p = os.path.join(win64, *cand.split("/"))
            if os.path.isdir(p) and (
                os.path.exists(os.path.join(win64, "UE4SS.dll"))
                or os.path.exists(os.path.join(win64, "ue4ss", "UE4SS.dll"))
            ):
                ue4ss = project + "/Binaries/Win64/" + cand
                break
        if ue4ss:
            out["ue4ss"] = {
                "modsSubdir": ue4ss,
                "logicModsSubdir": paks + "/LogicMods",
            }
            out["note"] = out["note"].replace(
                "Mods that need UE4SS, or replace", "UE4SS is installed, so "
                "script mods are routed to it too. Mods that replace")
        return out

    bepinex = _find_child(install_path, "BepInEx")
    melon = _find_child(install_path, "MelonLoader")
    exe = _guess_exe(install_path, [""])
    if bepinex:
        return {"engine": "unity-bepinex", "modsSubdir": bepinex + "/plugins",
                "processName": exe,
                "note": "BepInEx found: plugin mods go in BepInEx\\plugins."}
    if melon:
        mods = _find_child(install_path, "Mods") or "Mods"
        return {"engine": "unity-melonloader", "modsSubdir": mods,
                "processName": exe, "flatModExtensions": [".dll"],
                "note": "MelonLoader found: mod .dll files go flat into Mods."}
    existing = _find_child(install_path, "Mods")
    if unity_data:
        return {
            "engine": "unity",
            "modsSubdir": "BepInEx/plugins",
            "processName": exe,
            "note": (
                "Unity game without a mod loader. Most Unity mods need "
                "BepInEx: install the game's BepInEx pack from its Nexus "
                "page first (or by hand), then plugin mods land in "
                "BepInEx\\plugins."
            ),
        }
    if existing:
        return {"engine": "generic", "modsSubdir": existing, "processName": exe,
                "note": "The game has a " + existing + " folder; mods are "
                        "placed there, one folder each."}
    return {
        "engine": "unknown",
        "modsSubdir": "Mods",
        "processName": exe,
        "note": (
            "Engine not recognised. Mods are unpacked to a Mods folder in "
            "the game directory, one folder each - check each mod's "
            "instructions and move files by hand where needed."
        ),
    }


def build_game(app_id: int, display_name: str, install_dir: str,
               domain: str, nexus_name: str, inspection: dict) -> dict:
    """A SupportedGame-shaped dict for the frontend (see src/games.ts)."""
    game = {
        "appId": int(app_id),
        "displayName": display_name or nexus_name or domain,
        "nexusDomain": domain,
        "installDirName": install_dir,
        "modsSubdir": inspection.get("modsSubdir") or "Mods",
        "moddedSaveWarning": False,
        # Relative to the install dir, like the curated "bin/bg3".
        "processName": inspection.get("processName") or "",
        "installMode": "folder",
        "experimental": True,
        "engine": inspection.get("engine") or "unknown",
        "underConstruction": "Experimental generic support. "
        + (inspection.get("note") or ""),
    }
    if inspection.get("ue4ss"):
        game["ue4ss"] = inspection["ue4ss"]
    if inspection.get("flatModExtensions"):
        game["flatModExtensions"] = inspection["flatModExtensions"]
    return game


# ---- Game-wide requirements ("frameworks") ----------------------------------
# Some games load no mods at all until a loader or bypass is installed (Marvel
# Rivals: a signature bypass dll beside the game exe). Such a requirement is
# found from the data: the mod most of the game's top mods list as required,
# whose archive holds program files rather than ordinary mod content.

_LOADER_EXTS = (".dll", ".asi")


def pick_common_requirement(nodes: list, domain: str, min_share: float = 0.2,
                            min_count: int = 3):
    """The requirement shared by enough of the given legacyMods nodes.

    nodes are {"modId", "modRequirements": {"nexusRequirements": {"nodes":
    [{"modId", "modName", "url"}]}}}. Requirements on another game's page
    are ignored. Returns {"modId", "modName", "count"} or None.
    """
    counts = {}
    names = {}
    own = {int(n.get("modId") or 0) for n in nodes or [] if isinstance(n, dict)}
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        reqs = (((n.get("modRequirements") or {}).get("nexusRequirements") or {})
                .get("nodes") or [])
        seen = set()
        for r in reqs:
            try:
                rid = int(r.get("modId") or 0)
            except (TypeError, ValueError):
                continue
            url = str(r.get("url") or "").lower()
            if not rid or rid in seen:
                continue
            if url and f"/{domain.lower()}/mods/" not in url:
                continue
            seen.add(rid)
            counts[rid] = counts.get(rid, 0) + 1
            names.setdefault(rid, str(r.get("modName") or f"mod {rid}"))
    if not counts:
        return None
    rid, count = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))
    total = max(len(own), 1)
    if count < min_count or count / total < min_share:
        return None
    return {"modId": rid, "modName": names[rid], "count": count}


def framework_layout(paths: list, exe_dir: str):
    """Where a requirement archive installs, from its file listing.

    Returns {"installSubdir", "detectFile"} (both relative to the game root,
    forward slashes) when the archive carries a loader (.dll/.asi), else None
    - an archive of ordinary mod files is just a mod, installed normally.

    A single wrapper folder is ignored (as the copyRoot installer flattens
    it). An archive laid out from the game root (its paths start with the
    exe folder's first component) installs at the root; anything else goes
    beside the game exe.
    """
    rels = [p.replace("\\", "/").strip("/") for p in paths or [] if p]
    rels = [p for p in rels if p]
    if not rels:
        return None
    tops = {p.split("/")[0] for p in rels}
    exe_parts = [p for p in (exe_dir or "").split("/") if p]
    if (len(tops) == 1 and all("/" in p for p in rels)
            and (not exe_parts or next(iter(tops)).lower() != exe_parts[0].lower())):
        wrapper = next(iter(tops))
        rels = [p[len(wrapper) + 1:] for p in rels]
    loaders = [p for p in rels if p.lower().endswith(_LOADER_EXTS)]
    if not loaders:
        return None
    if exe_parts and any(p.split("/")[0].lower() == exe_parts[0].lower() for p in rels):
        detect = min(loaders, key=lambda p: (p.count("/"), p.lower()))
        return {"installSubdir": "", "detectFile": detect}
    detect = min(loaders, key=lambda p: (p.count("/"), p.lower()))
    sub = "/".join(exe_parts)
    return {"installSubdir": sub, "detectFile": (sub + "/" + detect) if sub else detect}


def exe_dir_of(process_name: str) -> str:
    parts = (process_name or "").replace("\\", "/").split("/")
    return "/".join(parts[:-1])
