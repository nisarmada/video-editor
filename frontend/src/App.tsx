import { useEffect, useState } from "react";
import AssetCategoryStrip from "./components/AssetCategoryStrip";
import ClipDetails from "./components/ClipDetails";
import ExportBar from "./components/ExportBar";
import AICommandBar from "./components/AICommandBar";
import LogsPanel from "./components/LogsPanel";
import MediaBin from "./components/MediaBin";
import OutputManagerPanel from "./components/OutputManagerPanel";
import SettingsPanel from "./components/SettingsPanel";
import SourcePreview from "./components/SourcePreview";
import TimelineVideoPreview from "./components/TimelineVideoPreview";
import TimelinePanel from "./components/TimelinePanel";
import KeyboardShortcutsPanel from "./components/KeyboardShortcutsPanel";
import ShortcutCheatSheet from "./components/ShortcutCheatSheet";
import { updateCursorContextPartial } from "./store/cursorContextStore";
import { useShortcuts } from "./hooks/useShortcuts";
import { getBindingTitle } from "./shortcuts/tooltip";
import { useKeybindingsStore } from "./store/keybindingsStore";
import { useTimelineStore } from "./store/timelineStore";
import "./App.css";

export default function App() {
  useShortcuts();

  const currentPlanName = useTimelineStore((s) => s.currentPlanName);
  const availablePlans = useTimelineStore((s) => s.availablePlans);
  const plansListError = useTimelineStore((s) => s.plansListError);
  const initSession = useTimelineStore((s) => s.initSession);
  const loadPlan = useTimelineStore((s) => s.loadPlan);
  const createNewPlan = useTimelineStore((s) => s.createNewPlan);
  const timeline = useTimelineStore((s) => s.timeline);
  const timelineLoading = useTimelineStore((s) => s.timelineLoading);
  const isDirty = useTimelineStore((s) => s.isDirty);
  const saveStatus = useTimelineStore((s) => s.saveStatus);
  const saveError = useTimelineStore((s) => s.saveError);
  const savePlan = useTimelineStore((s) => s.savePlan);
  const exportPlan = useTimelineStore((s) => s.exportPlan);
  const renderStatus = useTimelineStore((s) => s.renderStatus);
  const renderError = useTimelineStore((s) => s.renderError);
  const outputDownloadUrl = useTimelineStore((s) => s.outputDownloadUrl);
  const uiBannerError = useTimelineStore((s) => s.uiBannerError);
  const clearUiBanner = useTimelineStore((s) => s.clearUiBanner);
  const renamePlanFile = useTimelineStore((s) => s.renamePlanFile);
  const duplicatePlanFile = useTimelineStore((s) => s.duplicatePlanFile);
  const deletePlanFile = useTimelineStore((s) => s.deletePlanFile);
  const applyOperationInProgress = useTimelineStore(
    (s) => s.applyOperationInProgress,
  );
  const previewPanelMode = useTimelineStore((s) => s.previewPanelMode);
  const setPreviewPanelMode = useTimelineStore((s) => s.setPreviewPanelMode);
  const saving = saveStatus === "saving";
  const canSave =
    Boolean(timeline && currentPlanName) && isDirty && !saving && !timelineLoading;
  const rendering = renderStatus === "rendering";
  const canExport =
    Boolean(timeline && currentPlanName) &&
    !timelineLoading &&
    !rendering &&
    !saving &&
    !applyOperationInProgress;

  const [settingsOpen, setSettingsOpen] = useState(false);
  const keyboardShortcutsOpen = useKeybindingsStore((s) => s.keyboardSettingsOpen);
  const setKeyboardShortcutsOpen = useKeybindingsStore(
    (s) => s.setKeyboardSettingsOpen,
  );
  const kbOverrides = useKeybindingsStore((s) => s.overrides);
  const cheatSheetOpen = useKeybindingsStore((s) => s.cheatSheetOpen);
  const setCheatSheetOpen = useKeybindingsStore((s) => s.setCheatSheetOpen);
  const [outputOpen, setOutputOpen] = useState(false);
  const [logsExpanded, setLogsExpanded] = useState(false);

  useEffect(() => {
    void initSession();
  }, [initSession]);

  const selectPlanValue =
    currentPlanName && availablePlans.includes(currentPlanName)
      ? currentPlanName
      : "";

  useEffect(() => {
    if (!isDirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [isDirty]);

  const saveStatusLine =
    saveStatus === "error" && saveError
      ? `Save failed: ${saveError}`
      : saveStatus;

  const displayProjectName = currentPlanName || "Untitled";
  const saveTitle = getBindingTitle("save_plan", kbOverrides);
  const exportTitle = getBindingTitle("export_render", kbOverrides);

  return (
    <div className="app">
      <header className="top-bar">
        <div className="top-bar__left">
          <span className="top-bar__logo">Editor</span>
          <span className="top-bar__project" title="Active plan">
            {displayProjectName}
            {isDirty && <span className="top-bar__dirty" aria-label="unsaved" />}
          </span>
        </div>
        <div className="top-bar__center">
          <select
            className="top-bar__select"
            aria-label="Project file"
            value={selectPlanValue}
            disabled={timelineLoading || availablePlans.length === 0}
            onChange={(e) => {
              const v = e.target.value;
              if (v) void loadPlan(v);
            }}
          >
            {availablePlans.length === 0 ? (
              <option value="">No plans</option>
            ) : (
              availablePlans.map((stem) => (
                <option key={stem} value={stem}>
                  {stem}.json
                </option>
              ))
            )}
          </select>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={timelineLoading}
            onClick={() => void createNewPlan()}
          >
            New
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!currentPlanName || timelineLoading}
            title="Rename this plan file on disk"
            onClick={() => {
              const next = window.prompt(
                "New plan name (no .json):",
                currentPlanName,
              );
              if (next == null) return;
              void renamePlanFile(currentPlanName, next);
            }}
          >
            Rename
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!currentPlanName || timelineLoading}
            onClick={() => {
              const next = window.prompt("Duplicate as (stem, no .json):");
              if (next == null) return;
              void duplicatePlanFile(currentPlanName, next);
            }}
          >
            Duplicate
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!currentPlanName || timelineLoading}
            onClick={() => void deletePlanFile(currentPlanName)}
          >
            Delete
          </button>
          {plansListError && (
            <span className="top-bar__warn">{plansListError}</span>
          )}
        </div>
        <div className="top-bar__right">
          <span className="na-chip na-chip--compact" title="Not implemented">
            Share
          </span>
          <button
            type="button"
            className="btn btn--primary"
            disabled={!canSave}
            title={saveTitle}
            onClick={() => void savePlan()}
          >
            Save
          </button>
          <span className="top-bar__status" title="Save state">
            {saveStatusLine}
          </span>
          <button
            type="button"
            className="btn btn--export"
            disabled={!canExport}
            title={exportTitle}
            onClick={() => void exportPlan()}
          >
            Export
          </button>
          <span className="top-bar__render">
            {rendering ? "Export running…" : null}
            {!rendering &&
            renderStatus === "done" &&
            outputDownloadUrl ? (
              <a href={outputDownloadUrl} className="top-bar__download">
                Download
              </a>
            ) : null}
            {!rendering && renderStatus === "error" && renderError ? (
              <span className="top-bar__warn" title={renderError}>
                Export failed
              </span>
            ) : null}
          </span>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => setOutputOpen(true)}
          >
            Output…
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            title={getBindingTitle("open_keyboard_settings", kbOverrides)}
            onClick={() => setKeyboardShortcutsOpen(true)}
          >
            Keyboard
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => setSettingsOpen(true)}
          >
            Settings
          </button>
        </div>
      </header>

      {uiBannerError && (
        <div className="app-banner app-banner--error" role="alert">
          <span>{uiBannerError}</span>
          <button
            type="button"
            className="btn btn--ghost app-banner__dismiss"
            onClick={() => clearUiBanner()}
          >
            Dismiss
          </button>
        </div>
      )}

      <ExportBar />

      <AICommandBar />

      <div className="editor-workspace">
        <div className="editor-workspace__upper">
          <div
            className="col col--media"
            data-cursor-region="mediaBin"
            onPointerEnter={() => {
              const coarse = window.matchMedia("(pointer: coarse)").matches;
              updateCursorContextPartial({
                region: "mediaBin",
                hasFinePointer: !coarse,
              });
            }}
            onPointerLeave={() =>
              updateCursorContextPartial({ region: "none", hasFinePointer: false })
            }
          >
            <AssetCategoryStrip />
            <MediaBin />
          </div>
          <section
            className="panel panel--player"
            aria-label="Player"
            data-cursor-region="preview"
            onPointerEnter={() => {
              const coarse = window.matchMedia("(pointer: coarse)").matches;
              updateCursorContextPartial({
                region: "preview",
                hasFinePointer: !coarse,
              });
            }}
            onPointerLeave={() =>
              updateCursorContextPartial({ region: "none", hasFinePointer: false })
            }
          >
            <div className="panel__header panel__header--player">
              <span>Player</span>
              <div
                className="preview-mode-toggle"
                role="group"
                aria-label="Preview mode"
              >
                <button
                  type="button"
                  className={`btn btn--segment${previewPanelMode === "timeline" ? " btn--segment-active" : ""}`}
                  aria-pressed={previewPanelMode === "timeline"}
                  onClick={() => setPreviewPanelMode("timeline")}
                >
                  Timeline
                </button>
                <button
                  type="button"
                  className={`btn btn--segment${previewPanelMode === "source" ? " btn--segment-active" : ""}`}
                  aria-pressed={previewPanelMode === "source"}
                  onClick={() => setPreviewPanelMode("source")}
                >
                  Source
                </button>
              </div>
            </div>
            <div className="panel__body panel__body--preview">
              {previewPanelMode === "timeline" ? (
                <TimelineVideoPreview />
              ) : (
                <SourcePreview />
              )}
            </div>
          </section>
          <section
            className="panel panel--details"
            aria-label="Details"
            data-cursor-region="details"
            onPointerEnter={() => {
              const coarse = window.matchMedia("(pointer: coarse)").matches;
              updateCursorContextPartial({
                region: "details",
                hasFinePointer: !coarse,
              });
            }}
            onPointerLeave={() =>
              updateCursorContextPartial({ region: "none", hasFinePointer: false })
            }
          >
            <div className="panel__header">Details</div>
            <div className="panel__body panel__body--details">
              <ClipDetails />
            </div>
          </section>
        </div>

        <TimelinePanel />
      </div>

      <LogsPanel
        expanded={logsExpanded}
        onToggle={() => setLogsExpanded((x) => !x)}
      />

      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onOpenKeyboardShortcuts={() => setKeyboardShortcutsOpen(true)}
      />
      <KeyboardShortcutsPanel
        open={keyboardShortcutsOpen}
        onClose={() => setKeyboardShortcutsOpen(false)}
      />
      <ShortcutCheatSheet open={cheatSheetOpen} onClose={() => setCheatSheetOpen(false)} />
      <OutputManagerPanel open={outputOpen} onClose={() => setOutputOpen(false)} />
    </div>
  );
}
