"""ReShade for experimental games, done the way ReShade's own setup does it
(crosire/reshade, setup/MainWindow.xaml.cs), without its window:

* the setup exe carries a zip with ReShade32.dll and ReShade64.dll;
* the dll goes beside the game's exe under the name of the graphics API the
  game loads (d3d9.dll, dxgi.dll for D3D10/11/12, opengl32.dll, ddraw.dll);
* ReShade.ini points EffectSearchPaths / TextureSearchPaths at
  .\\reshade-shaders\\Shaders\\** and .\\reshade-shaders\\Textures\\**;
* shader packs come from EffectPackages.ini (crosire/reshade-shaders, branch
  "list"): each section a zip whose Shaders/ and Textures/ folders go to its
  InstallPath / TextureInstallPath.

Pure helpers here; downloads and file copies live in main.py.
"""

from __future__ import annotations

import io
import re
import zipfile

HOME_URL = "https://reshade.me/"
PACKAGES_URL = "https://raw.githubusercontent.com/crosire/reshade-shaders/list/EffectPackages.ini"
EFFECTS_DIR = "reshade-shaders/Shaders"
TEXTURES_DIR = "reshade-shaders/Textures"

_SETUP_RX = re.compile(r"""(?:https://reshade\.me/)?/?downloads/ReShade_Setup_([\d.]+)\.exe""", re.I)


def setup_url(html: str):
    """(version, url) of the newest plain (not add-on) ReShade setup linked
    from reshade.me, or None."""
    best = None
    for m in _SETUP_RX.finditer(html or ""):
        ver = m.group(1)
        if "_Addon" in (html[m.end():m.end() + 6] or ""):
            continue
        key = tuple(int(x) for x in ver.split(".") if x.isdigit())
        if best is None or key > best[0]:
            best = (key, ver)
    if not best:
        return None
    return best[1], f"https://reshade.me/downloads/ReShade_Setup_{best[1]}.exe"


def api_for(imports: list):
    """(api, dll name) ReShade should be installed as for an exe importing
    `imports`, or None when ReShade can't hook it this way (Vulkan, D3D8)."""
    imp = {i.lower() for i in imports or []}
    if "d3d9.dll" in imp:
        return "d3d9", "d3d9.dll"
    if imp & {"dxgi.dll", "d3d11.dll", "d3d12.dll", "d3d10.dll", "d3d10_1.dll"}:
        return "dxgi", "dxgi.dll"
    if "opengl32.dll" in imp:
        return "opengl", "opengl32.dll"
    if "ddraw.dll" in imp:
        return "ddraw", "ddraw.dll"
    return None


