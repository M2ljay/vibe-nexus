// Experimental "any game" support (this fork). Panel rows for games without a
// curated entry: an opt-in switch, a one-press setup that matches the game to
// its Nexus Mods domain and guesses its mods folder, and a way to undo it.
// The matching and folder guessing run in the backend
// (py_modules/experimental_games.py); this file only drives them.
import {
  ButtonItem,
  Field,
  ModalRoot,
  PanelSectionRow,
  TextField,
  ToggleField,
  showModal,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useState } from "react";

import {
  CoverageRow,
  ExperimentalCandidate,
  applyExperimentalTool,
  checkExperimentalCoverage,
  experimentalFolderOptions,
  setExperimentalFramework,
  setExperimentalModsFolder,
  findExperimentalGame,
  getExperimentalState,
  removeExperimentalFramework,
  removeExperimentalGame,
  saveExperimentalGame,
  setExperimentalEnabled,
} from "./api";
import {
  SupportedGame,
  isExperimentalEnabled,
  isExperimentalGame,
  setExperimentalState,
} from "./games";
import { notifyGameStateChanged } from "./state";

/** Toast for the backend's automatic re-apply after an install/uninstall. */
export function toolAppliedToast(
  _domain: string,
  result: { ok: boolean; count?: number; error?: string; restart?: boolean }
): void {
  toaster.toast(
    result.ok
      ? {
          title: result.restart
            ? "Mods applied - restart the game to see them"
            : "Overstrike applied your mods",
          body: result.restart
            ? "The game was already running and loaded the old files."
            : result.count
              ? `${result.count} mod file${result.count === 1 ? "" : "s"} active - you can play now`
              : "No mods installed - the game is back to vanilla",
        }
      : { title: "Overstrike couldn't apply mods", body: result.error ?? "" }
  );
}

/** Shown when the automatic re-apply starts, so nobody launches mid-way. */
export function toolApplyingToast(): void {
  toaster.toast({
    title: "Applying mods with Overstrike…",
    body: "Wait for the next message before starting the game",
  });
}

/** Pull the saved experimental state from the backend into games.ts. */
export async function loadExperimentalState(): Promise<void> {
  try {
    const r = await getExperimentalState();
    if (r.ok) {
      setExperimentalState(r.enabled, r.games ?? []);
      notifyGameStateChanged();
    }
  } catch (e) {
    console.warn("[Nexus Mods] experimental state not loaded", e);
  }
}

function PickGameModal({
  steamName,
  candidates,
  onPick,
  closeModal,
}: {
  steamName: string;
  candidates: ExperimentalCandidate[];
  onPick: (c: ExperimentalCandidate) => void;
  closeModal?: () => void;
}) {
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>Which Nexus Mods game is {steamName}?</h3>
      <div style={{ fontSize: "13px", opacity: 0.9, marginBottom: "8px" }}>
        The names did not match exactly. Pick the right one, or back out if
        none of these is the game.
      </div>
      {candidates.map((c) => (
        <ButtonItem
          key={c.domain}
          layout="below"
          description={
            c.mods ? `${c.mods.toLocaleString()} mods · ${c.domain}` : c.domain
          }
          onClick={() => {
            closeModal?.();
            onPick(c);
          }}
        >
          {c.name}
        </ButtonItem>
      ))}
    </ModalRoot>
  );
}

const VERDICT_TEXT: Record<CoverageRow["verdict"], string> = {
  mods_folder: "Works · mods folder",
  game_folder: "Works · game folder",
  wizard: "Works · installer wizard",
  tool_managed: "Works · applied by the mod tool",
  loader: "Step 1 loader",
  program: "Desktop program - can't install",
  no_target: "No clear place - likely won't load",
  ue_config: "Works · settings tweak (Engine.ini)",
  save_file: "Save file - not installed (copy it yourself)",
  unknown: "Can't check (no file list)",
};

