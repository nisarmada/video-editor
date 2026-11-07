import { useMemo, useState } from "react";
import type { TakeReviewGroup } from "../api/planner";
import { formatTimecode } from "../utils/timeFormat";

type Props = {
  groups: TakeReviewGroup[];
  onCancel: () => void;
  onConfirm: (excludedTakeIds: string[]) => void;
};

export default function TakeReviewModal({ groups, onCancel, onConfirm }: Props) {
  const initialKeep = useMemo(() => {
    const map = new Map<string, boolean>();
    for (const g of groups) {
      for (const a of g.attempts) {
        map.set(a.id, a.default_keep);
      }
    }
    return map;
  }, [groups]);

  const [keepMap, setKeepMap] = useState(initialKeep);

  const toggle = (id: string, next: boolean) => {
    setKeepMap((prev) => new Map(prev).set(id, next));
  };

  const excluded = useMemo(() => {
    const out: string[] = [];
    for (const [id, keep] of keepMap) {
      if (!keep) out.push(id);
    }
    return out;
  }, [keepMap]);

  if (!groups.length) {
    return (
      <div className="take-review-overlay" role="dialog" aria-modal="true" aria-label="Take review">
        <div className="take-review take-review--empty">
          <p>No multi-attempt phrases need review. Continue to planning.</p>
          <div className="take-review__actions">
            <button type="button" className="btn btn--ghost" onClick={onCancel}>
              Cancel
            </button>
            <button type="button" className="btn btn--primary" onClick={() => onConfirm([])}>
              Continue
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="take-review-overlay" role="dialog" aria-modal="true" aria-label="Review takes">
      <div className="take-review">
        <header className="take-review__header">
          <h2 className="take-review__title">Review takes before planning</h2>
          <p className="take-review__hint">
            Toggle off false starts or weaker attempts. Discarded takes will be excluded from the
            planner.
          </p>
        </header>
        <div className="take-review__list">
          {groups.map((g) => (
            <section key={g.id} className="take-review__group">
              <div className="take-review__phrase">
                <span className="take-review__file">{g.source_file}</span>
                <span className="take-review__label">{g.phrase_label || "Phrase"}</span>
              </div>
              <ul className="take-review__attempts">
                {g.attempts.map((a) => {
                  const keep = keepMap.get(a.id) ?? a.default_keep;
                  return (
                    <li key={a.id} className="take-review__attempt">
                      <label className="take-review__row">
                        <input
                          type="checkbox"
                          checked={keep}
                          onChange={(e) => toggle(a.id, e.target.checked)}
                        />
                        <span className="take-review__meta">
                          {typeof a.start === "number" && typeof a.end === "number"
                            ? `${formatTimecode(a.start)}–${formatTimecode(a.end)}`
                            : ""}
                          {a.abandoned_sentence ? " · abandoned" : ""}
                          {a.is_restart ? " · restart" : ""}
                        </span>
                        <span className="take-review__text">{a.text}</span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
        <footer className="take-review__actions">
          <span className="take-review__stat">
            {excluded.length > 0
              ? `${excluded.length} attempt(s) discarded`
              : "All shown attempts kept"}
          </span>
          <button type="button" className="btn btn--ghost" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => onConfirm(excluded)}
          >
            Continue planning
          </button>
        </footer>
      </div>
    </div>
  );
}
