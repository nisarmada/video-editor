import { useTimelineStore } from "../store/timelineStore";

/** In-document bar while GET /api/render/{id} is polled. */
export default function ExportBar() {
  const renderStatus = useTimelineStore((s) => s.renderStatus);
  const renderJob = useTimelineStore((s) => s.renderJob);
  const renderLogVisible = useTimelineStore((s) => s.renderLogVisible);
  const outputDownloadUrl = useTimelineStore((s) => s.outputDownloadUrl);
  const outputName = useTimelineStore((s) => s.outputName);
  const renderError = useTimelineStore((s) => s.renderError);
  const cancelExport = useTimelineStore((s) => s.cancelExport);
  const setRenderLogVisible = useTimelineStore((s) => s.setRenderLogVisible);
  const revealOutputInFinder = useTimelineStore((s) => s.revealOutputInFinder);

  if (
    renderStatus !== "rendering" &&
    renderStatus !== "done" &&
    renderStatus !== "error"
  ) {
    return null;
  }

  const pct =
    renderJob?.percent != null ? Math.round(renderJob.percent) : null;
  const stateLabel = renderJob?.state ?? renderStatus;

  return (
    <div className="export-bar" role="status" aria-live="polite">
      <div className="export-bar__row">
        <span className="export-bar__label">
          Export{" "}
          {renderStatus === "rendering"
            ? `— ${stateLabel}${pct != null ? ` ${pct}%` : ""}`
            : renderStatus === "done"
              ? "complete"
              : "failed"}
        </span>
        {renderStatus === "rendering" && (
          <>
            <div className="export-bar__track" aria-hidden>
              <div
                className="export-bar__fill"
                style={{ width: `${Math.min(100, Math.max(0, pct ?? 0))}%` }}
              />
            </div>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => void cancelExport()}
            >
              Cancel
            </button>
            <button
              type="button"
              className={`btn btn--ghost${renderLogVisible ? " btn--segment-active" : ""}`}
              onClick={() => setRenderLogVisible(!renderLogVisible)}
            >
              Log
            </button>
          </>
        )}
        {renderStatus === "done" && outputDownloadUrl && (
          <>
            <a className="btn btn--primary" href={outputDownloadUrl}>
              Download
            </a>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => void revealOutputInFinder()}
            >
              Show in Finder
            </button>
            <button
              type="button"
              className={`btn btn--ghost${renderLogVisible ? " btn--segment-active" : ""}`}
              onClick={() => setRenderLogVisible(!renderLogVisible)}
            >
              Log
            </button>
          </>
        )}
        {renderStatus === "error" && (
          <button
            type="button"
            className={`btn btn--ghost${renderLogVisible ? " btn--segment-active" : ""}`}
            onClick={() => setRenderLogVisible(!renderLogVisible)}
          >
            Log
          </button>
        )}
      </div>
      {renderLogVisible && renderJob?.log ? (
        <pre className="export-bar__log">{renderJob.log}</pre>
      ) : null}
      {renderStatus === "done" && outputName && (
        <p className="export-bar__meta">Saved as {outputName}</p>
      )}
      {renderStatus === "error" && renderError && (
        <p className="export-bar__err">{renderError}</p>
      )}
    </div>
  );
}
