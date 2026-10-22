"""Engine-wide mod loaders the plugin can install itself (Step 1) when a
game's mods need one and its Nexus page does not host it.

Each comes from the project's own GitHub releases:
  BepInEx 5 (Unity, Mono), BepInEx 6 (Unity, IL2CPP), MelonLoader (Unity),
  UE4SS (Unreal), Ultimate ASI Loader (DirectX games with .asi plugins).

Pure helpers: choosing a loader from what the game's mods contain, picking
the release asset, and where its files go. Downloads live in main.py.
"""

from __future__ import annotations

import re

GITHUB_API = "https://api.github.com/repos/{repo}/releases?per_page=30"

LOADERS = {
    "bepinex5": {
        "name": "BepInEx 5",
        "repo": "BepInEx/BepInEx",
        "tag": r"^v5\.",
        "asset64": r"^BepInEx_(win_)?x64_5\.[\d.]+\.zip$",
        "asset32": r"^BepInEx_(win_)?x86_5\.[\d.]+\.zip$",
        "prerelease": False,
        "target": "root",
        "detect": "BepInEx/core/BepInEx.dll",
        "url": "https://github.com/BepInEx/BepInEx",
    },
    "bepinex6il2cpp": {
        "name": "BepInEx 6 (IL2CPP)",
        "repo": "BepInEx/BepInEx",
        "tag": r"^v6\.",
        "asset64": r"^BepInEx-Unity\.IL2CPP-win-x64-6[\w.+-]*\.zip$",
        "asset32": r"^BepInEx-Unity\.IL2CPP-win-x86-6[\w.+-]*\.zip$",
        "prerelease": True,
        "target": "root",
        "detect": "BepInEx/core/BepInEx.Unity.IL2CPP.dll",
        "url": "https://github.com/BepInEx/BepInEx",
    },
    "melonloader": {
        "name": "MelonLoader",
        "repo": "LavaGang/MelonLoader",
        "tag": r"^v?0\.",
        "asset64": r"^MelonLoader\.x64\.zip$",
        "asset32": r"^MelonLoader\.x86\.zip$",
        "prerelease": False,
        "target": "root",
        "detect": "MelonLoader",
        "url": "https://github.com/LavaGang/MelonLoader",
    },
    "ue4ss": {
        "name": "UE4SS",
        "repo": "UE4SS-RE/RE-UE4SS",
        "tag": r"^v\d",
        "asset64": r"^UE4SS_v[\d.]+\.zip$",
        "asset32": None,
        "prerelease": False,
        "target": "exe",
        "detect": "dwmapi.dll",
        "url": "https://github.com/UE4SS-RE/RE-UE4SS",
    },
    "asiloader": {
        "name": "Ultimate ASI Loader",
        "repo": "ThirteenAG/Ultimate-ASI-Loader",
        "tag": r"^v",
        "asset64": r"^Ultimate-ASI-Loader_x64\.zip$",
        "asset32": r"^Ultimate-ASI-Loader\.zip$",
        "prerelease": False,
        "target": "exe",
        "detect": "",  # the proxy dll's name depends on the game
        "url": "https://github.com/ThirteenAG/Ultimate-ASI-Loader",
    },
    "doommodloader": {
        "name": "DOOMModLoader",
        "repo": "ZwipZwapZapony/DOOMModLoader",
        "tag": r".",
        "asset64": r"^DOOMModLoader-Windows-x64\.zip$",
        "asset32": None,
        "prerelease": False,
        "target": "root",
        "detect": "DOOMModLoader.exe",
        "url": "https://github.com/ZwipZwapZapony/DOOMModLoader",
    },
    "cleo3": {
        "name": "CLEO (GTA III)",
        "repo": "cleolibrary/III.VC.CLEO",
        "tag": r"^v?\d",
        "asset64": r"^III\.CLEO-v?[\d.]+\.zip$",
        "asset32": r"^III\.CLEO-v?[\d.]+\.zip$",
        "prerelease": False,
        "target": "root",
        "detect": "III.CLEO.asi",
        "url": "https://github.com/cleolibrary/III.VC.CLEO",
    },
    "cleovc": {
        "name": "CLEO (Vice City)",
        "repo": "cleolibrary/III.VC.CLEO",
        "tag": r"^v?\d",
        "asset64": r"^VC\.CLEO-v?[\d.]+\.zip$",
        "asset32": r"^VC\.CLEO-v?[\d.]+\.zip$",
        "prerelease": False,
        "target": "root",
        "detect": "VC.CLEO.asi",
        "url": "https://github.com/cleolibrary/III.VC.CLEO",
    },
    "sr2juiced": {
        "name": "Juiced Patch",
        # The project's releases live here; Clippy95's repo is the source mirror.
        "repo": "kobraworksmodding/Saints-Row-2-Juiced-Patch",
        "tag": r".",
        "asset64": r"^SR2_JUICED\.zip$",
        "asset32": r"^SR2_JUICED\.zip$",
        "prerelease": False,
        "target": "root",
        "detect": "juiced.ini",
        "url": "https://github.com/kobraworksmodding/Saints-Row-2-Juiced-Patch",
    },
}

