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
    # Capcom's Steam names carry the Japanese title after two spaces
    # ("RESIDENT EVIL 2  BIOHAZARD RE2"): the first part is the game.
    if "  " in (display_name or "").strip():
        display_name = display_name.strip().split("  ")[0]
    target = normalize(display_name)
    target_bare = _strip_editions(display_name)
    exact = None
    year_exact = None
    scored = []
    for g in games or []:
        if not isinstance(g, dict):
            continue
        name, domain, mods = _game_fields(g)
        if not name or not re.fullmatch(r"[a-z0-9_-]+", domain):
            continue
        n = normalize(name)
        entry = {"domain": domain, "name": name, "mods": mods}
        # Nexus tells remakes apart by year: "Resident Evil 2 (2019)".
        n_noyear = normalize(re.sub(r"\s*\((19|20)\d\d\)\s*$", "", name))
        if n and (n == target or _strip_editions(name) == target_bare
                  or domain == target):
            if exact is None or mods > exact["mods"]:
                exact = entry
            continue
        if n_noyear != n and n_noyear == target:
            # Weaker than a true exact: used only when there is none.
            if year_exact is None or mods > year_exact["mods"]:
                year_exact = entry
            continue
        ratio = difflib.SequenceMatcher(None, target_bare, _strip_editions(name)).ratio()
        if target_bare and n and (target_bare in n or n in target_bare):
            ratio = max(ratio, 0.75)
        if ratio >= 0.5:
            scored.append((ratio, mods, entry))
    scored.sort(key=lambda t: (-round(t[0], 2), -t[1]))
    candidates = [e for _r, _m, e in scored[:limit]]
    return {"exact": exact or year_exact, "candidates": candidates}


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
                m = re.match(r'\s*"(installdir|name|StateFlags)"\s+"(.*)"\s*$', line)
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
                + paks.replace("/", "\\") + "\\~mods." 
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
            out["note"] += " UE4SS is installed, so script mods go to it too."
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
            "Engine not recognised. Mods without a game-folder layout are "
            "unpacked to a Mods folder in the game directory, one folder "
            "each - check each mod's instructions."
        ),
    }


ROOT_LAYOUT_NOTE = (
    "Mods laid out for the game folder (a dll beside the exe, a Content "
    "tree) are placed file by file; game files they replace are kept and "
    "put back when the mod is switched off or uninstalled."
)


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
        + (inspection.get("note") or "") + " " + ROOT_LAYOUT_NOTE,
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
    picks = common_requirements(counts, names, len(own), min_share, min_count)
    return picks[0] if picks else None


def common_requirements(counts: dict, names: dict, total: int,
                        min_share: float = 0.2, min_count: int = 3) -> list:
    """Every requirement over the threshold, most required first."""
    total = max(total, 1)
    out = [{"modId": rid, "modName": names[rid], "count": c}
           for rid, c in counts.items()
           if c >= min_count and c / total >= min_share]
    out.sort(key=lambda r: (-r["count"], r["modId"]))
    return out


def requirement_counts(nodes: list, domain: str) -> tuple:
    """(counts, names, total) of same-game requirements across nodes."""
    counts, names = {}, {}
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
            if not rid or rid in seen or (url and f"/{domain.lower()}/mods/" not in url):
                continue
            seen.add(rid)
            counts[rid] = counts.get(rid, 0) + 1
            names.setdefault(rid, str(r.get("modName") or f"mod {rid}"))
    return counts, names, len(own)


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
    # A program you run (an .exe tool such as a mod packer) is not a loader
    # the game picks up, unless it also ships a proxy dll or .asi plugin.
    has_hook = any(p.split("/")[-1].lower() in PROXY_DLLS or p.lower().endswith(".asi")
                   for p in rels)
    if any(p.lower().endswith(".exe") for p in rels) and not has_hook:
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


# ---- Mods laid out from the game folder -------------------------------------
# A drop-in mods folder covers most archives, but plenty ship files for other
# places: a proxy dll beside the exe, a Content/ tree, a BepInEx pack, file
# replacements. plan_root_install() maps such an archive onto the game folder
# when every file has an unambiguous destination, and declines otherwise, so
# the ordinary mods-folder install still handles everything it handled before.

# DLL names Windows games load from their own folder, which mod loaders and
# injectors use as their way in.
PROXY_DLLS = {
    "dsound.dll", "dinput8.dll", "winmm.dll", "version.dll", "winhttp.dll",
    "d3d9.dll", "d3d10.dll", "d3d11.dll", "d3d12.dll", "dxgi.dll",
    "xinput1_3.dll", "xinput1_4.dll", "xinput9_1_0.dll", "wininet.dll",
    "opengl32.dll", "bink2w64.dll", "binkw64.dll", "msimg32.dll",
    # UE4SS 3.x hooks in through dwmapi; old DirectX games through ddraw/d3d8.
    "dwmapi.dll", "ddraw.dll", "d3d8.dll", "dbghelp.dll", "iphlpapi.dll",
}
# Top-level names that mean "this archive is laid out from the game root".
ROOT_MARKERS = {"bepinex", "melonloader", "doorstop_config.ini", "winhttp.dll",
                "version.dll", ".doorstop_version"}
# Loose documentation that has no business in a game folder.
_DOC_EXTS = (".txt", ".md", ".url", ".jpg", ".jpeg", ".png", ".pdf", ".html",
             ".htm", ".rtf", ".webp", ".gif")


