"""Reloaded-II support for experimental games (Persona, Metaphor, Sonic...).

Reloaded-II is a mod loader: mods are folders holding a ModConfig.json, kept in
Reloaded's own Mods directory and switched on per game in
Apps/<exe>/AppConfig.json. This module does what Reloaded's launcher would do
when you click through it, so the whole thing runs from the Decky panel:

* setup     - Reloaded's own Setup.exe installs it (and the .NET runtimes it
              needs) with --nogui; we then write its ReloadedII.json if the
              launcher has never been opened;
* per game  - an AppConfig.json, plus "Deploy ASI loader" - Ultimate ASI Loader
              under a dll name the game imports, and Reloaded's bootstrapper
              as an .asi beside it - so launching from Steam loads Reloaded;
* mods      - ModConfig.json folders copied into Mods/<ModId>; missing
              dependencies fetched from Reloaded's NuGet feed;
* enabling  - EnabledMods rewritten from what is installed.

Pure helpers here; the I/O that touches the network lives in main.py.
"""

from __future__ import annotations

import json
import os
import re
import struct

SETUP_URL = "https://github.com/Reloaded-Project/Reloaded-II/releases/latest/download/Setup.exe"
NUGET_INDEX = "https://packages.sewer56.moe/v3/index.json"
BOOTSTRAPPER = "Reloaded.Mod.Loader.Bootstrapper.dll"

# Ultimate ASI Loader names Reloaded will deploy under, in its preference
# order (AsiLoaderDeployer.cs).
ASI_DLLS_64 = ["version.dll", "winmm.dll", "wininet.dll", "dsound.dll", "dinput8.dll"]
ASI_DLLS_32 = ["version.dll", "winmm.dll", "wininet.dll", "vorbisFile.dll", "msvfw32.dll",
               "msacm32.dll", "xlive.dll", "dsound.dll", "dinput8.dll", "dinput.dll",
               "ddraw.dll", "d3d11.dll", "d3d9.dll", "d3d8.dll"]

# Nexus domain -> the game's exe (Reloaded's AppId is the lower-case name).
RELOADED_GAMES = {
    "persona4golden": "P4G.exe",
    "persona5royal": "P5R.exe",
    "persona3reload": "P3R.exe",
    "persona3portable": "P3P.exe",
    "persona4arenaultimax": "P4U2.exe",
    "metaphorrefantazio": "METAPHOR.exe",
    "sonicfrontiers": "SonicFrontiers.exe",
    "sonicxshadowgenerations": "SONIC_X_SHADOW_GENERATIONS.exe",
    "sonicgenerations": "SonicGenerations.exe",
}


def config_folder(appdata: str) -> str:
    return os.path.join(appdata, "Reloaded-Mod-Loader-II")


def loader_config(launcher_dir: str, existing: dict = None) -> dict:
    """ReloadedII.json pointing at an install in launcher_dir. Keeps any
    values an existing config already has (the launcher's own settings)."""
    cfg = dict(existing or {})
    x86 = os.path.join(launcher_dir, "Loader", "x86")
    x64 = os.path.join(launcher_dir, "Loader", "x64")
    defaults = {
        "LoaderPath32": os.path.join(x86, "Reloaded.Mod.Loader.dll"),
        "LoaderPath64": os.path.join(x64, "Reloaded.Mod.Loader.dll"),
        "LauncherPath": os.path.join(launcher_dir, "Reloaded-II.exe"),
        "Bootstrapper32Path": os.path.join(x86, "Bootstrapper", BOOTSTRAPPER),
        "Bootstrapper64Path": os.path.join(x64, "Bootstrapper", BOOTSTRAPPER),
        "ApplicationConfigDirectory": os.path.join(launcher_dir, "Apps"),
        "ModConfigDirectory": os.path.join(launcher_dir, "Mods"),
        "PluginConfigDirectory": os.path.join(launcher_dir, "Plugins"),
        "MiscConfigDirectory": os.path.join(launcher_dir, "User", "Misc"),
        "ModUserConfigDirectory": os.path.join(launcher_dir, "User", "Mods"),
    }
    for k, v in defaults.items():
        if not cfg.get(k):
            cfg[k] = v
    cfg.setdefault("FirstLaunch", False)
    # Reloaded's console window opens over the game at launch; in Steam Big
    # Picture it took the foreground and P4G never came up (2026-10-20).
    # The log file is written either way.
    cfg.setdefault("ShowConsole", False)
    return cfg


