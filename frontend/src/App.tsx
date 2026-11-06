import { useEffect, useState } from "react";
import AssetCategoryStrip from "./components/AssetCategoryStrip";
import ClipDetails from "./components/ClipDetails";
import ExportBar from "./components/ExportBar";
import LogsPanel from "./components/LogsPanel";
import MediaBin from "./components/MediaBin";
import OutputManagerPanel from "./components/OutputManagerPanel";
import SettingsPanel from "./components/SettingsPanel";
import SourcePreview from "./components/SourcePreview";
import TimelineVideoPreview from "./components/TimelineVideoPreview";
import TimelinePanel from "./components/TimelinePanel";
import { useTimelineStore } from "./store/timelineStore";
import "./App.css";

export default function App() {
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

  const plannerRunning = useTimelineStore((s) => s.plannerRunning);
  const plannerError = useTimelineStore((s) => s.plannerError);
  const runPlannerJob = useTimelineStore((s) => s.runPlannerJob);

  const [plannerOpen, setPlannerOpen] = useState(false);
  const [plannerBrief, setPlannerBrief] = useState("");
  const [plannerSaveAs, setPlannerSaveAs] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [outputOpen, setOutputOpen] = useState(false);
  const [logsExpanded, setLogsExpanded] = useState(false);

  useEffect(() => {
    if (currentPlanName) {
      setPlannerSaveAs((prev) => prev || currentPlanName);
    }
  }, [currentPlanName]);

  useEffect(() => {
    void initSession();
  }, [initSession]);

  const selectPlanValue =
    currentPlanName && availablePlans.includes(currentPlanName)
      ? currentPlanName
      : "";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.metaKey && !e.ctrlKey) return;
      if (e.key.toLowerCase() !== "s") return;
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.tagName === "SELECT" ||
          t.isContentEditable)
      ) {
        return;
      }
      if (!canSave) return;
      e.preventDefault();
      void savePlan();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canSave, savePlan]);

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
            onClick={() => setSettingsOpen(true)}
          >
            Settings
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={
              plannerRunning ||
              timelineLoading ||
              saving ||
              rendering ||
              applyOperationInProgress
            }
            onClick={() => setPlannerOpen((o) => !o)}
          >
            AI planner…
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

      {plannerOpen && (
        <div className="planner-bar" role="region" aria-label="Planner">
          <label className="planner-bar__field">
            Brief{" "}
            <input
              type="text"
              value={plannerBrief}
              onChange={(e) => setPlannerBrief(e.target.value)}
              disabled={plannerRunning}
            />
          </label>
          <label className="planner-bar__field">
            Save as{" "}
            <input
              type="text"
              value={plannerSaveAs}
              onChange={(e) => setPlannerSaveAs(e.target.value)}
              placeholder="stem, no .json"
              disabled={plannerRunning}
            />
          </label>
          <button
            type="button"
            className="btn btn--primary"
            disabled={
              plannerRunning ||
              timelineLoading ||
              saving ||
              rendering ||
              applyOperationInProgress
            }
            onClick={() =>
              void runPlannerJob(plannerBrief, plannerSaveAs || currentPlanName)
            }
          >
            {plannerRunning ? "Running…" : "Run planner"}
          </button>
          {plannerError && <span className="planner-bar__error">{plannerError}</span>}
        </div>
      )}

      <div className="editor-workspace">
        <div className="editor-workspace__upper">
          <div className="col col--media">
            <AssetCategoryStrip />
            <MediaBin />
          </div>
          <section className="panel panel--player" aria-label="Player">
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
          <section className="panel panel--details" aria-label="Details">
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

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <OutputManagerPanel open={outputOpen} onClose={() => setOutputOpen(false)} />
    </div>
  );
}