def index_game_dirs(install_path: str, max_depth: int = 4) -> dict:
    """lower-case directory name -> [game-relative paths], shallow first."""
    index = {}
    for rel, _abs, _files in _walk_dirs(install_path, max_depth):
        if not rel:
            continue
        index.setdefault(rel.split("/")[-1].lower(), []).append(rel)
    for paths in index.values():
        paths.sort(key=lambda p: (p.count("/"), p.lower()))
    return index


def _pick_dir(candidates: list, hints: list) -> str:
    """The one candidate a hint path runs through, else the only one."""
    hinted = [c for c in candidates
              if any(h.lower() == c.lower() or h.lower().startswith(c.lower() + "/")
                     for h in hints if h)]
    if not hinted:
        # A preferred root ("valve") picks the candidate living under it.
        hinted = [c for c in candidates
                  if any(c.lower().startswith(h.lower() + "/") for h in hints if h)]
    if len(hinted) == 1:
        return hinted[0]
    if len(candidates) == 1:
        return candidates[0]
    return ""


def index_game_files(install_path: str, mods_subdir: str = "", max_depth: int = 6,
                     cap: int = 200000) -> dict:
    """lower-case file name -> [game-relative paths], for replacement mods
    that ship a loose file named like one of the game's own. Installed mods
    (the mods folder and its -disabled twin) are not the game's files."""
    skip = mods_subdir.lower().rstrip("/") if mods_subdir else ""
    index, n = {}, 0
    for rel, _abs, files in _walk_dirs(install_path, max_depth):
        low = rel.lower()
        if skip and (low == skip or low.startswith(skip + "/") or low.startswith(skip + "-disabled")):
            continue
        for f in files:
            index.setdefault(f.lower(), []).append(f"{rel}/{f}" if rel else f)
            n += 1
            if n >= cap:
                return index
    return index


# Where a game's own content lives when the same folder name appears in
# several places (Half-Life's models/ exists under valve/ and every
# expansion): the base game's folder wins.
GAME_CONTENT_ROOT = {
    "halflife": "valve",
    "halflife2": "hl2",
    "halflifeblueshift": "valve",
    "counterstrike": "cstrike",
    "portal": "portal",
}

# Extensions too generic to say where a loose file belongs.
_GENERIC_EXTS = {".txt", ".ini", ".cfg", ".json", ".xml", ".dll", ".exe", ".png",
                 ".jpg", ".jpeg", ".bmp", ".dds", ".log", ".md", ".html", ".csv",
                 ".lua", ".bin", ".dat", ".url", ".pdf"}

# A folder holding one of these is a standalone mod that sits in the game
# root beside the base game's folder (GoldSrc liblist.gam, Source gameinfo.txt).
_STANDALONE_MARKERS = ("liblist.gam", "gameinfo.txt")


def _ext_homes(file_index: dict) -> dict:
    """extension -> set of game folders holding files of that extension."""
    homes = {}
    for name, paths in (file_index or {}).items():
        ext = os.path.splitext(name)[1]
        if not ext or ext in _GENERIC_EXTS:
            continue
        for p in paths:
            homes.setdefault(ext, set()).add(p.rsplit("/", 1)[0] if "/" in p else "")
    return homes


