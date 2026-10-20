// Experimental: scan the whole Steam library. Lists every installed game
// with its Nexus Mods match, checks (in the background, one game at a
// time) how many of each game's top mods should install where the game
// loads them, and sets a game up with one press.
import { ButtonItem, Field } from "@decky/ui";
import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { useEffect, useState } from "react";

import {
  LibraryGame,
  LibraryResult,
  cancelLibraryCheck,
  getLibraryScan,
  saveExperimentalGame,
  scanSteamLibrary,
  startLibraryCheck,
} from "./api";
import { ALL_GAMES, isExperimentalEnabled } from "./games";
import { loadExperimentalState } from "./ExperimentalSetup";
import { notifyGameStateChanged } from "./state";

function resultText(r?: LibraryResult): string {
  if (!r) return "Not checked yet";
  if (r.error) return r.error;
  const share = r.checked ? `${r.working ?? 0} of ${r.checked} top mods should work` : "No mods to check";
  return r.loader ? `${share} · Step 1 would install ${r.loader}` : share;
}

export function LibraryScan() {
  const [games, setGames] = useState<LibraryGame[]>([]);
  const [results, setResults] = useState<Record<string, LibraryResult>>({});
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<[number, number]>([0, 0]);
  const [adding, setAdding] = useState<number | null>(null);

  useEffect(() => {
    void getLibraryScan().then((r) => {
      if (r.ok) {
        setGames(r.games);
        setResults(r.results);
        setRunning(r.running);
      }
    });
    const listener = addEventListener<[done: number, total: number, appId: number, result: any]>(
      "library_check_progress",
      (done, total, appId, result) => {
        if (done < 0) {
          setRunning(false);
          toaster.toast({ title: "Library check stopped", body: result?.error ?? "" });
          return;
        }
        setProgress([done, total]);
        if (result && appId) setResults((prev) => ({ ...prev, [String(appId)]: result }));
        if (result?.done) {
          setRunning(false);
          toaster.toast({ title: "Library check finished", body: `${total} games checked` });
        }
      }
    );
    return () => removeEventListener("library_check_progress", listener);
  }, []);

  const scan = async () => {
    setBusy(true);
    try {
      const r = await scanSteamLibrary(ALL_GAMES.map((g) => g.appId));
      if (!r.ok) {
        toaster.toast({ title: "Scan failed", body: r.error ?? "" });
        return;
      }
      setGames(r.games ?? []);
      setResults(r.results ?? {});
    } finally {
      setBusy(false);
    }
  };

  const checkAll = async () => {
    const ids = games
      .filter((g) => g.domain && g.status !== "supported" && g.ready !== false)
      .map((g) => g.appId);
    if (!ids.length) return;
    setProgress([0, ids.length]);
    setRunning(true);
    await startLibraryCheck(ids, 20);
  };

  const add = async (g: LibraryGame) => {
    setAdding(g.appId);
    try {
      const r = await saveExperimentalGame(g.appId, g.name, g.domain, g.nexusName || g.name);
      if (!r.ok) {
        toaster.toast({ title: `Couldn't set up ${g.name}`, body: r.error ?? "" });
        return;
      }
      await loadExperimentalState();
      notifyGameStateChanged();
      setGames((prev) => prev.map((x) => (x.appId === g.appId ? { ...x, status: "added" } : x)));
      toaster.toast({ title: `${g.name} set up`, body: "Open it in the Nexus panel to install mods." });
    } finally {
      setAdding(null);
    }
  };

  if (!isExperimentalEnabled()) {
    return (
      <div style={{ fontSize: "13px", opacity: 0.8 }}>
        Turn on "Experimental: any game" above to scan your library.
      </div>
    );
  }

  const matched = games.filter((g) => g.domain);
  const unmatched = games.filter((g) => !g.domain);
  const order = (g: LibraryGame) => {
    const r = results[String(g.appId)];
    return r && r.checked ? -((r.working ?? 0) / r.checked) : 1;
  };
  const sorted = [...matched].sort((a, b) => order(a) - order(b) || b.mods - a.mods);

  return (
    <>
      <ButtonItem
        layout="below"
        disabled={busy}
        description="Finds every installed Steam game and its Nexus Mods page. Nothing is installed."
        onClick={scan}
      >
        {busy ? "Scanning…" : games.length ? "Scan again" : "Scan my Steam library"}
      </ButtonItem>
      {matched.length > 0 && (
        <ButtonItem
          layout="below"
          description={
            running
              ? `Checking ${progress[0]} of ${progress[1]}… one game at a time, about half a minute each. You can leave this page.`
              : "Checks the top 20 mods of every matched game from Nexus's file lists, in the background. Uses Nexus API requests - it stops by itself if Nexus starts refusing."
          }
          onClick={running ? () => void cancelLibraryCheck() : checkAll}
        >
          {running
            ? "Stop checking"
            : `Check all ${matched.filter((g) => g.status !== "supported" && g.ready !== false).length} games`}
        </ButtonItem>
      )}
      {sorted.map((g) => {
        const r = results[String(g.appId)];
        const label =
          g.ready === false
            ? "Still downloading - scan again when it's installed"
            : g.status === "supported"
            ? "Built-in support"
            : g.status === "added"
              ? "Set up · " + resultText(r)
              : resultText(r);
        return (
          <ButtonItem
            key={g.appId}
            layout="below"
            label={g.name}
            description={`${g.mods.toLocaleString()} mods on Nexus · ${label}`}
            disabled={adding !== null}
            onClick={() =>
              g.status === ""
                ? void add(g)
                : toaster.toast({
                    title: g.name,
                    body: g.status === "supported"
                      ? "This game has built-in support - open it in the Nexus panel."
                      : "Already set up - open it in the Nexus panel to install mods.",
                  })
            }
          >
            {adding === g.appId ? "Setting up…" : g.status === "" ? "Set up" : "Open in panel"}
          </ButtonItem>
        );
      })}
      {unmatched.length > 0 && (
        <Field
          label={`${unmatched.length} games without an exact Nexus match`}
          description={unmatched.map((g) => g.name).join(", ")}
          childrenLayout="below"
        >
          {null}
        </Field>
      )}
    </>
  );
}
