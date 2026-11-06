import { useEffect, useMemo, useState } from "react";
import { SHORTCUT_ACTIONS, getActionDefinition } from "../shortcuts/actions";
import type { BindingChord } from "../shortcuts/types";
import { useKeybindingsStore } from "../store/keybindingsStore";
import { useEditorSettingsStore } from "../store/editorSettingsStore";
import type { TargetMode } from "../shortcuts/types";
import { chordKey } from "../shortcuts/normalize";
import {
  getEffectiveBindings,
  getBindingState,
  buildChordToActionMap,
  validateImportOverrides,
} from "../shortcuts/merge";
import { formatChordForDisplay, isBarePrintableChord } from "../shortcuts/display";
import { reservedReason } from "../shortcuts/reserved";

function chordFromKeyboardEvent(e: KeyboardEvent): BindingChord | null {
  const ignore = new Set([
    "ShiftLeft",
    "ShiftRight",
    "ControlLeft",
    "ControlRight",
    "MetaLeft",
    "MetaRight",
    "AltLeft",
    "AltRight",
  ]);
  if (ignore.has(e.code)) return null;
  if (e.code === "Escape") return null;
  const mod = e.metaKey || e.ctrlKey;
  return {
    code: e.code,
    mod: mod || undefined,
    shift: e.shiftKey || undefined,
    alt: e.altKey || undefined,
  };
}

function chordEquals(a: BindingChord, b: BindingChord): boolean {
  return chordKey(a) === chordKey(b);
}

type CaptureState = { actionId: string; replaceIdx: number | null } | null;

type Props = {
  open: boolean;
  onClose: () => void;
};