def plan_root_install(rel_files: list, root_entries: set, dir_index: dict,
                      mods_subdir: str, exe_dir: str, file_index: dict = None,
                      prefer: str = ""):
    """Map an archive's files onto the game folder, or return None.

    rel_files are the extracted archive's files (forward slashes). Returns
    [(src_rel, dst_rel)] with dst relative to the game root, or None when the
    archive should go through the mods-folder install instead: it has files
    with no clear destination, or it is laid out from the mods folder itself
    (the mods-folder install unwraps that already).
    """
    files = [f.replace("\\", "/").strip("/") for f in rel_files if f]
    files = [f for f in files if f and not f.lower().startswith(("__macosx/", "fomod/"))]
    if not files:
        return None
    roots = {e.lower() for e in root_entries}
    mods_parts = [p.lower() for p in (mods_subdir or "").split("/") if p]
    # The mods folder's own name ("~mods", "plugins") at the top of an
    # archive is the mods-folder install's job: it unwraps it.
    leaf = mods_parts[-1] if mods_parts else ""
    known = lambda name: (name in roots or name in ROOT_MARKERS  # noqa: E731
                          or (name in dir_index and name != leaf))

    # Standalone mod folders (a whole GoldSrc/Source mod) go to the root as-is.
    standalone = {f.split("/")[-2] for f in files
                  if f.count("/") >= 1 and f.split("/")[-1].lower() in _STANDALONE_MARKERS}
    if standalone:
        plan = []
        for f in files:
            parts = f.split("/")
            hit = next((i for i, p in enumerate(parts) if p in standalone), None)
            if hit is None:
                if "/" not in f and f.lower().endswith(_DOC_EXTS):
                    continue
                return None
            plan.append((f, "/".join(parts[hit:])))
        return plan or None

    # Peel wrapper folders that mean nothing to the game ("MyMod v1.2/").
    # Readmes and screenshots beside the wrapper do not stop the peel.
    is_doc = lambda f: "/" not in f and f.lower().endswith(_DOC_EXTS)  # noqa: E731
    prefix = ""
    for _ in range(3):
        body = [f for f in files if f.startswith(prefix) and not is_doc(f[len(prefix):])]
        tops = {f[len(prefix):].split("/")[0] for f in body}
        if len(tops) != 1 or not body:
            break
        top = next(iter(tops))
        if not all("/" in f[len(prefix):] for f in body) or known(top.lower()):
            break
        if top.lower() == leaf:
            break
        prefix += top + "/"
    rels = [(f, f[len(prefix):]) for f in files if f.startswith(prefix)]

    mods_path = "/".join(mods_parts)
    if mods_path and all(r.lower().startswith(mods_path + "/") for _s, r in rels):
        return None
    exe_hint = exe_dir or ""
    # A proxy dll or .asi at the top means the whole pack goes beside the exe
    # with its structure (ReShade: dxgi.dll + reshade-shaders/ + preset .ini).
    if any("/" not in r and (r.lower() in PROXY_DLLS or r.lower().endswith(".asi"))
           for _s, r in rels):
        return [(src, (exe_hint + "/" + rel) if exe_hint else rel)
                for src, rel in rels
                if not ("/" not in rel and rel.lower().endswith(_DOC_EXTS))] or None
    plan = []
    for src, rel in rels:
        parts = rel.split("/")
        top = parts[0].lower()
        if len(parts) == 1 and top.endswith(_DOC_EXTS):
            continue  # a readme beside the payload
        dst = None
        if top in roots or top in ROOT_MARKERS:
            dst = rel
        elif len(parts) > 1 and top in dir_index and top != leaf:
            base = _pick_dir(dir_index[top], [prefer, mods_subdir, exe_hint])
            if base:
                dst = base + "/" + "/".join(parts[1:])
        elif len(parts) == 1 and (top in PROXY_DLLS or top.endswith(".asi")):
            dst = (exe_hint + "/" + rel) if exe_hint else rel
        elif top == "plugins" and any(r.lower().endswith(".asi") for _s, r in rels):
            dst = (exe_hint + "/" + rel) if exe_hint else rel
        if dst is None and file_index:
            # A replacement: the game has exactly one file of this name.
            hits = file_index.get(parts[-1].lower()) or []
            if len(hits) == 1:
                dst = hits[0]
            elif len(parts) == 1:
                # A new file of a kind the game keeps in one folder only
                # (Dead Island's Data3.pak beside Data0-2.pak in DI/).
                homes = sorted(_ext_homes(file_index).get(os.path.splitext(top)[1], ()))
                if prefer and len(homes) > 1:
                    homes = [h for h in homes if h.lower().split("/")[0] == prefer] or homes
                if len(homes) == 1:
                    dst = (homes[0] + "/" + rel) if homes[0] else rel
        if dst is None:
            return None
        plan.append((src, dst))
    return plan or None



# ---- Games whose mods are applied by a tool ----------------------------------
# Insomniac's PC ports load no loose mod files: Overstrike (open source, GPL)
# packs .smpcmod/.suit/.stage/.modular files into the game's archives. It
# has a command line (create-profile, install-mods), so the plugin keeps a
# profile in step with what is installed and runs it - one press, no desktop.

PROFILE_VERSION = 5

OVERSTRIKE_EXTS = [".smpcmod", ".suit", ".stage", ".modular", ".script"]
OVERSTRIKE_DIR = "Overstrike"
OVERSTRIKE_LIBRARY = OVERSTRIKE_DIR + "/Mods Library"
OVERSTRIKE_PROFILE = "Nexus"

# domain -> Overstrike's mod id on that game's Nexus page (None: look for
# it among the requirements of the game's top mods).
TOOL_GAMES = {
    "marvelsspidermanremastered": 4199,
    "marvelsspiderman2": 1,
    "ratchetandclankriftapart": 1,
    "spidermanmilesmorales": None,
}


def apply_tool_profile(game: dict, overstrike_id) -> bool:
    """Turn a game into an Overstrike-managed one. Returns False when the
    game is not one of TOOL_GAMES or Overstrike's mod id is unknown."""
    if game.get("nexusDomain") not in TOOL_GAMES or not overstrike_id:
        return False
    game["engine"] = "insomniac"
    game["modsSubdir"] = OVERSTRIKE_LIBRARY
    game["flatModExtensions"] = list(OVERSTRIKE_EXTS)
    game["toolApply"] = "overstrike"
    game.pop("ue4ss", None)
    game["framework"] = {
        "name": "Overstrike",
        "nexusModId": int(overstrike_id),
        "detectFile": OVERSTRIKE_DIR + "/Overstrike.exe",
        "url": f"https://www.nexusmods.com/{game['nexusDomain']}/mods/{int(overstrike_id)}",
        "installKind": "copyRootTracked",
        "installSubdir": OVERSTRIKE_DIR,
        "warning": (
            "Overstrike is the mod manager this game's mods are made for. It "
            "needs Microsoft's .NET 7 Desktop Runtime. The plugin keeps its "
            "own Overstrike profile and applies your mods with it after every "
            "install or uninstall."
        ),
    }
    game["underConstruction"] = (
        "Experimental generic support. This game's mods are applied by "
        "Overstrike: Step 1 installs it, then each install or uninstall here "
        "re-applies your mods automatically (the game must be closed)."
    )
    return True


