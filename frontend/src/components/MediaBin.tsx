import { useEffect, useRef, useState } from "react";
import {
  deleteFootageFile,
  FootageInUseError,
  uploadFootageFile,
} from "../api/footage";
import { FOOTAGE_DRAG_MIME } from "../timeline/dragConstants";
import { useTimelineStore } from "../store/timelineStore";
import { formatDuration } from "../utils/timeFormat";

type UploadRow = {
  id: string;
  fileName: string;
  progress: number;
  error: string | null;
};

export default function MediaBin() {
  const clips = useTimelineStore((s) => s.footageClips);
  const loading = useTimelineStore((s) => s.footageLoading);
  const error = useTimelineStore((s) => s.footageError);
  const selectedName = useTimelineStore((s) => s.selectedFootageName);
  const fetchFootage = useTimelineStore((s) => s.fetchFootage);
  const rescanFootage = useTimelineStore((s) => s.rescanFootage);
  const selectFootage = useTimelineStore((s) => s.selectFootage);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploads, setUploads] = useState<UploadRow[]>([]);
  const [deleteBusy, setDeleteBusy] = useState<string | null>(null);

  useEffect(() => {
    void fetchFootage();
  }, [fetchFootage]);

  const needsPoll = clips.some((c) => {
    const st = c.process_status ?? "ready";
    return st === "processing" || st === "pending" || st === "failed";
  });

  useEffect(() => {
    if (!needsPoll) return;
    const id = window.setInterval(() => {
      void fetchFootage({ silent: true });
    }, 1200);
    return () => window.clearInterval(id);
  }, [needsPoll, fetchFootage]);

  async function runUploads(files: FileList | File[]) {
    const list = Array.from(files);
    for (const file of list) {
      const uid = `${file.name}-${Date.now()}-${Math.random()}`;
      setUploads((u) => [
        ...u,
        { id: uid, fileName: file.name, progress: 0, error: null },
      ]);
      try {
        await uploadFootageFile(file, ({ loaded, total }) => {
          const pct = total > 0 ? Math.round((loaded / total) * 100) : 0;
          setUploads((u) =>
            u.map((row) =>
              row.id === uid ? { ...row, progress: pct } : row,
            ),
          );
        });
        setUploads((u) => u.filter((row) => row.id !== uid));
        await fetchFootage({ silent: true });
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Upload failed";
        setUploads((u) =>
          u.map((row) =>
            row.id === uid ? { ...row, error: msg, progress: 100 } : row,
          ),
        );
      }
    }
  }

  function onImportClick() {
    fileInputRef.current?.click();
  }

  async function onDelete(name: string) {
    if (!window.confirm(`Delete "${name}" from footage/? This cannot be undone.`)) {
      return;
    }
    setDeleteBusy(name);
    try {
      await deleteFootageFile(name);
      if (selectedName === name) {
        useTimelineStore.setState({ selectedFootageName: null });
      }
      await fetchFootage({ silent: true });
    } catch (e) {
      if (e instanceof FootageInUseError) {
        window.alert(
          `Cannot delete: file is used in plan(s): ${e.plans.join(", ") || "(unknown)"}`,
        );
      } else {
        window.alert(e instanceof Error ? e.message : "Delete failed");
      }
    } finally {
      setDeleteBusy(null);
    }
  }

  return (
    <section
      className={`panel panel--media${dragOver ? " panel--media-drop" : ""}`}
      aria-label="Media library"
      onDragOver={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.dataTransfer.types.includes("Files")) setDragOver(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        if (e.currentTarget === e.target) setDragOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        setDragOver(false);
        if (e.dataTransfer.files?.length) void runUploads(e.dataTransfer.files);
      }}
    >
      <div className="media-bin-toolbar">
        <input
          ref={fileInputRef}
          type="file"
          className="media-bin-toolbar__file-input"
          accept="video/mp4,video/quicktime,video/x-m4v,video/x-matroska,video/webm,.mp4,.mov,.m4v,.mkv,.webm"
          multiple
          onChange={(e) => {
            const f = e.target.files;
            if (f?.length) void runUploads(f);
            e.target.value = "";
          }}
        />
        <button type="button" className="btn btn--primary" onClick={onImportClick}>
          Import…
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          title="Generate missing proxies for files already in footage/"
          onClick={() => void rescanFootage()}
        >
          Rescan folder
        </button>
      </div>
      <div className="panel__body panel__body--media">
        {loading && <p className="panel-message">Loading footage…</p>}
        {error && (
          <p className="panel-message panel-message--error">
            {error}
            <button type="button" className="link-btn" onClick={() => void fetchFootage()}>
              Retry
            </button>
          </p>
        )}
        {uploads.length > 0 && (
          <ul className="media-upload-list">
            {uploads.map((u) => (
              <li key={u.id} className="media-upload-row">
                <span className="media-upload-row__name" title={u.fileName}>
                  {u.fileName}
                </span>
                {u.error ? (
                  <span className="media-upload-row__err">{u.error}</span>
                ) : (
                  <>
                    <div className="media-upload-row__bar">
                      <div
                        className="media-upload-row__fill"
                        style={{ width: `${u.progress}%` }}
                      />
                    </div>
                    <span className="media-upload-row__pct">{u.progress}%</span>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
        {!loading && !error && clips.length === 0 && uploads.length === 0 && (
          <p className="panel-message">
            No clips yet — Import or drop video files here (saved under{" "}
            <code className="media-bin-code">footage/</code>).
          </p>
        )}
        <ul className="media-list">
          {clips.map((clip) => {
            const isSelected = clip.name === selectedName;
            const pStatus = clip.process_status ?? "ready";
            const processing =
              pStatus === "processing" || pStatus === "pending";
            const failed = pStatus === "failed";
            return (
              <li key={clip.name} className="media-list__row">
                <button
                  type="button"
                  className={`media-list__item${isSelected ? " media-list__item--selected" : ""}`}
                  draggable={!processing}
                  onClick={() => selectFootage(clip.name)}
                  onDragStart={(e) => {
                    if (processing) {
                      e.preventDefault();
                      return;
                    }
                    e.dataTransfer.setData(
                      FOOTAGE_DRAG_MIME,
                      JSON.stringify({
                        name: clip.name,
                        source: clip.source,
                        duration_seconds: clip.duration_seconds,
                      }),
                    );
                    e.dataTransfer.effectAllowed = "copy";
                  }}
                >
                  <div className="media-list__thumb-wrap">
                    {!failed ? (
                      <img
                        className="media-list__thumb"
                        src={clip.thumbnail_url}
                        alt=""
                        draggable={false}
                        loading="lazy"
                        onError={(e) => {
                          e.currentTarget.style.visibility = "hidden";
                        }}
                      />
                    ) : (
                      <div className="media-list__thumb media-list__thumb--error" />
                    )}
                    {processing && (
                      <span className="media-list__spinner" aria-hidden />
                    )}
                  </div>
                  <div className="media-list__meta">
                    <span className="media-list__name" title={clip.name}>
                      {clip.name}
                    </span>
                    <span className="media-list__duration">
                      {formatDuration(clip.duration_seconds)}
                    </span>
                    {failed && clip.process_error && (
                      <span className="media-list__process-err" title={clip.process_error}>
                        {clip.process_error}
                      </span>
                    )}
                  </div>
                </button>
                <button
                  type="button"
                  className="media-list__delete btn btn--ghost"
                  disabled={deleteBusy === clip.name}
                  title="Remove from footage/"
                  onClick={(e) => {
                    e.stopPropagation();
                    void onDelete(clip.name);
                  }}
                >
                  {deleteBusy === clip.name ? "…" : "✕"}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
