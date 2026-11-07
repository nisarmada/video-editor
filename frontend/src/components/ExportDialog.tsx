import { useEffect, useMemo, useState } from "react";
import {
  estimateExportSizeMb,
  resolveProjectCanvas,
} from "../timeline/canvas";
import { timelineEnd } from "../timeline/duration";
import { fetchSettings, putSettings } from "../api/settings";
import { useTimelineStore } from "../store/timelineStore";

type Props = {
  open: boolean;
  onClose: () => void;
};

const CRF_PRESETS: { label: string; crf: number }[] = [
  { label: "High (CRF 18)", crf: 18 },
  { label: "Balanced (CRF 23)", crf: 23 },
  { label: "Small file (CRF 28)", crf: 28 },
];

export default function ExportDialog({ open, onClose }: Props) {
  const timeline = useTimelineStore((s) => s.timeline);
  const exportPlan = useTimelineStore((s) => s.exportPlanWithOptions);
  const rendering = useTimelineStore((s) => s.renderStatus === "rendering");

  const canvas = useMemo(
    () => resolveProjectCanvas(timeline?.settings),
    [timeline?.settings],
  );
  const duration = timeline ? timelineEnd(timeline) : 0;

  const [captions, setCaptions] = useState(false);
  const [crf, setCrf] = useState(23);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        const s = await fetchSettings();
        if (cancelled) return;
        setCaptions(Boolean(s.render_defaults.captions));
        const c = s.render_defaults.video_crf;
        if (typeof c === "number") setCrf(c);
      } catch {
        /* defaults */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  const estMb = estimateExportSizeMb(duration, canvas, crf);

  const onExport = async () => {
    setBusy(true);
    try {
      await putSettings({
        render_defaults: { captions, video_crf: crf },
      });
      await exportPlan({ captions, video_crf: crf });
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="export-dialog-backdrop" role="presentation">
      <div
        className="export-dialog"
        role="dialog"
        aria-labelledby="export-dialog-title"
      >
        <h2 id="export-dialog-title">Export video</h2>
        <dl className="export-dialog__meta">
          <dt>Size</dt>
          <dd>
            {canvas.width}×{canvas.height} @ {canvas.fps} fps
          </dd>
          <dt>Format</dt>
          <dd>MP4 (H.264 + AAC)</dd>
          <dt>Duration</dt>
          <dd>{duration.toFixed(1)} s</dd>
          <dt>Est. size</dt>
          <dd>~{estMb.toFixed(1)} MB</dd>
        </dl>
        <label className="export-dialog__field">
          Quality
          <select
            value={crf}
            disabled={busy || rendering}
            onChange={(e) => setCrf(Number(e.target.value))}
          >
            {CRF_PRESETS.map((p) => (
              <option key={p.crf} value={p.crf}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className="export-dialog__field export-dialog__check">
          <input
            type="checkbox"
            checked={captions}
            disabled={busy || rendering}
            onChange={(e) => setCaptions(e.target.checked)}
          />
          Burn captions
        </label>
        <p className="export-dialog__hint">
          Canvas and fit are set under the preview. Changing them saves in the
          plan (one undo step).
        </p>
        <div className="export-dialog__actions">
          <button
            type="button"
            className="btn btn--ghost"
            disabled={busy || rendering}
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn--export"
            disabled={busy || rendering || !timeline}
            onClick={() => void onExport()}
          >
            {busy || rendering ? "Exporting…" : "Export"}
          </button>
        </div>
      </div>
    </div>
  );
}
