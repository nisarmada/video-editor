import { useEffect, useRef, useState } from "react";
import {
  estimatePlanner,
  formatPlannerEstimate,
  formatPlannerEstimateNotes,
  requestFootageAnalyze,
  type PlannerEstimate,
} from "../api/planner";
import { analyzeStyle } from "../api/styles";
import { useTimelineStore } from "../store/timelineStore";
import { nextAutoPlanStem } from "../utils/planStem";

type FootageScope = "all" | "selected";
type PlannerMode = "draft" | "full";

const PLANNER_BAR_COLLAPSED_KEY = "video-editor:plannerBarCollapsed";

export default function AICommandBar() {
  const timelineLoading = useTimelineStore((s) => s.timelineLoading);
  const saving = useTimelineStore((s) => s.saveStatus === "saving");
  const rendering = useTimelineStore((s) => s.renderStatus === "rendering");
  const applyOperationInProgress = useTimelineStore(
    (s) => s.applyOperationInProgress,
  );

  const plannerRunning = useTimelineStore((s) => s.plannerRunning);
  const plannerError = useTimelineStore((s) => s.plannerError);
  const plannerPhase = useTimelineStore((s) => s.plannerPhase);
  const plannerProgressMessage = useTimelineStore(
    (s) => s.plannerProgressMessage,
  );
  const plannerSuccessSummary = useTimelineStore(
    (s) => s.plannerSuccessSummary,
  );
  const plannerUnanalyzed = useTimelineStore((s) => s.plannerUnanalyzed);

  const selectedFootageNames = useTimelineStore((s) => s.selectedFootageNames);
  const availablePlans = useTimelineStore((s) => s.availablePlans);
  const runPlannerJob = useTimelineStore((s) => s.runPlannerJob);
  const styleProfiles = useTimelineStore((s) => s.styleProfiles);
  const refreshStyleProfiles = useTimelineStore((s) => s.refreshStyleProfiles);

  const [brief, setBrief] = useState("");
  const [saveAsTouched, setSaveAsTouched] = useState(false);
  const [saveAs, setSaveAs] = useState(() => nextAutoPlanStem([]));
  const [footageScope, setFootageScope] = useState<FootageScope>("all");
  const [plannerMode, setPlannerMode] = useState<PlannerMode>("draft");
  const [analyzeNote, setAnalyzeNote] = useState<string | null>(null);
  const [barCollapsed, setBarCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(PLANNER_BAR_COLLAPSED_KEY) === "1";
  });
  const [imitateStyleId, setImitateStyleId] = useState("");
  const [styleUploadBusy, setStyleUploadBusy] = useState(false);
  const [styleUploadError, setStyleUploadError] = useState<string | null>(null);
  const [liveEstimate, setLiveEstimate] = useState<PlannerEstimate | null>(null);
  const [liveEstimateLoading, setLiveEstimateLoading] = useState(false);
  const [liveEstimateError, setLiveEstimateError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (saveAsTouched) return;
    setSaveAs(nextAutoPlanStem(availablePlans));
  }, [availablePlans, saveAsTouched]);

  useEffect(() => {
    if (plannerMode !== "draft") {
      setLiveEstimate(null);
      setLiveEstimateError("Estimates are for Draft mode only.");
      return;
    }
    if (footageScope === "selected" && selectedFootageNames.length === 0) {
      setLiveEstimate(null);
      setLiveEstimateError(
        "Select clips in the media bin (Shift+click) to see an estimate.",
      );
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLiveEstimateLoading(true);
      setLiveEstimateError(null);
      void estimatePlanner({
        brief,
        ...(footageScope === "selected"
          ? { clip_filenames: selectedFootageNames }
          : {}),
        ...(imitateStyleId ? { imitate_style_id: imitateStyleId } : {}),
      })
        .then((est) => {
          if (cancelled) return;
          setLiveEstimate(est);
          setLiveEstimateError(null);
        })
        .catch((e: unknown) => {
          if (cancelled) return;
          setLiveEstimate(null);
          setLiveEstimateError(
            e instanceof Error ? e.message : "Could not estimate planner cost.",
          );
        })
        .finally(() => {
          if (!cancelled) setLiveEstimateLoading(false);
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    brief,
    footageScope,
    selectedFootageNames,
    imitateStyleId,
    plannerMode,
  ]);

  const blocked =
    timelineLoading ||
    saving ||
    rendering ||
    applyOperationInProgress;

  const canSubmit =
    Boolean(brief.trim()) &&
    Boolean(saveAs.trim()) &&
    !blocked &&
    !plannerRunning &&
    !styleUploadBusy &&
    (footageScope === "all" || selectedFootageNames.length > 0);

  function setCollapsed(next: boolean) {
    setBarCollapsed(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(PLANNER_BAR_COLLAPSED_KEY, next ? "1" : "0");
    }
  }

  const processStyleFile = async (file: File | undefined) => {
    if (!file) return;
    setStyleUploadError(null);
    setStyleUploadBusy(true);
    try {
      const base = file.name.replace(/\.[^/.]+$/, "") || "reference";
      const res = await analyzeStyle(file, { style_name: base });
      await refreshStyleProfiles();
      setImitateStyleId(res.style_id);
      setStyleUploadError(null);
    } catch (e) {
      setStyleUploadError(e instanceof Error ? e.message : "Style analysis failed");
    } finally {
      setStyleUploadBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  if (barCollapsed) {
    return (
      <section
        className="ai-command-bar ai-command-bar--collapsed"
        role="region"
        aria-label="Edit planner"
      >
        <div className="ai-command-bar__collapsed">
          <button
            type="button"
            className="btn btn--ghost ai-command-bar__expand"
            aria-expanded={false}
            onClick={() => setCollapsed(false)}
          >
            Show planner bar
          </button>
        </div>
      </section>
    );
  }

  return (
    <section
      className="ai-command-bar"
      role="region"
      aria-label="Edit planner"
    >
      <div className="ai-command-bar__top-tools">
        <button
          type="button"
          className="btn btn--ghost ai-command-bar__hide"
          aria-expanded
          title="Hide this bar — scroll the page or use Show planner bar"
          onClick={() => setCollapsed(true)}
        >
          Hide bar
        </button>
      </div>
      <div className="ai-command-bar__inner">
        <div className="ai-command-bar__row">
          <div className="ai-command-bar__prompt-block">
            <label className="ai-command-bar__prompt">
              <input
                type="text"
                className="ai-command-bar__input"
                placeholder='Describe the edit you want to build... e.g., "Create a 30-second fast-paced highlight reel with background music and captions"'
                value={brief}
                onChange={(e) => setBrief(e.target.value)}
                disabled={plannerRunning}
                autoComplete="off"
                aria-label="Edit brief"
              />
            </label>
            <p className="ai-command-bar__hint">
              Draft builds from analyzed files in{" "}
              <code className="media-bin-code">footage/</code> (Use: All clips or
              bin selection). An empty timeline is fine.
            </p>
            <div
              className="ai-command-bar__estimate"
              aria-live="polite"
              data-loading={liveEstimateLoading ? "1" : undefined}
            >
              {liveEstimateLoading && !liveEstimate && !liveEstimateError && (
                <span className="ai-command-bar__hint">Estimating catalog…</span>
              )}
              {liveEstimateError && (
                <span className="ai-command-bar__hint">{liveEstimateError}</span>
              )}
              {liveEstimate && (
                <>
                  <span className="ai-command-bar__estimate-main">
                    {formatPlannerEstimate(liveEstimate)}
                    {liveEstimate.model ? ` · ${liveEstimate.model}` : ""}
                  </span>
                  {formatPlannerEstimateNotes(liveEstimate).map((line) => (
                    <span key={line} className="ai-command-bar__hint">
                      {line}
                    </span>
                  ))}
                </>
              )}
            </div>
          </div>
          <div className="ai-command-bar__secondary">
            <label className="ai-command-bar__save">
              <span className="ai-command-bar__label">Save as</span>
              <input
                type="text"
                className="ai-command-bar__input ai-command-bar__input--stem"
                placeholder="new plan name"
                value={saveAs}
                onChange={(e) => {
                  setSaveAsTouched(true);
                  setSaveAs(e.target.value);
                }}
                disabled={plannerRunning}
                title="New plan file unless this name already exists"
              />
            </label>
            <div
              className="ai-command-bar__scope"
              role="group"
              aria-label="Footage scope"
            >
              <span className="ai-command-bar__label">Use</span>
              <div className="ai-command-bar__segment">
                <button
                  type="button"
                  className={`btn btn--segment${footageScope === "all" ? " btn--segment-active" : ""}`}
                  aria-pressed={footageScope === "all"}
                  disabled={plannerRunning}
                  onClick={() => setFootageScope("all")}
                >
                  All clips
                </button>
                <button
                  type="button"
                  className={`btn btn--segment${footageScope === "selected" ? " btn--segment-active" : ""}`}
                  aria-pressed={footageScope === "selected"}
                  disabled={plannerRunning}
                  onClick={() => setFootageScope("selected")}
                  title="Shift+click clips in the media bin to add to selection"
                >
                  Selected ({selectedFootageNames.length})
                </button>
              </div>
            </div>
            <div className="ai-command-bar__scope" role="group" aria-label="Planner mode">
              <span className="ai-command-bar__label">Mode</span>
              <div className="ai-command-bar__segment">
                <button
                  type="button"
                  className={`btn btn--segment${plannerMode === "draft" ? " btn--segment-active" : ""}`}
                  aria-pressed={plannerMode === "draft"}
                  disabled={plannerRunning}
                  onClick={() => setPlannerMode("draft")}
                >
                  Draft
                </button>
                <button
                  type="button"
                  className={`btn btn--segment${plannerMode === "full" ? " btn--segment-active" : ""}`}
                  aria-pressed={plannerMode === "full"}
                  disabled={plannerRunning}
                  title="Not available yet. Draft is one compact call."
                  onClick={() => setPlannerMode("full")}
                >
                  Full
                </button>
              </div>
            </div>
            <div className="ai-command-bar__styles" role="group" aria-label="Style reference">
              <label className="ai-command-bar__style-field">
                <span className="ai-command-bar__label">Imitate style</span>
                <select
                  className="ai-command-bar__select"
                  value={imitateStyleId}
                  onChange={(e) => setImitateStyleId(e.target.value)}
                  disabled={plannerRunning || styleUploadBusy}
                  title="Planner mirrors cut pacing and visuals from this profile"
                >
                  <option value="">— None —</option>
                  {styleProfiles.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
              <div
                className={`ai-command-bar__dropzone${styleUploadBusy ? " ai-command-bar__dropzone--busy" : ""}`}
                onDragOver={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  const f = e.dataTransfer.files?.[0];
                  void processStyleFile(f);
                }}
                onClick={() => fileInputRef.current?.click()}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    fileInputRef.current?.click();
                  }
                }}
                role="button"
                tabIndex={0}
                title="Drop a reference MP4 here or click to upload"
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="video/*"
                  className="ai-command-bar__file"
                  aria-hidden
                  tabIndex={-1}
                  onChange={(e) => void processStyleFile(e.target.files?.[0])}
                />
                {styleUploadBusy ? "Analyzing reference…" : "Drop reference video"}
              </div>
            </div>
            <button
              type="button"
              className="btn btn--primary ai-command-bar__submit"
              disabled={!canSubmit}
              title={
                footageScope === "selected" && selectedFootageNames.length === 0
                  ? "Select clips in the media bin with Shift+click"
                  : undefined
              }
              onClick={() =>
                void runPlannerJob(brief, saveAs, {
                  footageScope,
                  clipNames:
                    footageScope === "selected"
                      ? selectedFootageNames
                      : undefined,
                  imitateStyleId: imitateStyleId || null,
                  mode: plannerMode,
                })
              }
            >
              {plannerRunning ? (
                <>
                  <span className="ai-command-bar__spinner" aria-hidden />
                  Generating…
                </>
              ) : (
                "Generate"
              )}
            </button>
          </div>
        </div>
        {(plannerRunning ||
          plannerError ||
          plannerSuccessSummary ||
          styleUploadError ||
          analyzeNote ||
          plannerUnanalyzed.length > 0) && (
          <div className="ai-command-bar__status">
            {plannerRunning && plannerProgressMessage && (
              <span className="ai-command-bar__progress">
                {plannerProgressMessage}
              </span>
            )}
            {plannerRunning && plannerPhase === "planning" && (
              <span className="ai-command-bar__hint">
                Draft mode sends a short catalog and makes one model call.
              </span>
            )}
            {plannerUnanalyzed.length > 0 && !plannerRunning && (
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => {
                  const names = plannerUnanalyzed;
                  if (
                    typeof window !== "undefined" &&
                    !window.confirm(
                      `Analyze ${names.length} file(s) now? Video that still needs frame captions can call the paid caption API.`,
                    )
                  ) {
                    return;
                  }
                  setAnalyzeNote(null);
                  void requestFootageAnalyze({ names })
                    .then((res) => {
                      setAnalyzeNote(
                        `Queued analysis for ${res.queued.length} file(s). Generate again when it finishes.`,
                      );
                    })
                    .catch((e: unknown) => {
                      setAnalyzeNote(
                        e instanceof Error ? e.message : "Could not queue analysis.",
                      );
                    });
                }}
              >
                Analyze now ({plannerUnanalyzed.length})
              </button>
            )}
            {analyzeNote && (
              <span className="ai-command-bar__hint">{analyzeNote}</span>
            )}
            {(plannerError || styleUploadError) && (
              <span className="ai-command-bar__error" role="alert">
                {styleUploadError ?? plannerError}
              </span>
            )}
            {!plannerRunning && plannerSuccessSummary && !plannerError && (
              <span className="ai-command-bar__ok">{plannerSuccessSummary}</span>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
