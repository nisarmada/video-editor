import { useEffect, useMemo, useRef, useState } from "react";
import { fetchMediaCatalog } from "../api/catalog";
import {
  deleteFootageFile,
  fetchFootageAnalyzePreflight,
  FootageInUseError,
  requestFootageAnalyze,
  uploadFootageFile,
} from "../api/footage";
import { putSettings } from "../api/settings";
import AnalyzeMissingDialog from "./AnalyzeMissingDialog";
import {
  type AnalyzeMissingChoice,
  computeBatchProgress,
  includeFrameCaptionsForChoice,
  namesToQueue,
  rememberModeForChoice,
  shouldShowAnalyzeMissingDialog,
} from "../media/analyzeMissingFlow";
import {
  entryNeedsPaidCaptions,
  filesMissingFreeAnalysis,
} from "../media/missingAnalysis";
import {
  FOOTAGE_DRAG_MIME,
  FOOTAGE_DRAG_TEXT_TYPE,
} from "../timeline/dragConstants";
import { setFootageFromBinDragging } from "../timeline/footageDragState";
import { useTimelineStore } from "../store/timelineStore";
import { formatDuration } from "../utils/timeFormat";

type UploadRow = {
  id: string;
  fileName: string;
  progress: number;
  error: string | null;
};

function clipFootageKind(clip: { kind?: string; name: string }): "video" | "audio" {
  if (clip.kind === "audio" || clip.kind === "video") return clip.kind;
  const ext = clip.name.includes(".")
    ? clip.name.slice(clip.name.lastIndexOf(".")).toLowerCase()
    : "";
  const audioExts = new Set([
    ".mp3",
    ".wav",
    ".aac",
    ".m4a",
    ".flac",
    ".ogg",
    ".opus",
  ]);
  return audioExts.has(ext) ? "audio" : "video";
}