def overstrike_profile_mods(records: list, old_mods: list) -> list:
    """The "mods" list for Overstrike's profile JSON.

    records: [(install_seq, [library-relative file paths])] for installed
    mods, in any order. old_mods: the profile's current list, whose per-mod
    extras (suit settings) are kept. Every installed file is switched on, in
    install order - the order Overstrike applies them in.
    """
    extras = {}
    for m in old_mods or []:
        if isinstance(m, list) and m and isinstance(m[0], str) and len(m) > 2:
            extras[m[0].lower()] = m[2]
    out, seen = [], set()
    for _seq, files in sorted(records, key=lambda r: r[0] or 0):
        for f in files:
            path = f.replace("/", "\\")
            if path.lower() in seen:
                continue
            seen.add(path.lower())
            entry = [path, True]
            if path.lower() in extras:
                entry.append(extras[path.lower()])
            out.append(entry)
    return out



# ---- Bethesda games without a curated entry --------------------------------
# Their mods merge into Data/ and are switched on in plugins.txt, which the
# plugin's dataDir tier already does for Skyrim and Fallout. These need only
# where plugins.txt lives (under %LOCALAPPDATA%) and how it marks a plugin
# active: "starred" ('*Name.esp', Skyrim SE onwards) or "listed" (presence).
BETHESDA_GAMES = {
    "oblivion": ("Oblivion/plugins.txt", "listed"),
    "skyrim": ("Skyrim/plugins.txt", "listed"),
    "enderalspecialedition": ("Enderal Special Edition/plugins.txt", "starred"),
    "enderal": ("enderal/plugins.txt", "listed"),
    "fallout4vr": ("Fallout4VR/plugins.txt", "starred"),
    "skyrimspecialeditionvr": ("Skyrim VR/plugins.txt", "starred"),
}


# Saints Row 2: loose files (tables, textures, models) load from the game's
# mods folder once the community Juiced Patch is in (its loose.txt lists
# "mods", one folder deep). Packfiles replace the game's own in its root.
SR2_DOMAIN = "saintsrow2"
SR2_LOOSE_EXTS = [".xtbl", ".tbl", ".cvtf", ".lua", ".le_strings", "_pc"]
SR2_ROOT_FILES = (".vpp_pc", "shaders_pc")


def apply_sr2_profile(game: dict, framework: dict) -> bool:
    if game.get("nexusDomain") != SR2_DOMAIN:
        return False
    game["engine"] = "sr2"
    game["modsSubdir"] = "mods"
    game["flatModExtensions"] = list(SR2_LOOSE_EXTS)
    game.pop("mergeInto", None)
    game.pop("mergeBase", None)
    game["framework"] = framework
    game["underConstruction"] = (
        "Experimental generic support. Saints Row 2 mods are loose game files: "
        "they go flat into the game's mods folder, which the Juiced Patch "
        "(Step 1) makes the game read. Replacement packfiles (patch.vpp_pc) "
        "go beside the game, with its own kept aside. Mods with several "
        "versions inside ask which one to install. Save files and ReShade "
        "presets are not installed."
    )
    return True


def sr2_builder(paths) -> bool:
    """Overhauls like Gentlemen of the Row compile their own patch.vpp_pc
    with bundled tools (optional_mod_stuff -> MY_CUSTOM_PATCH): their files
    are build inputs, not files the game loads as they are."""
    low = [p.replace("\\", "/").lower() for p in paths or []]
    return any("/my_custom_patch/" in "/" + p or "optional_mod_stuff/" in p for p in low)


# Gentlemen of the Row on Juiced (saintsrowmods.com, "Installing GotR using
# Juiced v7.1.0 or later"): optional_mod_stuff/modified/* and the two
# preload tables into mods/GotR, the game's own patch.vpp_pc left alone,
# GotR's patch builder never run, gotr.txt in the root (skips the intro
# warning that crashes some games). Each optional mod gets its own folder
# under mods/GotR/Optional; switching one on lists its folder in
# loose.txt, above mods/GotR. Juiced keeps the FIRST copy of a file name it
# meets in loose.txt order, so listed options win over the base.
GOTR_DIR = "mods/GotR"
GOTR_OPT_DIR = GOTR_DIR + "/Optional"
GOTR_FLAG = "gotr.txt"


def gotr_base(rel_files: list) -> str:
    """The folder holding optional_mod_stuff/modified, or None."""
    for f in rel_files or []:
        low = f.replace("\\", "/").lower()
        i = low.find("optional_mod_stuff/modified/")
        if i >= 0:
            return f.replace("\\", "/")[:i]
    return None


def gotr_options(rel_files: list) -> list:
    """The optional mods GotR ships (folders under optional_mods)."""
    base = gotr_base(rel_files)
    if base is None:
        return []
    pre = (base + "optional_mod_stuff/optional_mods/").lower()
    out = set()
    for f in rel_files:
        f = f.replace("\\", "/")
        if f.lower().startswith(pre) and "/" in f[len(pre):]:
            out.add(f[:len(pre)] + f[len(pre):].split("/")[0])
    return sorted(out)


def gotr_option_name(option_dir: str) -> str:
    """The folder name an optional mod gets under mods/GotR/Optional."""
    name = option_dir.rstrip("/").split("/")[-1]
    return re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .") or "option"


def gotr_plan(rel_files: list) -> list:
    """[(archive path, game-relative destination)] for GotR's base; files
    land flat (loose.txt is read one level deep). Preloads win over
    modified/."""
    base = gotr_base(rel_files)
    if base is None:
        return []
    files = [f.replace("\\", "/") for f in rel_files if f and not f.endswith("/")]
    low = {f.lower(): f for f in files}
    mod_pre = (base + "optional_mod_stuff/modified/").lower()
    picks = {}
    for f in sorted(files):
        if f.lower().startswith(mod_pre) and not f.lower().endswith(_DOC_EXTS):
            picks[f.split("/")[-1].lower()] = (f, GOTR_DIR + "/" + f.split("/")[-1])
    for name in ("preload.tbl", "preload_anim.tbl"):
        for where in ("optional_mod_stuff/", "", "MY_CUSTOM_PATCH/"):
            src = low.get((base + where + name).lower())
            if src:
                picks[name] = (src, GOTR_DIR + "/" + name)
                break
    return sorted(picks.values())