export default function KeyboardShortcutsPanel({ open, onClose }: Props) {
  const overrides = useKeybindingsStore((s) => s.overrides);
  const setOverrides = useKeybindingsStore((s) => s.setOverrides);
  const shortcutTargeting = useEditorSettingsStore((s) => s.shortcutTargeting);
  const setShortcutUi = useEditorSettingsStore((s) => s.setUi);
  const timelineSnapEnabled = useEditorSettingsStore((s) => s.timelineSnapEnabled);
  const showCursorTimelineGuide = useEditorSettingsStore((s) => s.showCursorTimelineGuide);
  const cursorActionSelectsClip = useEditorSettingsStore((s) => s.cursorActionSelectsClip);
  const perActionTargetMode = useEditorSettingsStore((s) => s.perActionTargetMode);
  const setPerActionTargetMode = useEditorSettingsStore((s) => s.setPerActionTargetMode);
  const setActionBindings = useKeybindingsStore((s) => s.setActionBindings);
  const resetAction = useKeybindingsStore((s) => s.resetAction);
  const resetAll = useKeybindingsStore((s) => s.resetAll);
  const setCapture = useKeybindingsStore((s) => s.setShortcutCaptureActive);

  const [search, setSearch] = useState("");
  const [onlyCustom, setOnlyCustom] = useState(false);
  const [capture, setCaptureState] = useState<CaptureState>(null);
  const [note, setNote] = useState<string | null>(null);
  const [conflict, setConflict] = useState<{
    otherId: string;
    chord: BindingChord;
  } | null>(null);

  const cancelCapture = () => {
    setCaptureState(null);
    setNote(null);
    setConflict(null);
    setCapture(false);
  };

  useEffect(() => {
    if (!open || !capture) {
      setCapture(false);
      return;
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        cancelCapture();
        return;
      }
      e.preventDefault();
      e.stopPropagation();

      const ch = chordFromKeyboardEvent(e);
      if (!ch) return;

      const reserved = reservedReason(ch);
      if (reserved) {
        setNote(reserved);
        return;
      }

      const k = chordKey(ch);
      const other = buildChordToActionMap(useKeybindingsStore.getState().overrides).get(k);
      const { actionId, replaceIdx } = capture;
      if (other && other !== actionId) {
        setConflict({ otherId: other, chord: ch });
        const ol = getActionDefinition(other)?.label ?? other;
        setNote(`Conflict with "${ol}". Replace or Cancel.`);
        return;
      }

      const cur = [...getEffectiveBindings(actionId, useKeybindingsStore.getState().overrides)];
      const bare = isBarePrintableChord(ch);
      if (replaceIdx !== null && replaceIdx >= 0 && replaceIdx < cur.length) {
        cur[replaceIdx] = ch;
      } else {
        cur.push(ch);
      }
      setActionBindings(actionId, cur);
      if (bare) {
        setNote("Saved. Bare keys only fire when focus is outside text fields.");
        window.setTimeout(() => setNote(null), 4000);
      } else {
        setNote(null);
      }
      cancelCapture();
    };

    setCapture(true);
    setNote("Press new shortcut… (Esc to cancel)");
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      setCapture(false);
    };
  }, [open, capture, setActionBindings, setCapture]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return SHORTCUT_ACTIONS.filter((a) => {
      if (onlyCustom && getBindingState(a.id, overrides) === "default") return false;
      if (!q) return true;
      return (
        a.label.toLowerCase().includes(q) ||
        a.description.toLowerCase().includes(q) ||
        a.id.includes(q)
      );
    });
  }, [search, onlyCustom, overrides]);

  const byCat = useMemo(() => {
    const m = new Map<string, typeof filtered>();
    for (const a of filtered) {
      const list = m.get(a.category) ?? [];
      list.push(a);
      m.set(a.category, list);
    }
    return m;
  }, [filtered]);

  const startCapture = (actionId: string, replaceIdx: number | null) => {
    setConflict(null);
    setCaptureState({ actionId, replaceIdx });
  };

  const confirmReplace = () => {
    if (!capture || !conflict) return;
    const victim = conflict.otherId;
    const chord = conflict.chord;
    const victimChords = getEffectiveBindings(victim, overrides).filter(
      (c) => !chordEquals(c, chord),
    );
    setActionBindings(victim, victimChords);

    const target = capture.actionId;
    const cur = [...getEffectiveBindings(target, overrides)];
    const idx = capture.replaceIdx;
    if (idx !== null && idx >= 0 && idx < cur.length) {
      cur[idx] = chord;
    } else {
      cur.push(chord);
    }
    setActionBindings(target, cur);
    cancelCapture();
  };

  if (!open) return null;

  return (
    <div
      className="shortcut-overlay shortcut-overlay--wide"
      role="dialog"
      aria-modal
      aria-label="Keyboard shortcuts settings"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="shortcut-overlay__panel" onClick={(e) => e.stopPropagation()}>
        <div className="shortcut-overlay__head">
          <h2 className="shortcut-overlay__title">Keyboard shortcuts</h2>
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="shortcut-settings__toolbar">
          <input
            type="search"
            placeholder="Search…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search shortcuts"
          />
          <label>
            Shortcuts act on{" "}
            <select
              value={shortcutTargeting}
              onChange={(e) =>
                setShortcutUi({
                  shortcutTargeting: e.target.value as typeof shortcutTargeting,
                })
              }
            >
              <option value="cursor">Cursor (timeline)</option>
              <option value="playhead">Playhead</option>
              <option value="cursor_else_playhead">Cursor on timeline, else playhead</option>
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={timelineSnapEnabled}
              onChange={(e) => setShortcutUi({ timelineSnapEnabled: e.target.checked })}
            />{" "}
            Timeline snap (edges + playhead)
          </label>
          <label>
            <input
              type="checkbox"
              checked={showCursorTimelineGuide}
              onChange={(e) => setShortcutUi({ showCursorTimelineGuide: e.target.checked })}
            />{" "}
            Cursor guide line
          </label>
          <label>
            <input
              type="checkbox"
              checked={cursorActionSelectsClip}
              onChange={(e) => setShortcutUi({ cursorActionSelectsClip: e.target.checked })}
            />{" "}
            Cursor shortcuts select clip first
          </label>
          <label>
            <input
              type="checkbox"
              checked={onlyCustom}
              onChange={(e) => setOnlyCustom(e.target.checked)}
            />{" "}
            Only customized
          </label>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              if (window.confirm("Reset all shortcuts to defaults?")) resetAll();
            }}
          >
            Reset all
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              const blob = new Blob(
                [JSON.stringify({ keybindings: overrides }, null, 2)],
                { type: "application/json" },
              );
              const a = document.createElement("a");
              a.href = URL.createObjectURL(blob);
              a.download = "video-editor-keybindings.json";
              a.click();
              URL.revokeObjectURL(a.href);
            }}
          >
            Export JSON
          </button>
          <label className="btn btn--ghost" style={{ cursor: "pointer" }}>
            Import JSON
            <input
              type="file"
              accept="application/json,.json"
              className="sr-only"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (!f) return;
                void f.text().then((text) => {
                  try {
                    const j = JSON.parse(text) as unknown;
                    const { overrides: next, unknownIds } = validateImportOverrides(j);
                    if (unknownIds.length) {
                      window.alert(`Unknown action ids ignored: ${unknownIds.join(", ")}`);
                    }
                    setOverrides({
                      ...useKeybindingsStore.getState().overrides,
                      ...next,
                    });
                  } catch {
                    window.alert("Invalid JSON");
                  }
                });
              }}
            />
          </label>
        </div>

        {note && <p className="shortcut-settings__note">{note}</p>}
        {conflict && (
          <div className="shortcut-settings__conflict">
            <button type="button" className="btn btn--primary" onClick={confirmReplace}>
              Replace
            </button>
            <button type="button" className="btn btn--ghost" onClick={cancelCapture}>
              Cancel
            </button>
          </div>
        )}

        <div className="shortcut-settings__body">
          {[...byCat.entries()].map(([cat, actions]) => (
            <section key={cat}>
              <h3 className="shortcut-overlay__cat">{cat}</h3>
              <ul className="shortcut-settings__actions">
                {actions.map((a) => {
                  const eff = getEffectiveBindings(a.id, overrides);
                  const state = getBindingState(a.id, overrides);
                  return (
                    <li key={a.id} className="shortcut-settings__action">
                      <div>
                        <span className="shortcut-settings__label">
                          {state === "customized" && <span title="Customized">* </span>}
                          {a.label}
                        </span>
                        <span className="shortcut-settings__desc">{a.description}</span>
                      </div>
                      <div className="shortcut-settings__chips">
                        {eff.length === 0 ? (
                          <span className="shortcut-settings__unassigned">Unassigned</span>
                        ) : (
                          eff.map((c, i) => (
                            <button
                              key={`${a.id}-${chordKey(c)}-${i}`}
                              type="button"
                              className="shortcut-settings__chip"
                              onClick={() => startCapture(a.id, i)}
                              title="Click to change"
                            >
                              {formatChordForDisplay(c)}
                              <span
                                className="shortcut-settings__chip-x"
                                onClick={(ev) => {
                                  ev.stopPropagation();
                                  const next = eff.filter((_, j) => j !== i);
                                  setActionBindings(a.id, next);
                                }}
                              >
                                {" "}
                                ×
                              </span>
                            </button>
                          ))
                        )}
                        <button
                          type="button"
                          className="shortcut-settings__add"
                          onClick={() => startCapture(a.id, null)}
                          title="Add binding"
                        >
                          +
                        </button>
                        <label className="shortcut-settings__target">
                          Target:{" "}
                          <select
                            value={perActionTargetMode[a.id] ?? ""}
                            onChange={(e) => {
                              const v = e.target.value;
                              if (!v) setPerActionTargetMode(a.id, undefined);
                              else setPerActionTargetMode(a.id, v as TargetMode);
                            }}
                          >
                            <option value="">Default ({a.targetMode})</option>
                            <option value="cursor">cursor</option>
                            <option value="playhead">playhead</option>
                            <option value="selection">selection</option>
                            <option value="global">global</option>
                          </select>
                        </label>
                        <button
                          type="button"
                          className="btn btn--ghost shortcut-settings__reset"
                          onClick={() => resetAction(a.id)}
                        >
                          Reset
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