function CoverageModal({
  gameName,
  result,
  closeModal,
  onDeep,
}: {
  gameName: string;
  result: { working?: number; checked?: number; total?: number; rows?: CoverageRow[] };
  closeModal?: () => void;
  onDeep?: () => void;
}) {
  const rows = result.rows ?? [];
  const problems = rows.filter((r) =>
    ["program", "no_target", "unknown", "save_file"].includes(r.verdict)
  );
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>
        {gameName}: {result.working ?? 0} of {result.checked ?? 0} checked mods should work
      </h3>
      <div style={{ fontSize: "13px", opacity: 0.85, marginBottom: "8px" }}>
        The {result.total ?? 0} most-endorsed mods, judged from the files Nexus
        Mods lists for them - nothing was downloaded. A prediction, not a promise.
      </div>
      {(result.rows ?? []).some((r) => r.verdict === "unknown") && onDeep && (
        <ButtonItem
          layout="below"
          description="Downloads the mods Nexus lists no files for (up to 4 GB in total), looks inside, and deletes them again. Nothing is installed."
          onClick={() => {
            closeModal?.();
            onDeep();
          }}
        >
          Check the unlisted ones by downloading them
        </ButtonItem>
      )}
      {problems.length === 0 ? (
        <div style={{ fontSize: "13px" }}>No problem mods found.</div>
      ) : (
        problems.map((r) => (
          <Field key={r.modId} label={r.name} childrenLayout="below">
            {VERDICT_TEXT[r.verdict]}
          </Field>
        ))
      )}
    </ModalRoot>
  );
}

export function ExperimentalToggle() {
  const [enabled, setEnabled] = useState(isExperimentalEnabled());
  return (
    <ToggleField
      label="Experimental: any game"
      description="Offer generic mod support for games the plugin has no rules for. Mods go into a folder guessed from the game's files."
      checked={enabled}
      onChange={async (v: boolean) => {
        setEnabled(v);
        const r = await setExperimentalEnabled(v);
        if (r.ok) {
          setExperimentalState(r.enabled, r.games ?? []);
          setEnabled(r.enabled);
          notifyGameStateChanged();
        }
      }}
    />
  );
}

/** Rows under "Current Game" when the game has no curated support. */
export function ExperimentalUnsupportedRows({
  appId,
  name,
}: {
  appId?: number;
  name: string;
}) {
  const [busy, setBusy] = useState(false);
  const enabled = isExperimentalEnabled();

  const save = async (c: ExperimentalCandidate) => {
    if (appId === undefined) return;
    const r = await saveExperimentalGame(appId, name, c.domain, c.name);
    if (!r.ok || !r.game) {
      toaster.toast({ title: "Setup failed", body: r.error ?? "Unknown error" });
      return;
    }
    await loadExperimentalState();
    toaster.toast({
      title: `${name}: experimental support on`,
      body: `Nexus Mods game: ${c.name}. Mods go in ${r.game.modsSubdir}.`,
    });
  };

  const setup = async () => {
    if (appId === undefined || busy) return;
    setBusy(true);
    try {
      const r = await findExperimentalGame(appId, name);
      if (!r.ok) {
        toaster.toast({ title: "Setup failed", body: r.error ?? "Unknown error" });
        return;
      }
      if (r.inspection?.engine === "missing") {
        toaster.toast({
          title: `${name} isn't installed here`,
          body: r.inspection.note,
        });
        return;
      }
      if (r.exact) {
        await save(r.exact);
        return;
      }
      const candidates = r.candidates ?? [];
      if (candidates.length === 0) {
        toaster.toast({
          title: "No Nexus Mods page found",
          body: `Nothing on Nexus Mods matched "${r.name || name}".`,
        });
        return;
      }
      showModal(
        <PickGameModal
          steamName={name}
          candidates={candidates}
          onPick={(c) => void save(c)}
        />
      );
    } finally {
      setBusy(false);
    }
  };

  if (!enabled) {
    return (
      <PanelSectionRow>
        <ExperimentalToggle />
      </PanelSectionRow>
    );
  }
  return (
    <>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy || appId === undefined}
          description="Experimental: matches this game on Nexus Mods and guesses where its mods go."
          onClick={setup}
        >
          {busy ? "Looking it up…" : `Set up mods for ${name}`}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ExperimentalToggle />
      </PanelSectionRow>
    </>
  );
}

/** Extra rows under "Current Game" for a game set up experimentally. */
function FolderModal({
  game,
  current,
  options,
  closeModal,
}: {
  game: SupportedGame;
  current: string;
  options: string[];
  closeModal?: () => void;
}) {
  const [custom, setCustom] = useState(current);
  const pick = async (subdir: string) => {
    const r = await setExperimentalModsFolder(game.appId, subdir);
    if (!r.ok) {
      toaster.toast({ title: "Mods folder not changed", body: r.error ?? "" });
      return;
    }
    closeModal?.();
    toaster.toast({ title: "Mods folder changed", body: subdir });
    await loadExperimentalState();
  };
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>Where do {game.displayName} mods go?</h3>
      <div style={{ fontSize: "13px", opacity: 0.85, marginBottom: "8px" }}>
        Folders inside the game folder. Each mod gets its own folder in the one
        you pick. Check a popular mod's instructions if you're unsure.
      </div>
      {options.map((o) => (
        <ButtonItem key={o} layout="below" onClick={() => void pick(o)}>
          {o === current ? `${o} (current)` : o}
        </ButtonItem>
      ))}
      <TextField
        label="Or type a folder (relative to the game folder)"
        value={custom}
        onChange={(e: any) => setCustom(e.target.value)}
      />
      <ButtonItem layout="below" onClick={() => void pick(custom)}>
        Use this folder
      </ButtonItem>
    </ModalRoot>
  );
}

