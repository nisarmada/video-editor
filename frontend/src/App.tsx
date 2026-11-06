import { useEffect, useState } from "react";
import MediaBin from "./components/MediaBin";
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
  const applyOperationInProgress = useTimelineStore(
    (s) => s.applyOperationInProgress,
  );
  const timelineBrief = useTimelineStore((s) => s.timeline?.brief);
  const selectedClipId = useTimelineStore((s) => s.selectedClipId);

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

  return (
    <div className="app">
      <header className="app-bar">
        <span className="app-bar__title">Video Editor</span>
        {plansListError && (
          <span className="app-bar__plan">{plansListError}</span>
        )}
        <select
          className="app-bar__btn"
          aria-label="Open plan"
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
          className="app-bar__btn"
          disabled={timelineLoading}
          onClick={() => void createNewPlan()}
        >
          New plan
        </button>
        <div className="app-bar__actions">
          <button
            type="button"
            className="app-bar__btn"
            disabled={!canSave}
            onClick={() => void savePlan()}
          >
            Save
          </button>
          <span className="app-bar__plan">{saveStatusLine}</span>
          <button
            type="button"
            className="app-bar__btn"
            disabled={!canExport}
            onClick={() => void exportPlan()}
          >
            Export
          </button>
          <span className="app-bar__plan">
            {rendering
              ? "Rendering..."
              : renderStatus === "error" && renderError
                ? renderError
                : renderStatus === "done" && outputDownloadUrl ? (
                  <a href={outputDownloadUrl}>Download</a>
                ) : null}
          </span>
          <button
            type="button"
            className="app-bar__btn"
            disabled={
              plannerRunning ||
              timelineLoading ||
              saving ||
              rendering ||
              applyOperationInProgress
            }
            onClick={() => setPlannerOpen((o) => !o)}
          >
            Planner…
          </button>
        </div>
      </header>

      {plannerOpen && (
        <div className="app-bar" role="region" aria-label="Planner">
          <label>
            Brief{" "}
            <input
              type="text"
              value={plannerBrief}
              onChange={(e) => setPlannerBrief(e.target.value)}
              disabled={plannerRunning}
            />
          </label>
          <label>
            Save as{" "}
            <input
              type="text"
              value={plannerSaveAs}
              onChange={(e) => setPlannerSaveAs(e.target.value)}
              placeholder="filename without path"
              disabled={plannerRunning}
            />
          </label>
          <button
            type="button"
            className="app-bar__btn"
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
          {plannerError && <span className="app-bar__plan">{plannerError}</span>}
        </div>
      )}

      <div className="upper-workspace">
        <MediaBin />

        <div className="resize-handle" aria-hidden title="Resize (coming soon)" />

        <section className="panel panel--preview" aria-label="Preview">
          <div className="panel__header">Preview — timeline (video track)</div>
          <div className="panel__body panel__body--preview">
            <TimelineVideoPreview />
          </div>
        </section>

        <div className="resize-handle" aria-hidden title="Resize (coming soon)" />

        <section className="panel panel--properties" aria-label="Properties">
          <div className="panel__header">Properties</div>
          <div className="panel__body">
            <div className="props-grid">
              <div className="props-row">
                <label>Plan name</label>
                <span>{currentPlanName}</span>
              </div>
              <div className="props-row">
                <label>Brief</label>
                <span>{timelineBrief ?? "—"}</span>
              </div>
              <div className="props-row">
                <label>Selection</label>
                <span>{selectedClipId ?? "None"}</span>
              </div>
            </div>
          </div>
        </section>
      </div>

      <div className="resize-handle resize-handle--horizontal" aria-hidden />

      <TimelinePanel />
    </div>
  );
}