def app_config(exe_path: str, game_name: str, enabled: list, existing: dict = None) -> dict:
    cfg = dict(existing or {})
    cfg["AppId"] = os.path.basename(exe_path).lower()
    cfg.setdefault("AppName", game_name)
    cfg["AppLocation"] = exe_path
    cfg.setdefault("AppArguments", "")
    cfg.setdefault("WorkingDirectory", os.path.dirname(exe_path))
    cfg["EnabledMods"] = list(enabled)
    cfg.setdefault("AutoInject", False)
    return cfg


def pe_info(data: bytes) -> tuple:
    """(is_64bit, [imported dll names, lower-case]) from an exe's bytes.
    ([], False) for anything that does not parse."""
    try:
        if data[:2] != b"MZ":
            return False, []
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            return False, []
        n_sections = struct.unpack_from("<H", data, pe + 6)[0]
        opt_size = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        magic = struct.unpack_from("<H", data, opt)[0]
        is64 = magic == 0x20B
        dd = opt + (112 if is64 else 96)
        import_rva = struct.unpack_from("<I", data, dd + 8)[0]
        sections = []
        sec = opt + opt_size
        for i in range(n_sections):
            vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, sec + 40 * i + 8)
            sections.append((vaddr, max(vsize, rsize), raddr))

        def off(rva):
            for vaddr, size, raddr in sections:
                if vaddr <= rva < vaddr + size:
                    return rva - vaddr + raddr
            return None

        names = []
        p = off(import_rva)
        while p is not None and p + 20 <= len(data):
            name_rva = struct.unpack_from("<I", data, p + 12)[0]
            if not name_rva:
                break
            q = off(name_rva)
            if q is None:
                break
            end = data.index(b"\0", q)
            names.append(data[q:end].decode("ascii", "replace").lower())
            p += 20
        return is64, names
    except (struct.error, ValueError, IndexError):
        return False, []


def pick_asi_name(is64: bool, imports: list) -> str:
    """The proxy dll name to give Ultimate ASI Loader, as Reloaded picks it."""
    for name in (ASI_DLLS_64 if is64 else ASI_DLLS_32):
        if name.lower() in imports:
            return name
    return ""


def find_mods(rel_files: list) -> list:
    """Folders in an extracted archive that are Reloaded mods: the
    directories (archive-relative, "" for the root) holding a ModConfig.json."""
    out = []
    for f in rel_files:
        f = f.replace("\\", "/")
        if f.split("/")[-1].lower() == "modconfig.json":
            out.append(f.rsplit("/", 1)[0] if "/" in f else "")
    return sorted(set(out))


