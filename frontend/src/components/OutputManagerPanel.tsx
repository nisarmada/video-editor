import { useEffect, useState } from "react";
import {
  deleteOutputFile,
  fetchOutputList,
  type OutputFileRow,
} from "../api/outputApi";
import { useTimelineStore } from "../store/timelineStore";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

type Props = {
  open: boolean;
  onClose: () => void;
};

export default function OutputManagerPanel({ open, onClose }: Props) {
  const setUiBannerError = useTimelineStore((s) => s.setUiBannerError);
  const [files, setFiles] = useState<OutputFileRow[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = () => {
    setLoading(true);
    void fetchOutputList()
      .then(setFiles)
      .catch((e: unknown) =>
        setUiBannerError(
          e instanceof Error ? e.message : "Failed to list output",
        ),
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (open) refresh();
  }, [open]);

  if (!open) return null;

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="modal-sheet modal-sheet--wide"
        role="dialog"
        aria-label="Output files"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-sheet__header">
          <h2 className="modal-sheet__title">Output</h2>
          <div className="modal-sheet__header-actions">
            <button type="button" className="btn btn--ghost" onClick={refresh}>
              Refresh
            </button>
            <button type="button" className="btn btn--ghost" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
        {loading ? (
          <p className="modal-sheet__muted">Loading…</p>
        ) : files.length === 0 ? (
          <p className="modal-sheet__muted">No files in output/ yet.</p>
        ) : (
          <ul className="output-list">
            {files.map((f) => (
              <li key={f.name} className="output-list__row">
                <span className="output-list__name" title={f.name}>
                  {f.name}
                </span>
                <span className="output-list__size">{formatBytes(f.size_bytes)}</span>
                <a className="btn btn--ghost" href={f.download_url}>
                  Download
                </a>
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => {
                    if (
                      typeof window !== "undefined" &&
                      !window.confirm(`Delete ${f.name}?`)
                    ) {
                      return;
                    }
                    void deleteOutputFile(f.name)
                      .then(refresh)
                      .catch((e: unknown) =>
                        setUiBannerError(
                          e instanceof Error ? e.message : "Delete failed",
                        ),
                      );
                  }}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
