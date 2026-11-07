import type { AnalyzeMissingChoice } from "../media/analyzeMissingFlow";

export type AnalyzePreflight = {
  free_missing_file_count: number;
  paid_caption_file_count: number;
  total_keyframes: number;
  haiku_calls: number;
  est_cost_usd: number;
  caption_model: string;
};

type Props = {
  open: boolean;
  preflight: AnalyzePreflight;
  rememberChecked: boolean;
  onRememberChange: (v: boolean) => void;
  onChoice: (choice: AnalyzeMissingChoice) => void;
};

export default function AnalyzeMissingDialog({
  open,
  preflight,
  rememberChecked,
  onRememberChange,
  onChoice,
}: Props) {
  if (!open) return null;

  const cost =
    preflight.est_cost_usd > 0 && preflight.est_cost_usd < 0.01
      ? preflight.est_cost_usd.toFixed(4)
      : preflight.est_cost_usd.toFixed(2);

  return (
    <div className="export-dialog-backdrop" role="presentation">
      <div
        className="export-dialog"
        role="dialog"
        aria-labelledby="analyze-missing-dialog-title"
      >
        <h2 id="analyze-missing-dialog-title">Analyze missing footage</h2>
        <p className="export-dialog__hint">
          {preflight.free_missing_file_count > 0
            ? `${preflight.free_missing_file_count} file(s) need local analysis. `
            : ""}
          {preflight.paid_caption_file_count > 0 ? (
            <>
              {preflight.paid_caption_file_count} video file(s) would run paid
              frame captions ({preflight.haiku_calls} Haiku call
              {preflight.haiku_calls === 1 ? "" : "s"}, ~
              {preflight.total_keyframes} keyframe image
              {preflight.total_keyframes === 1 ? "" : "s"}). Estimated cost ~$
              {cost} ({preflight.caption_model}).
            </>
          ) : (
            "No paid caption API calls are needed."
          )}
        </p>
        <label className="export-dialog__field export-dialog__check">
          <input
            type="checkbox"
            checked={rememberChecked}
            onChange={(e) => onRememberChange(e.target.checked)}
          />
          Remember my choice
        </label>
        <div className="export-dialog__actions">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => onChoice("cancel")}
          >
            Cancel
          </button>
          {preflight.paid_caption_file_count > 0 && (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => onChoice("free_only")}
            >
              Analyze free steps only (skip frame captions)
            </button>
          )}
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => onChoice("all")}
          >
            Analyze everything (includes paid frame captions)
          </button>
        </div>
      </div>
    </div>
  );
}