def read_mod_config(path: str) -> dict:
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def safe_id(mod_id: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", mod_id or "").strip() or "mod"


def nuget_flat_base(index: dict) -> str:
    """The PackageBaseAddress (flat container) URL from a NuGet v3 index."""
    for r in (index or {}).get("resources") or []:
        if str(r.get("@type", "")).startswith("PackageBaseAddress"):
            return str(r.get("@id") or "").rstrip("/")
    return ""


def newest_version(versions: list) -> str:
    def key(v):
        core = v.split("-")[0]
        return tuple(int(x) if x.isdigit() else 0 for x in core.split(".")), "-" not in v
    vs = [v for v in versions or [] if isinstance(v, str)]
    # A prerelease only when nothing stable has been published.
    vs = [v for v in vs if "-" not in v] or vs
    return max(vs, key=key) if vs else ""


NUPKG_SKIP = ("_rels/", "package/", "[content_types].xml")


def is_reloaded_game(game: dict) -> bool:
    return game.get("toolApply") == "reloaded"


RELOADED_DIR_NAME = "Reloaded-II"
SETUP_ARGS = ["--nogui", "--nocreateshortcut", "--nostartreloaded"]
# Mods a Reloaded game installs here never go into the game folder; folder
# installs that are not Reloaded mods land in this inert spot instead of
# somewhere the game would try to read.
UNUSED_MODS_SUBDIR = "_nexus_unused"


def apply_reloaded_profile(game: dict) -> bool:
    """Turn a game into a Reloaded-II managed one. False when it isn't
    one of RELOADED_GAMES."""
    domain = game.get("nexusDomain") or ""
    exe = RELOADED_GAMES.get(domain)
    if not exe:
        return False
    proc = (game.get("processName") or "").replace("\\", "/")
    if not proc or proc.split("/")[-1].lower() != exe.lower():
        # Keep the folder the scan found the exe in, if it found this one.
        proc = exe
    game["processName"] = proc
    game["engine"] = "reloaded"
    game["modsSubdir"] = UNUSED_MODS_SUBDIR
    game["toolApply"] = "reloaded"
    game.pop("ue4ss", None)
    game.pop("flatModExtensions", None)
    exe_dir = proc.rsplit("/", 1)[0] if "/" in proc else ""
    game["framework"] = {
        "name": "Reloaded-II",
        "nexusModId": 0,
        "detectFile": (exe_dir + "/" if exe_dir else "")
        + BOOTSTRAPPER.replace(".dll", ".asi"),
        "url": "https://reloaded-project.github.io/Reloaded-II/",
        "installKind": "reloaded2",
        "installSubdir": "",
        "warning": (
            "Reloaded-II is the mod loader this game's mods are made for. "
            "Step 1 downloads it from its GitHub releases and installs it "
            "(Windows may ask to install Microsoft's .NET runtimes - say yes), "
            "then adds a small loader beside the game so launching from "
            "Steam starts your mods. Remove it here to put the game back."
        ),
    }
    game["underConstruction"] = (
        "Experimental generic support. This game's mods load through "
        "Reloaded-II: Step 1 sets it up, then each install, uninstall or "
        "switch here updates Reloaded's list of mods for this game, "
        "fetching the libraries they need."
    )
    return True


def mod_index(mods_dir: str) -> dict:
    """{ModId lower-case: (ModId, folder path)} for every mod in Reloaded's
    Mods directory (one level, plus one level of grouping folders)."""
    out = {}
    try:
        entries = sorted(os.listdir(mods_dir))
    except OSError:
        return out
    for name in entries:
        path = os.path.join(mods_dir, name)
        if not os.path.isdir(path):
            continue
        cfg = os.path.join(path, "ModConfig.json")
        if os.path.isfile(cfg):
            mid = read_mod_config(cfg).get("ModId")
            if isinstance(mid, str) and mid:
                out.setdefault(mid.lower(), (mid, path))
            continue
        try:
            subs = sorted(os.listdir(path))
        except OSError:
            continue
        for sub in subs:
            sp = os.path.join(path, sub, "ModConfig.json")
            if os.path.isfile(sp):
                mid = read_mod_config(sp).get("ModId")
                if isinstance(mid, str) and mid:
                    out.setdefault(mid.lower(), (mid, os.path.dirname(sp)))
    return out


def dependencies_of(cfg: dict) -> list:
    deps = cfg.get("ModDependencies") or []
    return [d for d in deps if isinstance(d, str) and d.strip()]


def enabled_mods(existing: list, managed: set, wanted: list) -> list:
    """The AppConfig EnabledMods list: what the player enabled in Reloaded
    themselves (anything we don't manage) kept, then ours in order."""
    managed_l = {m.lower() for m in managed}
    out, seen = [], set()
    for m in list(existing or []) + list(wanted):
        if not isinstance(m, str) or m.lower() in seen:
            continue
        if m in (existing or []) and m.lower() in managed_l and m not in wanted:
            continue
        seen.add(m.lower())
        out.append(m)
    return out


def nupkg_member_target(name: str) -> str:
    """Where a file inside a .nupkg goes, relative to the mod folder; ""
    for NuGet's own bookkeeping files."""
    n = name.replace("\\", "/")
    low = n.lower()
    if not n or n.endswith("/") or low.endswith(".nuspec") or low.startswith(NUPKG_SKIP):
        return ""
    if ".." in n.split("/") or n.startswith("/"):
        return ""
    return n
