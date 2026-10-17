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
  ToggleField,
  showModal,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useState } from "react";

import {
  ExperimentalCandidate,
  applyExperimentalTool,
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
export function ExperimentalGameRows({ game }: { game: SupportedGame }) {
  const [busy, setBusy] = useState(false);
  if (!isExperimentalGame(game)) return null;
  return (
    <>
      <PanelSectionRow>
        <Field label="Mods folder">{game.modsSubdir}</Field>
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