def module_from_setup(blob: bytes, is64: bool) -> bytes:
    """ReShade64.dll / ReShade32.dll out of the setup exe's attached zip."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return z.read("ReShade64.dll" if is64 else "ReShade32.dll")


def is_reshade_module(blob: bytes) -> bool:
    """A dll that is ReShade (its version info says so)."""
    return b"R\x00e\x00S\x00h\x00a\x00d\x00e\x00" in (blob or b"")[:4 << 20] or b"ReShade" in (blob or b"")[-(2 << 20):]


def parse_ini(text: str) -> dict:
    """{section: {key: value}} keeping values raw (comma lists intact)."""
    out, cur = {}, None
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith((";", "#")):
            continue
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1].strip()
            out.setdefault(cur, {})
            continue
        if cur is not None and "=" in s:
            k, v = s.split("=", 1)
            out[cur][k.strip()] = v.strip()
    return out


def packages(ini_text: str) -> list:
    """The effect packages EffectPackages.ini lists."""
    out = []
    for name, sec in parse_ini(ini_text).items():
        files = [f.strip() for f in (sec.get("EffectFiles") or "").split(",") if f.strip()]
        deny = {f.strip() for f in (sec.get("DenyEffectFiles") or "").split(",") if f.strip()}
        out.append({
            "id": name,
            "name": sec.get("PackageName") or name,
            "required": sec.get("Required") == "1",
            "default": sec.get("Enabled") == "1" or sec.get("Required") == "1",
            "installPath": (sec.get("InstallPath") or "").replace("\\", "/"),
            "textureInstallPath": (sec.get("TextureInstallPath") or "").replace("\\", "/"),
            "url": sec.get("DownloadUrl") or "",
            "effects": [f for f in files if f not in deny],
            "deny": sorted(deny),
        })
    return out


def preset_effects(preset_text: str) -> set:
    """Effect files (.fx) a preset uses, from its Techniques/TechniqueSorting."""
    sec = {}
    for s in parse_ini(preset_text).values():
        sec.update(s)
    for k, v in parse_ini("[x]\n" + (preset_text or "")).get("x", {}).items():
        sec.setdefault(k, v)
    out = set()
    for key in ("Techniques", "TechniqueSorting"):
        for item in (sec.get(key) or "").split(","):
            if "@" in item:
                out.add(item.split("@", 1)[1].strip())
    return out


def packages_for(effects: set, pkgs: list, have: set) -> list:
    """Packages to fetch: every required one, plus any that provide an
    effect a preset needs and isn't already installed (`have`, lower-case)."""
    want = {e.lower() for e in effects} - {h.lower() for h in have}
    out = []
    for p in pkgs:
        if not p["url"]:
            continue
        if p["required"] or want & {e.lower() for e in p["effects"]}:
            out.append(p)
            want -= {e.lower() for e in p["effects"]}
    return out


def is_preset_archive(rel_files: list) -> list:
    """The preset files (.ini) of an archive that is a ReShade preset - inis
    and shader/texture files, no proxy dll - else []."""
    files = [f.replace("\\", "/") for f in rel_files or [] if f and not f.endswith("/")]
    low = [f.lower() for f in files]
    docs = (".txt", ".md", ".url", ".jpg", ".jpeg", ".png", ".pdf", ".html", ".htm", ".rtf", ".webp", ".gif")
    payload = [f for f in low if not f.endswith(docs) or "/reshade-shaders/" in "/" + f]
    if not payload:
        return []
    ok = all(f.endswith((".ini", ".fx", ".fxh", ".addon", ".addon32", ".addon64", ".png", ".jpg", ".dds"))
             or "reshade-shaders/" in f for f in payload)
    if not ok or any(f.split("/")[-1] in ("dxgi.dll", "d3d9.dll", "d3d11.dll", "opengl32.dll") for f in low):
        return []
    return [f for f in files if f.lower().endswith(".ini") and f.split("/")[-1].lower() != "reshade.ini"]


def reshade_ini(text: str, preset: str = "") -> str:
    """ReShade.ini with the shader search paths (only when it has none, as
    ReShade's setup does) and PresetPath (when given); everything else kept."""
    sec = parse_ini(text).get("GENERAL", {})
    want = {}
    if "EffectSearchPaths" not in sec:
        want["EffectSearchPaths"] = ".\\reshade-shaders\\Shaders\\**"
    if "TextureSearchPaths" not in sec:
        want["TextureSearchPaths"] = ".\\reshade-shaders\\Textures\\**"
    if preset:
        want["PresetPath"] = ".\\" + preset.replace("/", "\\")
    out, in_general, placed = [], False, False
    for line in (text or "").splitlines():
        st = line.strip()
        if st.startswith("[") and st.endswith("]"):
            if in_general and not placed:
                out += [f"{k}={v}" for k, v in want.items()]
                placed = True
            in_general = st[1:-1].strip().upper() == "GENERAL"
            out.append(line)
            continue
        if in_general and "=" in st and st.split("=", 1)[0].strip() in want:
            continue  # rewritten below
        out.append(line)
    if in_general and not placed:
        out += [f"{k}={v}" for k, v in want.items()]
        placed = True
    if not placed and want:
        out += (["", "[GENERAL]"] if out else ["[GENERAL]"]) + [f"{k}={v}" for k, v in want.items()]
    return "\n".join(out).strip("\n") + "\n"