export default function MediaBin() {
  const clips = useTimelineStore((s) => s.footageClips);
  const mediaBinCategory = useTimelineStore((s) => s.mediaBinCategory);
  const loading = useTimelineStore((s) => s.footageLoading);
  const error = useTimelineStore((s) => s.footageError);
  const selectedName = useTimelineStore((s) => s.selectedFootageName);
  const selectedNames = useTimelineStore((s) => s.selectedFootageNames);
  const fetchFootage = useTimelineStore((s) => s.fetchFootage);
  const rescanFootage = useTimelineStore((s) => s.rescanFootage);
  const selectFootage = useTimelineStore((s) => s.selectFootage);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [analyzeBusy, setAnalyzeBusy] = useState(false);
  const [analyzeMessage, setAnalyzeMessage] = useState<string | null>(null);
  const [analyzeIsError, setAnalyzeIsError] = useState(false);
  const [batchNames, setBatchNames] = useState<string[] | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogPreflight, setDialogPreflight] = useState<
    Awaited<ReturnType<typeof fetchFootageAnalyzePreflight>> | null
  >(null);
  const [dialogEntries, setDialogEntries] = useState<
    Awaited<ReturnType<typeof fetchMediaCatalog>>["entries"]
  >([]);
  const [rememberChoice, setRememberChoice] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [uploads, setUploads] = useState<UploadRow[]>([]);
  const [deleteBusy, setDeleteBusy] = useState<string | null>(null);

  useEffect(() => {
    void fetchFootage();
  }, [fetchFootage]);

  const visibleClips = useMemo(() => {
    if (mediaBinCategory === "all") return clips;
    return clips.filter((c) => clipFootageKind(c) === mediaBinCategory);
  }, [clips, mediaBinCategory]);

  const needsPoll =
    Boolean(batchNames?.length) ||
    clips.some((c) => {
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

  const batchProgress = useMemo(() => {
    if (!batchNames?.length) return null;
    return computeBatchProgress(batchNames, clips);
  }, [batchNames, clips]);

  useEffect(() => {
    if (!batchNames?.length || !batchProgress) return;
    if (batchProgress.done < batchProgress.total) return;
    if (batchProgress.failed.length > 0) {
      setAnalyzeIsError(true);
      setAnalyzeMessage(
        `Analysis finished: ${batchProgress.done}/${batchProgress.total}. ` +
          batchProgress.failed
            .map((f) => `${f.name}: ${f.error}`)
            .join(" · "),
      );
    } else {
      setAnalyzeMessage(
        `Analysis finished: ${batchProgress.done}/${batchProgress.total} file(s).`,
      );
    }
    setBatchNames(null);
  }, [batchNames, batchProgress]);

  useEffect(() => {
    if (!batchProgress || !batchNames?.length) return;
    if (batchProgress.done < batchProgress.total) {
      const failNote =
        batchProgress.failed.length > 0
          ? ` · ${batchProgress.failed.length} failed`
          : "";
      setAnalyzeMessage(
        `Analyzing ${batchProgress.done}/${batchProgress.total}${failNote}…`,
      );
      setAnalyzeIsError(batchProgress.failed.length > 0);
    }
  }, [batchProgress, batchNames]);

  async function queueAnalysis(
    names: string[],
    includeFrameCaptions: boolean,
  ) {
    if (names.length === 0) {
      setAnalyzeMessage(
        "Nothing to queue — local analysis is already complete (use Generate captions on a clip for paid captions only).",
      );
      return;
    }
    const queued = await requestFootageAnalyze({
      names,
      include_frame_captions: includeFrameCaptions,
    });
    setBatchNames(queued.queued);
    setAnalyzeMessage(`Queued analysis for ${queued.queued.length} file(s)…`);
    await fetchFootage({ silent: true });
  }

  async function startAnalyzeMissing() {
    setAnalyzeBusy(true);
    setAnalyzeMessage(null);
    setAnalyzeIsError(false);
    try {
      const { entries } = await fetchMediaCatalog();
      const freeMissing = filesMissingFreeAnalysis(entries);
      const paidCount = entries.filter((e) => entryNeedsPaidCaptions(e)).length;
      if (freeMissing.length === 0 && paidCount === 0) {
        setAnalyzeMessage(
          "Every file in the library already has its analysis files.",
        );
        return;
      }
      const queueNames = namesToQueue(entries, true);
      const preflight = await fetchFootageAnalyzePreflight({
        names: queueNames,
      });
      const remembered = preflight.remember_missing_mode;
      const showDialog = shouldShowAnalyzeMissingDialog(
        remembered,
        preflight.paid_caption_file_count,
        preflight.free_missing_file_count,
      );
      if (showDialog) {
        setDialogEntries(entries);
        setDialogPreflight(preflight);
        setRememberChoice(false);
        setDialogOpen(true);
        return;
      }
      const mode = remembered ?? "all";
      const include = mode === "all";
      await queueAnalysis(namesToQueue(entries, include), include);
    } catch (e) {
      setAnalyzeIsError(true);
      setAnalyzeMessage(
        e instanceof Error ? e.message : "Could not queue analysis.",
      );
    } finally {
      setAnalyzeBusy(false);
    }
  }

  async function onDialogChoice(choice: AnalyzeMissingChoice) {
    setDialogOpen(false);
    if (choice === "cancel") {
      setAnalyzeMessage("Analyze all missing was cancelled.");
      return;
    }
    setAnalyzeBusy(true);
    try {
      const include = includeFrameCaptionsForChoice(choice);
      if (include === null) return;
      if (rememberChoice) {
        const mode = rememberModeForChoice(choice);
        if (mode) {
          await putSettings({ analysis: { remember_missing_mode: mode } });
        }
      }
      await queueAnalysis(namesToQueue(dialogEntries, include), include);
    } catch (e) {
      setAnalyzeIsError(true);
      setAnalyzeMessage(
        e instanceof Error ? e.message : "Could not queue analysis.",
      );
    } finally {
      setAnalyzeBusy(false);
      setDialogPreflight(null);
      setDialogEntries([]);
    }
  }

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
      if (selectedName === name || selectedNames.includes(name)) {
        useTimelineStore.setState({
          selectedFootageName: null,
          selectedFootageNames: [],
        });
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
      {dialogOpen && dialogPreflight && (
        <AnalyzeMissingDialog
          open={dialogOpen}
          preflight={dialogPreflight}
          rememberChecked={rememberChoice}
          onRememberChange={setRememberChoice}
          onChoice={(c) => void onDialogChoice(c)}
        />
      )}
      <div className="media-bin-toolbar">
        <input
          ref={fileInputRef}
          type="file"
          className="media-bin-toolbar__file-input"
          accept="video/*,audio/*,.mp4,.mov,.m4v,.mkv,.webm,.mp3,.wav,.aac,.m4a,.flac,.ogg,.opus"
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
        <button
          type="button"
          className="btn btn--ghost"
          disabled={analyzeBusy || clips.length === 0}
          title="Queue analysis for files that are missing a transcript, silences, shots, keyframes, captions, or a merged index"
          onClick={() => void startAnalyzeMissing()}
        >
          {analyzeBusy ? "Queuing…" : "Analyze all missing"}
        </button>
      </div>
      {analyzeMessage && (
        <p
          className={
            analyzeIsError
              ? "panel-message panel-message--error"
              : "panel-message"
          }
          role={analyzeIsError ? "alert" : "status"}
        >
          {analyzeMessage}
        </p>
      )}
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
        {!loading &&
          !error &&
          clips.length === 0 &&
          uploads.length === 0 && (
          <p className="panel-message">
            No clips yet — Import or drop video or audio files here (saved under{" "}
            <code className="media-bin-code">footage/</code>).
          </p>
        )}
        {!loading &&
          !error &&
          clips.length > 0 &&
          visibleClips.length === 0 &&
          uploads.length === 0 && (
            <p className="panel-message">
              No{" "}
              {mediaBinCategory === "video"
                ? "video"
                : mediaBinCategory === "audio"
                  ? "audio"
                  : ""}{" "}
              files in <code className="media-bin-code">footage/</code> yet — switch tab or
              import {mediaBinCategory === "audio" ? "an .mp3 / .wav" : "media"}.
            </p>
          )}
        <ul className="media-list">
          {visibleClips.map((clip) => {
            const isSelected =
              clip.name === selectedName || selectedNames.includes(clip.name);
            const pStatus = clip.process_status ?? "ready";
            const processing =
              pStatus === "processing" || pStatus === "pending";
            const failed = pStatus === "failed";
            const kind = clipFootageKind(clip);
            return (
              <li key={clip.name} className="media-list__row">
                <button
                  type="button"
                  className={`media-list__item${isSelected ? " media-list__item--selected" : ""}`}
                  draggable={!processing}
                  onClick={(e) =>
                    selectFootage(clip.name, { additive: e.shiftKey })
                  }
                  onDragStart={(e) => {
                    if (processing) {
                      e.preventDefault();
                      return;
                    }
                    const payload = JSON.stringify({
                      name: clip.name,
                      source: clip.source,
                      duration_seconds: clip.duration_seconds,
                    });
                    e.dataTransfer.setData(FOOTAGE_DRAG_MIME, payload);
                    e.dataTransfer.setData(FOOTAGE_DRAG_TEXT_TYPE, payload);
                    e.dataTransfer.effectAllowed = "copy";
                    setFootageFromBinDragging(true);
                  }}
                  onDragEnd={() => setFootageFromBinDragging(false)}
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
                      {kind === "audio" && (
                        <span className="media-list__kind" title="Audio file">
                          ♪{" "}
                        </span>
                      )}
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