def gotr_option_plans(rel_files: list) -> dict:
    """{option folder name: [(archive path, game-relative destination)]},
    each optional mod flat in its own folder."""
    files = [f.replace("\\", "/") for f in rel_files if f and not f.endswith("/")]
    out = {}
    for opt in gotr_options(rel_files):
        name = gotr_option_name(opt)
        pre = opt.lower() + "/"
        picks = {}
        for f in sorted(files):
            if f.lower().startswith(pre) and not f.lower().endswith(_DOC_EXTS):
                picks[f.split("/")[-1].lower()] = (f, f"{GOTR_OPT_DIR}/{name}/" + f.split("/")[-1])
        if picks:
            out[name] = sorted(picks.values())
    return out


def gotr_enable(option_files: dict, enabled: list, name: str) -> tuple:
    """Switch an optional mod on. Any switched-on option that changes one
    of the same files is switched off, so nothing quietly overrides
    anything. Returns (new enabled list, [names switched off])."""
    mine = set(option_files.get(name) or [])
    off = [o for o in enabled if o != name and mine & set(option_files.get(o) or [])]
    new = [o for o in enabled if o not in off and o != name] + [name]
    return sorted(new), sorted(off)


def gotr_default_enabled(option_files: dict) -> tuple:
    """Every optional mod on, except ones that would change a file an
    earlier one (name order) already changes. (enabled, left off)."""
    enabled, taken, left = [], set(), []
    for name in sorted(option_files):
        files = set(option_files[name])
        if files & taken:
            left.append(name)
            continue
        enabled.append(name)
        taken |= files
    return enabled, left


def _is_gotr_line(line: str) -> bool:
    low = line.strip().replace("\\", "/").lower()
    return low == GOTR_DIR.lower() or low.startswith(GOTR_DIR.lower() + "/")


def loose_with_gotr(text: str, enabled: list = ()) -> str:
    """loose.txt listing the switched-on GotR options, then GotR's base,
    at the end (earlier lines win, so options override the base)."""
    lines = [l for l in (text or "").splitlines() if not _is_gotr_line(l)]
    while lines and not lines[-1].strip():
        lines.pop()
    ours = [f"{GOTR_OPT_DIR}/{n}" for n in enabled] + [GOTR_DIR]
    return "\n".join(lines + ours) + "\n"


def loose_without_gotr(text: str) -> str:
    lines = [l for l in (text or "").splitlines() if not _is_gotr_line(l)]
    return "\n".join(lines) + "\n"


def save_files(rel_files: list) -> list:
    """The save files of an archive made only of saves (and readmes), else []."""
    files = [f.replace("\\", "/") for f in rel_files or [] if f and not f.endswith("/")]
    payload = [f for f in files if not f.lower().endswith(_DOC_EXTS)]
    if payload and all(any(h in f.lower().split("/")[-1] for h in _SAVE_HINTS) or "savedata" in f.lower()
                       for f in payload):
        return payload
    return []


_NAME_WORDS = re.compile(r"[a-z0-9]+")


def score_save_dir(path: str, names: set, save_names: list, game_name: str) -> int:
    """How likely `path` (holding files `names`, lower-case) is where this
    game keeps the saves an archive brings: the same file names count most,
    the same kind of file next, the game's name in the path breaks ties."""
    want = {n.split("/")[-1].lower() for n in save_names}
    exts = {os.path.splitext(n)[1] for n in want if os.path.splitext(n)[1]}
    exact = len(want & names)
    kind = sum(1 for n in names if os.path.splitext(n)[1] in exts and exts - {".dat"})
    if not exact and not kind:
        return 0
    words = set(_NAME_WORDS.findall((game_name or "").lower())) - {"the", "of", "and", "edition"}
    in_path = sum(1 for w in words if w in path.lower())
    return exact * 100 + min(kind, 20) * 5 + in_path


def flat_variants(flat_rel: list) -> dict:
    """Mods that ship alternatives (Optional/Darker Nights/x.xtbl beside
    The Mod/x.xtbl): {folder: [files]} for every folder holding a file
    whose name another folder also has; {} when no names clash."""
    by_name = {}
    for f in flat_rel:
        f = f.replace("\\", "/")
        by_name.setdefault(f.split("/")[-1].lower(), set()).add(f.rsplit("/", 1)[0] if "/" in f else "")
    clashing = {d for dirs in by_name.values() if len(dirs) > 1 for d in dirs}
    if not clashing:
        return {}
    return {d: sorted(f for f in flat_rel if (f.rsplit("/", 1)[0] if "/" in f else "") == d)
            for d in sorted(clashing)}


def pick_flat_variant(flat_rel: list, chosen: str) -> list:
    """Every file once: the chosen folder's version wins a clash; other
    clashes go to the first folder in name order."""
    picked = {}
    for f in sorted(flat_rel, key=lambda x: (not (x.rsplit("/", 1)[0] if "/" in x else "") == chosen, x)):
        picked.setdefault(f.split("/")[-1].lower(), f)
    return sorted(picked.values())


