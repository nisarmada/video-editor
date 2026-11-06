import { useEffect, useState } from "react";
import { useTimelineStore } from "../store/timelineStore";

type FootageScope = "all" | "selected";

export default function AICommandBar() {
  const currentPlanName = useTimelineStore((s) => s.currentPlanName);
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

  const selectedFootageNames = useTimelineStore((s) => s.selectedFootageNames);
  const runPlannerJob = useTimelineStore((s) => s.runPlannerJob);

  const [brief, setBrief] = useState("");
  const [saveAs, setSaveAs] = useState("");
  const [footageScope, setFootageScope] = useState<FootageScope>("all");

  useEffect(() => {
    if (currentPlanName) {
      setSaveAs((prev) => prev || currentPlanName);
    }
  }, [currentPlanName]);

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
    (footageScope === "all" || selectedFootageNames.length > 0);

  return (
    <section
      className="ai-command-bar"
      role="region"
      aria-label="AI assistant"
    >
      <div className="ai-command-bar__inner">
        <div className="ai-command-bar__head">
          <h2 className="ai-command-bar__title">AI Assistant</h2>
          <p className="ai-command-bar__subtitle">
            Describe the edit you want — we generate a timeline from your indexed footage.
          </p>
        </div>
        <div className="ai-command-bar__row">
          <label className="ai-command-bar__prompt">
            <span className="ai-command-bar__label">Prompt</span>
            <input
              type="text"
              className="ai-command-bar__input"
              placeholder='Describe the edit you want to build... e.g., "Create a 30-second fast-paced highlight reel with background music and captions"'
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              disabled={plannerRunning}
              autoComplete="off"
            />
          </label>
          <div className="ai-command-bar__secondary">
            <label className="ai-command-bar__save">
              <span className="ai-command-bar__label">Save as</span>
              <input
                type="text"
                className="ai-command-bar__input ai-command-bar__input--stem"
                placeholder="plan name (no .json)"
                value={saveAs}
                onChange={(e) => setSaveAs(e.target.value)}
                disabled={plannerRunning}
                title="Plan file stem; overwrites if it already exists"
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
                void runPlannerJob(brief, saveAs || currentPlanName, {
                  footageScope,
                  clipNames:
                    footageScope === "selected"
                      ? selectedFootageNames
                      : undefined,
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
        {(plannerRunning || plannerError || plannerSuccessSummary) && (
          <div className="ai-command-bar__status">
            {plannerRunning && plannerProgressMessage && (
              <span className="ai-command-bar__progress">
                {plannerProgressMessage}
              </span>
            )}
            {plannerRunning && plannerPhase === "planning" && (
              <span className="ai-command-bar__hint">
                This may take a minute while the model reads your transcripts and
                indexes.
              </span>
            )}
            {plannerError && (
              <span className="ai-command-bar__error" role="alert">
                {plannerError}
              </span>
            )}
            {!plannerRunning && plannerSuccessSummary && !plannerError && (
              <span className="ai-command-bar__ok">{plannerSuccessSummary}</span>
            )}
          </div>
        )}
        <p className="ai-command-bar__help">
          Media bin: Shift+click to pick multiple clips for “Selected”. Undo the
          result with{" "}
          <kbd className="ai-command-bar__kbd">⌘Z</kbd> /{" "}
          <kbd className="ai-command-bar__kbd">Ctrl+Z</kbd> when saving over the
          active plan.
        </p>
      </div>
    </section>
  );
}
