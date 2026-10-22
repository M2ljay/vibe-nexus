"""Capcom RE Engine games through REFramework (praydog/REFramework, MIT).

* Step 1: the game's zip from REFramework's latest GitHub release
  (RE2.zip, ...; RE2_TDB66.zip etc. for the DX11 builds of RE2/RE3/RE7):
  dinput8.dll beside the exe. Its Loose File Loader - off by default - is
  switched on in re2_fw_config.txt (REFramework's config file name in
  every game: REFrameworkConfig::REFRAMEWORK_CONFIG_NAME), so mods' loose
  natives/ files load without repacking.
* Mods are natives/... trees, REFramework scripts (reframework/autorun/*.lua)
  and plugins (reframework/plugins/*.dll), all relative to the game folder.
  Fluffy Mod Manager's modinfo.ini and screenshots ride along unused.
* RE2, RE3 and RE7 have two builds: the current ray-traced one (DX12, a
  D3D12 folder) reads natives/stm/, the DX11 one (Steam's dx11_non-rt
  beta) natives/x64/.

Pure helpers here; downloading lives in main.py.
"""

from __future__ import annotations

import re

RELEASE = "https://github.com/praydog/REFramework/releases/latest/download/"
GAMES = {
    "residentevil22019": {"exe": "re2.exe", "zip": "RE2.zip", "dx11": "RE2_TDB66.zip", "name": "Resident Evil 2"},
    "residentevil32020": {"exe": "re3.exe", "zip": "RE3.zip", "dx11": "RE3_TDB67.zip", "name": "Resident Evil 3"},
    "residentevil7": {"exe": "re7.exe", "zip": "RE7.zip", "dx11": "RE7_TDB49.zip",
                      "name": "Resident Evil 7"},
    "residentevil42023": {"exe": "re4.exe", "zip": "RE4.zip", "name": "Resident Evil 4"},
    "residentevilvillage": {"exe": "re8.exe", "zip": "RE8.zip", "name": "Resident Evil Village"},
    "devilmaycry5": {"exe": "DevilMayCry5.exe", "zip": "DMC5.zip", "name": "Devil May Cry 5"},
    "monsterhunterrise": {"exe": "MonsterHunterRise.exe", "zip": "MHRISE.zip", "name": "Monster Hunter Rise"},
    "monsterhunterwilds": {"exe": "MonsterHunterWilds.exe", "zip": "MHWILDS.zip",
                           "name": "Monster Hunter Wilds"},
    "streetfighter6": {"exe": "StreetFighter6.exe", "zip": "SF6.zip", "name": "Street Fighter 6"},
    "dragonsdogma2": {"exe": "DD2.exe", "zip": "DD2.zip", "name": "Dragon's Dogma 2"},
}
CONFIG = "re2_fw_config.txt"
_DOCS = (".txt", ".md", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".url", ".html")
_DLC_DIR = re.compile(r"^\d{5,}$")


def is_re(game: dict) -> bool:
    return (game or {}).get("nexusDomain") in GAMES


def apply_re_profile(game: dict, dx12: bool) -> bool:
    info = GAMES.get(game.get("nexusDomain") or "")
    if not info:
        return False
    game["engine"] = "reengine"
    game["processName"] = info["exe"]
    game["modsSubdir"] = "natives"
    game["reBuild"] = "dx12" if dx12 or "dx11" not in info else "dx11"
    for k in ("flatModExtensions", "mergeInto", "mergeBase", "extraFrameworks", "toolApply"):
        game.pop(k, None)
    game["framework"] = {
        "name": "REFramework",
        "nexusModId": 0,
        "detectFile": "dinput8.dll",
        "url": "https://github.com/praydog/REFramework",
        "installKind": "reframework",
        "installSubdir": "",
        "warning": (
            f"{info['name']}'s mods are loose game files (natives/...) and REFramework scripts. "
            "Step 1 gets REFramework from its GitHub releases and switches on its Loose File "
            "Loader, so those files load as they are - no Fluffy Mod Manager needed. It loads "
            "code into the game: don't use it in online modes."),
    }
    note = ""
    if "dx11" in info:
        note = (" Your game is the ray-traced (DX12) build, which reads natives/stm/ - mods made "
                "for the DX11 build (natives/x64/) need Steam's dx11_non-rt beta branch."
                if game["reBuild"] == "dx12" else
                " Your game is the DX11 build (natives/x64/); mods for the ray-traced build use natives/stm/.")
    game["underConstruction"] = (
        f"Experimental generic support for {info['name']} through REFramework's Loose File Loader." + note)
    return True


def release_url(game: dict) -> str:
    info = GAMES[game["nexusDomain"]]
    name = info.get("dx11") if game.get("reBuild") == "dx11" and info.get("dx11") else info["zip"]
    return RELEASE + name


def plan(rel_files: list):
    """[(archive path, game-relative destination)] for a loose-file mod, or
    None. The mod's own top folder is natives/, reframework/, or a DLC's
    numbered folder holding re_dlc_*.pak; wrapper folders are peeled."""
    files = [f.replace("\\", "/").strip("/") for f in rel_files or [] if f]
    payload = [f for f in files if not f.lower().endswith(_DOCS)
               and f.split("/")[-1].lower() != "modinfo.ini"]
    if not payload:
        return None
    prefix = ""
    for _ in range(3):
        tops = {f[len(prefix):].split("/")[0] for f in payload if f.startswith(prefix)}
        if any(_is_top(t, payload, prefix) for t in tops):
            break
        if len(tops) != 1:
            return None
        prefix += next(iter(tops)) + "/"
    out = []
    for f in payload:
        if not f.startswith(prefix):
            return None
        rel = f[len(prefix):]
        if not _is_top(rel.split("/")[0], payload, prefix) or "/" not in rel:
            return None
        out.append((f, rel))
    return out or None


def _is_top(name: str, payload: list, prefix: str) -> bool:
    low = name.lower()
    if low in ("natives", "reframework"):
        return True
    return bool(_DLC_DIR.match(name)) and any(
        f.startswith(prefix + name + "/") and f.split("/")[-1].lower().startswith("re_dlc_")
        for f in payload)


def wrong_build(rel_files: list, game: dict) -> bool:
    """A mod laid out for the other build of a two-build game."""
    if "dx11" not in GAMES.get(game.get("nexusDomain") or "", {}):
        return False
    other = "natives/x64/" if game.get("reBuild") == "dx12" else "natives/stm/"
    mine = "natives/stm/" if other == "natives/x64/" else "natives/x64/"
    low = ["/" + f.replace("\\", "/").lower() for f in rel_files or []]
    return any("/" + other in f for f in low) and not any("/" + mine in f for f in low)


def enable_loose_loader(text: str) -> str:
    """REFramework's config with LooseFileLoader_Enabled=true."""
    lines = [ln for ln in (text or "").splitlines() if not ln.strip().lower().startswith("loosefileloader_enabled=")]
    lines.append("LooseFileLoader_Enabled=true")
    return "\n".join(lines) + "\n"