def apply_bethesda_profile(game: dict) -> bool:
    """dataDir install settings for a known Bethesda domain. False if the
    domain is not one of BETHESDA_GAMES."""
    entry = BETHESDA_GAMES.get(game.get("nexusDomain") or "")
    if not entry:
        return False
    game["engine"] = "bethesda"
    game["installMode"] = "dataDir"
    game["modsSubdir"] = "Data"
    game["pluginsTxtSubpath"], game["pluginsTxtStyle"] = entry
    game.pop("flatModExtensions", None)
    game["underConstruction"] = (
        "Experimental generic support. Bethesda game: mods merge into Data "
        "and their plugins are switched on in plugins.txt, as for Skyrim. "
        "Script-extender mods need the extender installed by hand."
    )
    return True


# ---- Compatibility check -------------------------------------------------------
# For "as many mods working as possible" the gaps have to be measured, not
# guessed: classify_mod() predicts, from a mod file's published listing and
# without downloading it, what the installer would do with it and whether
# the game would then load it.

# Files each engine's drop-in folder actually loads.
_LOADABLE = {
    "unreal": (".pak", ".utoc", ".ucas"),
    "unity-bepinex": (".dll",),
    "unity": (".dll",),
    "unity-melonloader": (".dll",),
}
_EXE_OR_INSTALLER = (".exe", ".msi", ".bat", ".cmd")

VERDICTS = {
    "mods_folder": "installs into the mods folder",
    "game_folder": "installs into the game folder, file by file",
    "wizard": "has an installer wizard (FOMOD) the plugin runs",
    "tool_managed": "applied by the game's mod tool",
    "loader": "is the game's loader (Step 1)",
    "program": "is a program you run on the desktop",
    "no_target": "has no clear place to go - would land in the mods folder unused",
    "ue_config": "is a settings tweak (Engine.ini), placed in the game's config folder",
    "save_file": "is a save file - goes into the game's save folder (yours are backed up first)",
    "cheat_table": "is a Cheat Engine table - used from the desktop, not installed",
    "reshade_preset": "is a ReShade preset - needs ReShade installed first",
    "unknown": "has no published file list to check",
}


WORKING_VERDICTS = ("mods_folder", "game_folder", "wizard", "tool_managed",
                    "loader", "ue_config", "save_file")

UE_CONFIG_NAMES = {"engine.ini", "gameusersettings.ini", "game.ini", "input.ini",
                   "scalability.ini", "deviceprofiles.ini"}
_SAVE_HINTS = (".sav", ".save", "savedata", "savegame", "slot0", "slot1", "slot2",
               "gta3sf", "gtavcsf", "gtasasf", ".bbsave", "profile.dat")


def ue_config_plan(rel_files: list):
    """[(src, dst)] when an archive is nothing but Unreal user-config files
    (Engine.ini tweaks), each name once; dst is just the file name, relative
    to the game's Saved/Config/<platform> folder. None otherwise."""
    plan, seen = [], set()
    for f in rel_files:
        f = f.replace("\\", "/").strip("/")
        name = f.split("/")[-1]
        low = name.lower()
        if low.endswith(_DOC_EXTS):
            continue
        if low not in UE_CONFIG_NAMES or low in seen:
            return None  # something else in it, or alternatives to choose from
        seen.add(low)
        plan.append((f, name))
    return plan or None


def classify_mod(paths, game: dict, root_entries: set, dir_index: dict,
                 is_framework: bool = False, file_index: dict = None) -> str:
    """One of VERDICTS' keys for a mod file, from its listing paths.

    paths is None when Nexus publishes no listing for the file.
    """
    if is_framework:
        return "loader"
    if paths is None:
        return "unknown"
    files = [p.replace("\\", "/").strip("/") for p in paths if p]
    low = [f.lower() for f in files]
    if any(f.endswith("fomod/moduleconfig.xml") for f in low):
        return "wizard"
    payload_low = [f for f in low if not f.endswith(_DOC_EXTS)]
    if payload_low and all(f.endswith(".ct") or f.endswith(_EXE_OR_INSTALLER) for f in payload_low) \
            and any(f.endswith(".ct") for f in payload_low):
        return "cheat_table"
    if payload_low and all(any(h in f.split("/")[-1] for h in _SAVE_HINTS) or "savedata" in f
                           for f in payload_low):
        return "save_file"
    if game.get("engine") == "unreal" and (ue_config_plan(files) or (
            payload_low and all(f.split("/")[-1] in UE_CONFIG_NAMES for f in payload_low))):
        return "ue_config"
    if payload_low and all(f.endswith((".ini", ".fx", ".fxh", ".addon", ".addon64"))
                           or "reshade-shaders/" in f for f in payload_low) \
            and not any(f.split("/")[-1] in PROXY_DLLS for f in low):
        return "reshade_preset"
    if game.get("toolApply") == "reloaded" and any(
            f.split("/")[-1] == "modconfig.json" for f in low):
        return "tool_managed"
    if game.get("toolApply") == "xv2ins" and any(f.endswith(".x2m") for f in low):
        return "tool_managed"
    if game.get("nexusDomain") == SR2_DOMAIN and gotr_base(files) is not None:
        return "mods_folder"
    if game.get("nexusDomain") == SR2_DOMAIN and sr2_builder(files):
        return "program"
    merge = game.get("mergeInto")
    if merge and only_programs(files):
        return "program"
    if merge and payload_low and game.get("mergeBase"):
        return "mods_folder"
    if merge and payload_low and merge != ".":
        merge_root = merge.split("/")[0].lower()
        tops = {f.split("/")[0] for f in low}
        if not (tops & ({e.lower() for e in root_entries} - {merge_root})):
            return "mods_folder"
    exts = tuple(game.get("flatModExtensions") or [])
    if game.get("toolApply") or exts:
        if exts and any(f.endswith(exts) for f in low):
            return "tool_managed" if game.get("toolApply") else "mods_folder"
        if plan_root_install(files, root_entries, dir_index, game.get("modsSubdir") or "",
                             exe_dir_of(game.get("processName") or ""), file_index,
                             GAME_CONTENT_ROOT.get(game.get("nexusDomain") or "", "")):
            return "game_folder"
        if any(f.endswith(_EXE_OR_INSTALLER) for f in low):
            return "program"
        return "no_target"
    payload = [f for f in low if not f.endswith(_DOC_EXTS)]
    if payload and all(f.endswith(_EXE_OR_INSTALLER) or f.endswith(".dll") for f in payload) \
            and any(f.endswith(_EXE_OR_INSTALLER) for f in payload):
        return "program"
    # Mods-folder content first: a pak mod is a mods-folder mod even if a
    # game file happens to share a name with it.
    loadable = _LOADABLE.get(game.get("engine") or "")
    if loadable and any(f.endswith(loadable) for f in low) and not any(
            "/" not in f and (f in PROXY_DLLS or f.endswith(".asi")) for f in low):
        return "mods_folder"
    plan = plan_root_install(files, root_entries, dir_index,
                             game.get("modsSubdir") or "", exe_dir_of(game.get("processName") or ""),
                             file_index, GAME_CONTENT_ROOT.get(game.get("nexusDomain") or "", ""))
    if plan:
        return "game_folder"
    loadable = _LOADABLE.get(game.get("engine") or "")
    if loadable is None:
        # Unknown engine: a mods folder the game itself created is trusted.
        return "mods_folder" if game.get("engine") == "generic" else "no_target"
    if any(f.endswith(loadable) for f in low):
        return "mods_folder"
    if any(f.endswith(_EXE_OR_INSTALLER) for f in low):
        return "program"
    return "no_target"


