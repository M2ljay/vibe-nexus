"""GTA III / Vice City model and texture archives (IMG version 1).

`models/gta3.img` holds the game's .dff models and .txd textures; its
directory is the separate `models/gta3.dir`: 32-byte entries of
(offset, size) counted in 2048-byte sectors and a 24-byte name. GTA III
keeps a second pair, `models/txd.img`/`txd.dir`, with copies of the vehicle
textures, and a replaced texture has to go into both (gtamods.com, "Vehicle
Mod Installation").

Mods replace entries. Rather than editing in place, every apply rebuilds
from the original: the archive is cut back to its original length, the
original directory is restored, and each switched-on mod's files are
appended in install order, so a later mod wins and removing a mod is
exact. The original directory is kept beside it as `.nexusbak`.
"""

from __future__ import annotations

import os
import struct

# A planned destination "models/gta3.img::name.txd" means "an entry of that
# archive"; the install keeps such files under STORE/<mod>/.
MARK = "::"
STORE = "Mods/IMG"
GAMES = {
    "gta3": {"exe": "gta3.exe", "cleo": "cleo3", "name": "GTA III"},
    "gtavicecity": {"exe": "gta-vc.exe", "cleo": "cleovc", "name": "GTA Vice City"},
}
SECTOR = 2048
ENTRY = struct.Struct("<II24s")
IMG_EXTS = (".dff", ".txd", ".col", ".ifp")
PAIRS = ("models/gta3", "models/txd")  # archive base names, game-relative


def apply_gta_profile(game: dict) -> bool:
    info = GAMES.get(game.get("nexusDomain") or "")
    if not info:
        return False
    import generic_loaders
    game["engine"] = "gta"
    game["processName"] = info["exe"]
    game["modsSubdir"] = "Mods"
    game["toolApply"] = "gtaimg"
    for k in ("flatModExtensions", "mergeInto", "mergeBase", "extraFrameworks"):
        game.pop(k, None)
    fw = generic_loaders.framework_entry("asiloader", "")
    fw["name"] = "Ultimate ASI Loader + CLEO"
    fw["with"] = [info["cleo"]]
    fw["detectFile"] = generic_loaders.LOADERS[info["cleo"]]["detect"]
    fw["warning"] = (
        f"{info['name']}'s mods are .asi plugins, CLEO scripts and replacement models and "
        "textures. Step 1 gets Ultimate ASI Loader and CLEO from their GitHub releases. "
        "Models and textures go into the game's archives (models/gta3.img): the plugin "
        "rebuilds them from the originals with whichever mods are on, so removing a mod "
        "is exact.")
    game["framework"] = fw
    game["underConstruction"] = (
        f"Experimental generic support for {info['name']}: .asi plugins beside the exe, CLEO "
        "scripts in cleo/, models and textures into the game's archives.")
    return True


def parse_dir(data: bytes) -> list:
    """[[offset, size, name]] from a v1 .dir file."""
    out = []
    for i in range(0, len(data) - len(data) % ENTRY.size, ENTRY.size):
        off, size, raw = ENTRY.unpack_from(data, i)
        name = raw.split(b"\0", 1)[0].decode("latin-1")
        if name:
            out.append([off, size, name])
    return out


def build_dir(entries: list) -> bytes:
    return b"".join(ENTRY.pack(o, s, n.encode("latin-1")[:23].ljust(24, b"\0")) for o, s, n in entries)


def names(root: str) -> dict:
    """{lower-case entry name: game-relative archive path} across the game's
    archives (gta3.img first: a name in both is listed under gta3.img)."""
    out = {}
    for base in PAIRS:
        d = os.path.join(root, *base.split("/")) + ".dir"
        for kept in (d + ".nexusbak", d):
            if os.path.isfile(kept):
                try:
                    with open(kept, "rb") as f:
                        for _o, _s, n in parse_dir(f.read()):
                            out.setdefault(n.lower(), base + ".img")
                except OSError:
                    pass
                break
    return out


def is_v1_game(root: str) -> bool:
    return os.path.isfile(os.path.join(root, "models", "gta3.dir")) and \
        os.path.isfile(os.path.join(root, "models", "gta3.img"))


def rebuild(root: str, state: dict, replacements: list) -> dict:
    """Put each archive back to its original and append `replacements`
    ([(entry name, file path)], later ones win). `state` holds each
    archive's original length, recorded the first time; it is updated and
    returned. Files whose names aren't in an archive are added to gta3.img."""
    state = dict(state or {})
    by_name = {}
    for name, path in replacements:
        by_name[name.lower()] = (name, path)
    for base in PAIRS:
        img = os.path.join(root, *base.split("/")) + ".img"
        dirp = os.path.join(root, *base.split("/")) + ".dir"
        if not (os.path.isfile(img) and os.path.isfile(dirp)):
            continue
        bak = dirp + ".nexusbak"
        orig_len = state.get(base)
        if orig_len is None or not os.path.isfile(bak):
            # First time: this is the game's own archive.
            with open(dirp, "rb") as f:
                original = f.read()
            with open(bak, "wb") as f:
                f.write(original)
            orig_len = os.path.getsize(img)
            state[base] = orig_len
        with open(bak, "rb") as f:
            entries = parse_dir(f.read())
        if os.path.getsize(img) < orig_len:
            # Smaller than recorded: Steam put a different original back.
            orig_len = os.path.getsize(img)
            state[base] = orig_len
            with open(dirp, "rb") as f:
                original = f.read()
            with open(bak, "wb") as f:
                f.write(original)
            entries = parse_dir(original)
        index = {e[2].lower(): e for e in entries}
        mine = [(n, p) for key, (n, p) in by_name.items()
                if key in index or (base == PAIRS[0] and not _in_other(key, root))]
        with open(img, "r+b") as f:
            f.truncate(orig_len)
            f.seek(orig_len)
            sector = (orig_len + SECTOR - 1) // SECTOR
            if orig_len % SECTOR:
                f.write(b"\0" * (sector * SECTOR - orig_len))
            for name, path in mine:
                with open(path, "rb") as src:
                    data = src.read()
                pad = (-len(data)) % SECTOR
                f.write(data + b"\0" * pad)
                size = (len(data) + pad) // SECTOR
                e = index.get(name.lower())
                if e:
                    e[0], e[1] = sector, size
                else:
                    e = [sector, size, name]
                    entries.append(e)
                    index[name.lower()] = e
                sector += size
        with open(dirp, "wb") as f:
            f.write(build_dir(entries))
        state[base + ":count"] = len(mine)
    return state


def _in_other(key: str, root: str) -> bool:
    d = os.path.join(root, "models", "txd.dir.nexusbak")
    if not os.path.isfile(d):
        d = os.path.join(root, "models", "txd.dir")
    try:
        with open(d, "rb") as f:
            return any(n.lower() == key for _o, _s, n in parse_dir(f.read()))
    except OSError:
        return False


def restore(root: str, state: dict) -> None:
    """Back to the game's own archives (no mods)."""
    rebuild(root, state, [])