export function ExperimentalGameRows({ game }: { game: SupportedGame }) {
  const [busy, setBusy] = useState(false);
  if (!isExperimentalGame(game)) return null;
  return (
    <>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          label="Mods folder"
          disabled={busy || game.toolApply !== undefined || game.installMode === "dataDir"}
          description={game.modsSubdir}
          onClick={async () => {
            const r = await experimentalFolderOptions(game.appId);
            if (!r.ok) {
              toaster.toast({ title: "Couldn't list folders", body: r.error ?? "" });
              return;
            }
            showModal(
              <FolderModal
                game={game}
                current={r.current ?? game.modsSubdir}
                options={r.options ?? []}
              />
            );
          }}
        >
          Change
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          description={
            game.framework
              ? `Step 1 (${game.framework.name}) was guessed from what the top mods require. Remove it if this game doesn't need it - files it installed are taken out.`
              : "Looks again at what the game's top mods require, in case they need a loader installed first."
          }
          onClick={async () => {
            setBusy(true);
            try {
              const r = await setExperimentalFramework(
                game.appId,
                game.framework ? "none" : "redetect"
              );
              toaster.toast(
                r.ok
                  ? {
                      title: game.framework ? "Step 1 removed" : "Step 1 checked",
                      body: r.game?.framework
                        ? `Needs ${r.game.framework.name}`
                        : "No loader needed",
                    }
                  : { title: "Couldn't change Step 1", body: r.error ?? "" }
              );
              await loadExperimentalState();
            } finally {
              setBusy(false);
            }
          }}
        >
          {game.framework ? "This game doesn't need Step 1" : "Look for a Step 1 loader"}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          description="Checks the 50 most popular mods for this game, without downloading them, and lists the ones the plugin can't place where the game loads them."
          onClick={async () => {
            const run = async (deep: boolean) => {
              setBusy(true);
              try {
                if (deep) {
                  toaster.toast({
                    title: "Downloading unlisted mods to check them…",
                    body: "This can take a few minutes",
                  });
                }
                const r = await checkExperimentalCoverage(game.appId, 50, deep);
                if (!r.ok) {
                  toaster.toast({ title: "Check failed", body: r.error ?? "" });
                  return;
                }
                showModal(
                  <CoverageModal
                    gameName={game.displayName}
                    result={r}
                    onDeep={deep ? undefined : () => void run(true)}
                  />
                );
              } finally {
                setBusy(false);
              }
            };
            await run(false);
          }}
        >
          {busy ? "Checking…" : "Check mod compatibility"}
        </ButtonItem>
      </PanelSectionRow>
      {game.toolApply === "overstrike" && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={busy}
            description="Runs Overstrike now with every installed mod. Happens by itself after each install or uninstall; use this after a game update or if that failed. Close the game first."
            onClick={async () => {
              setBusy(true);
              try {
                toolAppliedToast(game.nexusDomain, await applyExperimentalTool(game.appId));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Applying…" : "Apply mods with Overstrike"}
          </ButtonItem>
        </PanelSectionRow>
      )}
      {game.framework?.installKind === "copyRootTracked" && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={busy}
            description={`Deletes the files ${game.framework.name} added and puts back any game file it replaced.`}
            onClick={async () => {
              setBusy(true);
              try {
                const r = await removeExperimentalFramework(game.appId);
                toaster.toast({
                  title: r.ok
                    ? `${game.framework?.name} removed`
                    : "Nothing to remove",
                  body: r.ok ? `${r.removed ?? 0} files deleted` : r.error ?? "",
                });
                notifyGameStateChanged();
              } finally {
                setBusy(false);
              }
            }}
          >
            Remove {game.framework.name}
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          description="Stops treating this game as set up. Installed mods and loaders stay where they are; remove them first if you want them gone."
          onClick={async () => {
            setBusy(true);
            try {
              await removeExperimentalGame(game.appId);
              await loadExperimentalState();
            } finally {
              setBusy(false);
            }
          }}
        >
          Undo experimental setup
        </ButtonItem>
      </PanelSectionRow>
    </>
  );
}
