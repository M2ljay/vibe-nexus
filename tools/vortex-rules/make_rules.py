"""Turn run.js output files into py_modules/vortex_rules.json.
Usage: python3 make_rules.py out.json [community-out.json ...] > vortex_rules.json"""
import json
import sys

games = {}
for fn in sys.argv[1:]:
    data = json.load(open(fn))
    for key, entries in data.items():
        if not isinstance(entries, list):
            continue
        for g in entries:
            gid = g.get("id")
            if not gid or not isinstance(g.get("modPath"), str):
                continue
            rule = {
                "name": g.get("name"),
                "modPath": g["modPath"],
                "mergeMods": g.get("mergeMods") if isinstance(g.get("mergeMods"), bool) else None,
                "steamAppId": (g.get("details") or {}).get("steamAppId"),
                "executable": g.get("executable") if isinstance(g.get("executable"), str) else None,
                "source": key,
            }
            types = [{"id": m["id"], "path": m["path"]} for m in g.get("modTypes") or [] if m.get("path")]
            if types:
                rule["modTypes"] = types
            games.setdefault(gid, rule)  # the first file listed wins
json.dump({"about": "Mod folders per game, extracted from Vortex game extensions "
                    "(Nexus-Mods/vortex-games and community extensions) by "
                    "tools/vortex-rules. Facts only: folder names and flags.",
           "games": dict(sorted(games.items()))}, sys.stdout, indent=1)
