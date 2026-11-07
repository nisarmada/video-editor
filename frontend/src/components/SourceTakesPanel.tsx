import { useEffect, useState } from "react";
import { fetchMediaCatalog, type MediaCatalogEntry } from "../api/catalog";
import { useTimelineStore } from "../store/timelineStore";
import { formatTimecode } from "../utils/timeFormat";

type TakeRow = {
  take_index?: number;
  start?: number;
  end?: number;
  text?: string;
  speech_rate_wpm?: number;
  is_restart?: boolean;
  abandoned_sentence?: boolean;
  ends_complete_sentence?: boolean;
};

function isAudioFootage(name: string, kind?: string): boolean {
  if (kind === "audio") return true;
  const ext = name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "";
  return [".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".opus"].includes(ext);
}

export default function SourceTakesPanel() {
  const selectedName = useTimelineStore((s) => s.selectedFootageName);
  const clips = useTimelineStore((s) => s.footageClips);
  const requestSourcePlayback = useTimelineStore((s) => s.requestSourcePlayback);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [takes, setTakes] = useState<TakeRow[]>([]);
  const [takeCount, setTakeCount] = useState<number | null>(null);

  const clip = selectedName
    ? clips.find((c) => c.name === selectedName) ?? null
    : null;
  const showPanel = clip && isAudioFootage(clip.name, clip.kind);

  useEffect(() => {
    if (!showPanel || !selectedName) {
      setTakes([]);
      setTakeCount(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void fetchMediaCatalog({ names: [selectedName] })
      .then(({ entries }) => {
        if (cancelled) return;
        const entry = entries[0] as MediaCatalogEntry | undefined;
        if (!entry) {
          setTakes([]);
          setTakeCount(null);
          return;
        }
        const summary = entry.takes_summary as
          | { take_count?: number; status?: string }
          | undefined;
        const st = summary?.status;
        if (st && st !== "complete") {
          setTakes([]);
          setTakeCount(null);
          setError("Takes not analyzed yet — use Analyze all missing.");
          return;
        }
        const rows = (entry.takes as TakeRow[] | undefined) ?? [];
        setTakes(rows);
        setTakeCount(
          typeof summary?.take_count === "number"
            ? summary.take_count
            : rows.length,
        );
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not load takes");
        setTakes([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedName, showPanel]);

  if (!showPanel) return null;

  return (
    <section className="source-takes" aria-label="Speech takes">
      <div className="source-takes__header">
        <span>Takes</span>
        {takeCount != null && (
          <span className="source-takes__count">{takeCount}</span>
        )}
      </div>
      {loading && <p className="panel-message">Loading takes…</p>}
      {error && (
        <p className="panel-message panel-message--error" role="alert">
          {error}
        </p>
      )}
      {!loading && !error && takes.length === 0 && (
        <p className="panel-message">No speech takes detected.</p>
      )}
      <ul className="source-takes__list">
        {takes.map((take) => {
          const start = take.start ?? 0;
          const end = take.end ?? start;
          const idx = take.take_index ?? 0;
          return (
            <li key={idx} className="source-takes__row">
              <button
                type="button"
                className="btn btn--ghost source-takes__play"
                title={`Play ${formatTimecode(start)} – ${formatTimecode(end)}`}
                onClick={() => requestSourcePlayback(start, end)}
              >
                ▶
              </button>
              <div className="source-takes__body">
                <span className="source-takes__time">
                  {formatTimecode(start)} – {formatTimecode(end)}
                  {take.speech_rate_wpm != null && (
                    <span className="source-takes__wpm">
                      {" "}
                      · {take.speech_rate_wpm} wpm
                    </span>
                  )}
                </span>
                <span className="source-takes__text" title={take.text ?? ""}>
                  {take.text ?? "—"}
                </span>
                <span className="source-takes__flags">
                  {take.is_restart ? "restart" : null}
                  {take.abandoned_sentence ? " · abandoned" : null}
                  {take.ends_complete_sentence ? " · complete" : null}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