def summarize(rows: list) -> dict:
    """{verdict: count} plus the share that should work."""
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    good = sum(counts.get(k, 0) for k in WORKING_VERDICTS)
    checked = len(rows) - counts.get("unknown", 0)
    return {"counts": counts, "working": good, "checked": checked, "total": len(rows)}




def folder_options(install_path: str, current: str) -> list:
    """Likely mods folders for the panel's "change mods folder" list:
    the current one, conventional names that exist, every Content/Paks
    ~mods spot, and the game's top-level folders. Game-relative paths."""
    out = []

    def add(rel):
        if rel and rel not in out:
            out.append(rel)

    add(current)
    for rel, _abs, _files in _walk_dirs(install_path, 4):
        parts = rel.split("/") if rel else []
        if len(parts) >= 2 and parts[-1].lower() == "paks" and parts[-2].lower() == "content":
            add(rel + "/~mods")
            add(rel + "/LogicMods")
        if parts and parts[-1].lower() in ("mods", "plugins", "~mods", "modules", "addons"):
            add(rel)
    for name in ("Mods", "BepInEx/plugins"):
        add(name)
    try:
        for n in sorted(os.listdir(install_path), key=str.lower):
            if os.path.isdir(os.path.join(install_path, n)) and n.lower() not in _SKIP_DIRS:
                add(n)
    except OSError:
        pass
    return out[:40]



def is_mods_folder_payload(rel_files: list, engine: str) -> bool:
    """True when an archive carries what the engine's mods folder loads and
    no loader at its top - the mods-folder install is the right one."""
    loadable = _LOADABLE.get(engine or "")
    if not loadable:
        return False
    low = [f.replace("\\", "/").strip("/").lower() for f in rel_files]
    return any(f.endswith(loadable) for f in low) and not any(
        "/" not in f and (f in PROXY_DLLS or f.endswith(".asi")) for f in low)


# ---- Vortex game rules --------------------------------------------------------
# Extracted offline from Vortex's open game extensions (tools/vortex-rules):
# where each game's mods go and whether they merge into that folder.

def _norm_rel(p: str) -> str:
    p = (p or "").replace("\\", "/").strip("/")
    while p.startswith("./"):
        p = p[2:]
    return p


def vortex_mod_dir(rule: dict, root_entries: set) -> str:
    """The rule's mod folder relative to the game folder, "." for the game
    folder itself, or "" when it points outside it (Documents, AppData)
    or nowhere this install has."""
    raw = rule.get("modPath")
    if not isinstance(raw, str):
        return ""
    p = _norm_rel(raw)
    if re.match(r"^[a-zA-Z]:", raw.replace("\\", "/")) and not raw.upper().startswith("C:\\GAME"):
        return ""
    if raw.upper().startswith("C:\\GAME"):
        p = _norm_rel(raw[len("C:\\GAME"):])
    if p in ("", "."):
        return "."
    first = p.split("/")[0].lower()
    if first not in {e.lower() for e in root_entries}:
        return ""
    return p