# Names Ultimate ASI Loader works under, most broadly useful first.
ASI_PROXY_NAMES = ["dinput8.dll", "version.dll", "winmm.dll", "dsound.dll", "d3d9.dll",
                   "d3d11.dll", "wininet.dll", "winhttp.dll", "xinput1_3.dll",
                   "d3d8.dll", "ddraw.dll", "dinput.dll", "msacm32.dll", "vorbisfile.dll"]

_WORD = {
    "bepinex": re.compile(r"bepinex", re.I),
    "melonloader": re.compile(r"melon\s*loader", re.I),
    "ue4ss": re.compile(r"ue4ss", re.I),
    "asiloader": re.compile(r"asi\s*loader|ultimate\s*asi", re.I),
}


def mod_signals(paths: list) -> set:
    """What a mod's file list says about the loader it is made for."""
    out = set()
    low = [p.replace("\\", "/").lower().strip("/") for p in paths or []]
    for p in low:
        parts = p.split("/")
        if "bepinex" in parts and any(x in parts for x in ("plugins", "patchers", "config")):
            out.add("bepinex")
        if p.endswith(".asi"):
            out.add("asiloader")
        if parts[-1] in ("main.lua", "enabled.txt") and "scripts" in parts or "ue4ss" in parts:
            out.add("ue4ss")
        if parts[0] in ("mods", "userlibs", "plugins") and p.endswith(".dll") and len(parts) == 2:
            out.add("dll-in-mods")
    return out


def suggest_loader(engine: str, il2cpp: bool, listings: list, req_names: list) -> str:
    """The generic loader a game's mods need, or "".

    listings: file lists of the game's top mods (None entries skipped).
    req_names: names of requirements those mods declare."""
    counts = {}
    seen = 0
    for paths in listings:
        if paths is None:
            continue
        seen += 1
        for s in mod_signals(paths):
            counts[s] = counts.get(s, 0) + 1
    for name in req_names or []:
        for key, rx in _WORD.items():
            if rx.search(name or ""):
                counts[key] = counts.get(key, 0) + 2
    need = max(2, seen // 5)

    def strong(key):
        return counts.get(key, 0) >= need

    unity = (engine or "").startswith("unity")
    if unity and engine not in ("unity-bepinex", "unity-melonloader"):
        if strong("bepinex"):
            return "bepinex6il2cpp" if il2cpp else "bepinex5"
        if strong("melonloader") or (counts.get("dll-in-mods", 0) >= need
                                    and not counts.get("bepinex")):
            return "melonloader"
    if engine == "unreal" and strong("ue4ss"):
        return "ue4ss"
    if strong("asiloader"):
        return "asiloader"
    return ""


def pick_asset(releases: list, loader: dict, is64: bool):
    """(release tag, asset name, download url) for the newest release that
    matches, or None."""
    rx = loader["asset64"] if is64 else loader["asset32"]
    if not rx:
        return None
    asset_rx, tag_rx = re.compile(rx, re.I), re.compile(loader["tag"])
    for rel in releases or []:
        if rel.get("draft") or (rel.get("prerelease") and not loader["prerelease"]):
            continue
        if not tag_rx.search(str(rel.get("tag_name") or "")):
            continue
        for a in rel.get("assets") or []:
            if asset_rx.match(str(a.get("name") or "")):
                return rel["tag_name"], a["name"], a.get("browser_download_url")
    return None


def pick_asi_proxy(imports: list, taken: set) -> str:
    """A proxy name the game loads and nothing else is using."""
    imports = {i.lower() for i in imports or []}
    for name in ASI_PROXY_NAMES:
        if name in imports and name not in taken:
            return name
    return ""


def framework_entry(loader_id: str, exe_dir: str, detect_override: str = "") -> dict:
    spec = LOADERS[loader_id]
    if spec["target"] == "exe" and exe_dir:
        detect = detect_override or (exe_dir + "/" + spec["detect"] if spec["detect"] else "")
    else:
        detect = detect_override or spec["detect"]
    return {
        "name": spec["name"],
        "nexusModId": 0,
        "detectFile": detect,
        "url": spec["url"],
        "installKind": "githubLoader",
        "loaderId": loader_id,
        "installSubdir": exe_dir if spec["target"] == "exe" else "",
        "warning": (
            f"Most of this game's mods need {spec['name']}. Step 1 downloads it "
            "from its official GitHub releases and puts it in the game folder; "
            "Remove takes it out again. It loads code into the game: online "
            "games with anti-cheat may penalise accounts that use it."
        ),
    }
