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
    if len(hinted) == 1:
        return hinted[0]
    if len(candidates) == 1:
        return candidates[0]
    return ""


def plan_root_install(rel_files: list, root_entries: set, dir_index: dict,
                      mods_subdir: str, exe_dir: str):
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

    # Peel wrapper folders that mean nothing to the game ("MyMod v1.2/").
    prefix = ""
    for _ in range(3):
        tops = {f[len(prefix):].split("/")[0] for f in files}
        if len(tops) != 1:
            break
        top = next(iter(tops))
        if not all("/" in f[len(prefix):] for f in files) or known(top.lower()):
            break
        if top.lower() == leaf:
            break
        prefix += top + "/"
    rels = [(f, f[len(prefix):]) for f in files]

    mods_path = "/".join(mods_parts)
    if mods_path and all(r.lower().startswith(mods_path + "/") for _s, r in rels):
        return None
    exe_hint = exe_dir or ""
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
            base = _pick_dir(dir_index[top], [mods_subdir, exe_hint])
            if base:
                dst = base + "/" + "/".join(parts[1:])
        elif len(parts) == 1 and (top in PROXY_DLLS or top.endswith(".asi")):
            dst = (exe_hint + "/" + rel) if exe_hint else rel
        elif top == "plugins" and any(r.lower().endswith(".asi") for _s, r in rels):
            dst = (exe_hint + "/" + rel) if exe_hint else rel
        if dst is None:
            return None
        plan.append((src, dst))
    return plan or None



# ---- Games whose mods are applied by a tool ----------------------------------
# Insomniac's PC ports load no loose mod files: Overstrike (open source, GPL)
# packs .smpcmod/.suit/.stage/.modular files into the game's archives. It
# has a command line (create-profile, install-mods), so the plugin keeps a
# profile in step with what is installed and runs it - one press, no desktop.

PROFILE_VERSION = 2

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