def apply_vortex_rule(game: dict, rule: dict, root_entries: set) -> bool:
    """Use Vortex's knowledge of where this game's mods go. True if applied."""
    if not rule or game.get("toolApply") or game.get("installMode") == "dataDir":
        return False
    mod_dir = vortex_mod_dir(rule, root_entries)
    low = mod_dir.lower()
    # Only where Vortex knows something our own inspection does not: the
    # game folder itself is already handled file by file, Unreal pak games
    # already route to Content/Paks/~mods, and a Binaries folder is where
    # an extension keeps loaders while its paks go elsewhere (Sparking
    # Zero's rule points there - following it would break every pak mod).
    if (not mod_dir or mod_dir == "." or "/content/paks" in "/" + low
            or low.split("/")[-1] in ("win64", "win32") or "/binaries" in "/" + low):
        return False
    if mod_dir != ".":
        game["modsSubdir"] = mod_dir
    if rule.get("mergeMods") is not False:
        game["mergeInto"] = mod_dir
    game["vortexRule"] = True
    note = (f"Mod locations come from Vortex's support for this game: mods go in "
            f"{'the game folder' if mod_dir == '.' else mod_dir.replace('/', chr(92))}.")
    uc = game.get("underConstruction") or ""
    if "Vortex" not in uc:
        game["underConstruction"] = (uc + " " + note).strip()
    return True


def only_programs(rel_files: list) -> bool:
    """An archive that is just an installer program (and its readme): it
    has to be run, so merging it into a mod folder would only litter it."""
    payload = [f.replace("\\", "/").lower() for f in rel_files or []
               if f and not f.lower().endswith(_DOC_EXTS + (".installinfo",))]
    return bool(payload) and all(f.endswith(_EXE_OR_INSTALLER) for f in payload)


def plan_merge(rel_files: list, merge_rel: str, merge_entries: set) -> list:
    """[(archive path, game-relative destination)] merging an archive into
    the mod folder the way Vortex deploys it: paths kept as they are,
    except a leading copy of the mod folder's own name, or a single
    wrapper folder whose contents match what that folder holds."""
    files = [_norm_rel(f) for f in rel_files if f and not f.endswith("/")]
    if not files:
        return []
    merge_rel = _norm_rel(merge_rel)
    tail = merge_rel.split("/")[-1].lower() if merge_rel not in ("", ".") else ""
    full = merge_rel.lower() + "/" if merge_rel not in ("", ".") else ""
    lowered = [f.lower() for f in files]

    strip = 0
    if full and all(f.startswith(full) for f in lowered):
        strip = full.count("/")
    elif tail and all(f.split("/")[0] == tail and "/" in f for f in lowered):
        strip = 1
    else:
        tops = {f.split("/")[0] for f in lowered}
        if len(tops) == 1 and all("/" in f for f in lowered):
            top = next(iter(tops))
            seconds = {f.split("/")[1] for f in lowered if f.count("/") >= 1}
            existing = {e.lower() for e in merge_entries}
            if top not in existing and seconds & existing:
                strip = 1
    out = []
    for f in files:
        rest = "/".join(f.split("/")[strip:])
        if not rest:
            continue
        dst = rest if merge_rel in ("", ".") else merge_rel + "/" + rest
        out.append((f, dst))
    return out


# ---- Steam library scan ---------------------------------------------------------

_NOT_GAMES = re.compile(
    r"proton|steam linux runtime|steamworks common|steamvr|redistributable|"
    r"dedicated server|\bsdk\b|soundtrack|playtest|benchmark|wallpaper engine|"
    r"lossless scaling|steam audio",
    re.I)
_TOOL_APP_IDS = {228980, 1070560, 1391110, 1628350, 1493710, 250820, 1826330, 2180100}


def installed_games(steamapps_dirs: list) -> list:
    """[{appId, name, installDir}] for every installed Steam game in the
    given steamapps folders, tools and runtimes left out."""
    out, seen = [], set()
    for lib in steamapps_dirs:
        try:
            names = os.listdir(lib)
        except OSError:
            continue
        for n in names:
            m = re.fullmatch(r"appmanifest_(\d+)\.acf", n)
            if not m:
                continue
            app_id = int(m.group(1))
            if app_id in seen or app_id in _TOOL_APP_IDS:
                continue
            info = read_appmanifest(os.path.join(lib, n))
            name = info.get("name") or ""
            if not name or not info.get("installdir") or _NOT_GAMES.search(name):
                continue
            seen.add(app_id)
            try:
                flags = int(info.get("StateFlags") or 4)
            except ValueError:
                flags = 4
            out.append({"appId": app_id, "name": name, "installDir": info["installdir"],
                        # 4 = fully installed; anything else is downloading,
                        # updating or half-removed (TEKKEN 8 was scanned while
                        # still downloading and "checked" as an empty folder).
                        "ready": bool(flags & 4)})
    out.sort(key=lambda g: g["name"].lower())
    return out


def vortex_outside_dir(rule: dict) -> str:
    """A rule's mod folder when it lives outside the game folder (relative
    to Documents or AppData, e.g. "Electronic Arts/The Sims 4/Mods"), or ""."""
    raw = rule.get("modPath")
    if not isinstance(raw, str) or re.match(r"^[a-zA-Z]:", raw) or raw.upper().startswith("C:\\GAME"):
        return ""
    p = _norm_rel(raw)
    if p in ("", ".") or "/" not in p or ".." in p.split("/"):
        return ""
    return p


def pick_outside_base(rel: str, bases: list) -> str:
    """The first of `bases` (Documents, AppData...) where the folder above
    the mod folder exists - the game has run once and made it."""
    parent = rel.rsplit("/", 1)[0]
    for b in bases:
        if b and os.path.isdir(os.path.join(b, *parent.split("/"))):
            return b
    return ""
