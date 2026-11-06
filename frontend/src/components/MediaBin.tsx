import { useEffect } from "react";
import { useEditorStore } from "../store/editorStore";
import { formatDuration } from "../utils/timeFormat";

export default function MediaBin() {
  const clips = useEditorStore((s) => s.footageClips);
  const loading = useEditorStore((s) => s.footageLoading);
  const error = useEditorStore((s) => s.footageError);
  const selectedName = useEditorStore((s) => s.selectedFootageName);
  const fetchFootage = useEditorStore((s) => s.fetchFootage);
  const selectFootage = useEditorStore((s) => s.selectFootage);

  useEffect(() => {
    void fetchFootage();
  }, [fetchFootage]);

  return (
    <section className="panel panel--media" aria-label="Media bin">
      <div className="panel__header">Media bin</div>
      <div className="panel__body">
        {loading && <p className="panel-message">Loading footage…</p>}
        {error && (
          <p className="panel-message panel-message--error">
            {error}
            <button type="button" className="link-btn" onClick={() => void fetchFootage()}>
              Retry
            </button>
          </p>
        )}
        {!loading && !error && clips.length === 0 && (
          <p className="panel-message">No clips in footage/</p>
        )}
        <ul className="media-list">
          {clips.map((clip) => {
            const isSelected = clip.name === selectedName;
            return (
              <li key={clip.name}>
                <button
                  type="button"
                  className={`media-list__item${isSelected ? " media-list__item--selected" : ""}`}
                  onClick={() => selectFootage(clip.name)}
                >
                  <img
                    className="media-list__thumb"
                    src={clip.thumbnail_url}
                    alt=""
                    loading="lazy"
                    onError={(e) => {
                      e.currentTarget.style.visibility = "hidden";
                    }}
                  />
                  <div className="media-list__meta">
                    <span className="media-list__name" title={clip.name}>
                      {clip.name}
                    </span>
                    <span className="media-list__duration">
                      {formatDuration(clip.duration_seconds)}
                    </span>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
