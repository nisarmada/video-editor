import { useEffect } from "react";
import { canMutateTimeline } from "../store/timelineMutation";
import { useTimelineStore } from "../store/timelineStore";
import { useKeybindingsStore } from "../store/keybindingsStore";
import { useEditorSettingsStore, timelineViewportElRef } from "../store/editorSettingsStore";
import { getCursorContext } from "../store/cursorContextStore";
import { keydownMatchesChord } from "../shortcuts/normalize";
import { getEffectiveBindings } from "../shortcuts/merge";
import { SHORTCUT_ACTIONS } from "../shortcuts/actions";
import { reservedReason } from "../shortcuts/reserved";
import { resolveTarget } from "../shortcuts/resolveTarget";
import { isTooCloseToClipEdgeForSplit } from "../shortcuts/snapTime";
import {
  copyClipPayload,
  expandLinkedSelection,
  findClipById,
  readClipFromClipboard,
  clipLinkingEnabled,
} from "../timeline/selection";
import { timelineEnd, clipTimelineDuration } from "../timeline/duration";
import { MAX_PX_PER_SEC, MIN_PX_PER_SEC } from "../store/timelineStore";
import { rawSecondsFromClientXInTimeline } from "../timeline/timelinePointer";
import { snapShortcutTime } from "../shortcuts/snapTime";

function isTypingTarget(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  if (tag === "BUTTON" || tag === "A") return true;
  return false;
}

function isShortcutBlockedUi(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el) return false;
  if (el.closest(".tl-context-menu") || el.closest(".tl-context-menu-backdrop")) {
    return true;
  }
  if (el.closest('[role="dialog"]') || el.closest('[role="menu"]')) {
    return true;
  }
  return false;
}

const ZOOM_STEP = 4;

const NO_KEY_REPEAT = new Set<string>([
  "undo",
  "redo",
  "split",
  "delete",
  "play_pause",
  "save_plan",
  "export_render",
  "copy_clip",
  "paste_clip",
  "separate_audio",
  "reattach_audio",
  "unlink_clips",
  "toggle_clip_linking",
  "toggle_track_mute",
  "mute_clip",
  "select_all_clips",
  "deselect_clips",
  "cheat_sheet",
  "open_keyboard_settings",
  "jump_start",
  "jump_end",
  "move_playhead_to_cursor",
  "trim_start_to_cursor",
  "trim_end_to_cursor",
  "toggle_track_lock",
]);

async function runTimelineOp(fn: () => Promise<unknown>): Promise<void> {
  try {
    await fn();
  } catch {
    /* opErrorMessage on store */
  }
}

function toast(msg: string): void {
  useTimelineStore.getState().setShortcutToast(msg);
  window.setTimeout(() => {
    if (useTimelineStore.getState().shortcutToast === msg) {
      useTimelineStore.getState().setShortcutToast(null);
    }
  }, 2800);
}

export function useShortcuts(): void {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const ui = useKeybindingsStore.getState();
      if (ui.shortcutCaptureActive) return;
      if (ui.keyboardSettingsOpen || ui.cheatSheetOpen) return;
      if (isTypingTarget(e.target)) return;
      if (isShortcutBlockedUi(e.target)) return;

      const overrides = useKeybindingsStore.getState().overrides;

      let matchedId: string | null = null;
      for (const def of SHORTCUT_ACTIONS) {
        const chords = getEffectiveBindings(def.id, overrides);
        for (const chord of chords) {
          if (keydownMatchesChord(e, chord)) matchedId = def.id;
        }
      }
      if (!matchedId) return;

      if (NO_KEY_REPEAT.has(matchedId) && e.repeat) return;

      const s = useTimelineStore.getState();
      const busy = !canMutateTimeline({
        applyOperationInProgress: s.applyOperationInProgress,
        dragInProgress: s.dragInProgress,
      });

      const ed = useEditorSettingsStore.getState();

      const rtBase = (actionId: string) =>
        resolveTarget(actionId, {
          policy: ed.shortcutTargeting,
          perActionTargetMode: ed.perActionTargetMode,
          timelineSnapEnabled: ed.timelineSnapEnabled,
          pxPerSecond: s.pxPerSecond,
          playheadSeconds: s.playheadSeconds,
          timeline: s.timeline,
          selectedClipIds: s.selectedClipIds,
          selectedClipId: s.selectedClipId,
        });

      const preventAndRun = (fn: () => void | Promise<void>) => {
        e.preventDefault();
        void fn();
      };

      const applyCursorSelection = (rt: ReturnType<typeof rtBase>) => {
        if (!ed.cursorActionSelectsClip || !rt.useCursorTime) return;
        const ids =
          rt.expandedClipIds.length > 0
            ? rt.expandedClipIds
            : rt.primaryClipId
              ? [rt.primaryClipId]
              : [];
        if (ids.length) s.setSelectedClipIds(ids);
      };

      switch (matchedId) {
        case "undo":
          if (busy || s.undoStack.length === 0) return;
          preventAndRun(() => runTimelineOp(() => s.undo()));
          break;
        case "redo":
          if (busy || s.redoStack.length === 0) return;
          preventAndRun(() => runTimelineOp(() => s.redo()));
          break;

        case "split": {
          if (busy || !s.timeline) return;
          const rt = rtBase("split");
          applyCursorSelection(rt);
          if (rt.fallbackNoClip || rt.clipIds.length === 0) {
            preventAndRun(() => toast(rt.message ?? "No clip."));
            return;
          }
          const fps =
            s.timeline.settings?.fps && s.timeline.settings.fps > 0
              ? s.timeline.settings.fps
              : 30;
          const t = rt.timeSeconds;
          for (const cid of rt.clipIds) {
            const hit = findClipById(s.timeline, cid);
            if (!hit) continue;
            if ((hit.trackType === "caption")) {
              preventAndRun(() => toast("Cannot split caption clips here."));
              return;
            }
            const tr = s.timeline.tracks?.find((x) => x.id === hit.trackId);
            if (tr?.locked) {
              preventAndRun(() => toast("Track is locked."));
              return;
            }
            const d = clipTimelineDuration(hit.clip, hit.trackType);
            const t0 = hit.clip.timeline_start;
            const t1 = t0 + d;
            if (isTooCloseToClipEdgeForSplit(t, t0, t1, fps)) {
              preventAndRun(() =>
                toast("Too close to clip edge to split (within one frame)."),
              );
              return;
            }
          }
          preventAndRun(() =>
            runTimelineOp(() => s.splitClipsAtTime(rt.clipIds, t)),
          );
          break;
        }

        case "delete": {
          if (busy || !s.timeline) return;
          const rt = rtBase("delete");
          applyCursorSelection(rt);
          if (rt.fallbackNoClip || rt.clipIds.length === 0) {
            preventAndRun(() => toast(rt.message ?? "Nothing to delete."));
            return;
          }
          for (const cid of rt.clipIds) {
            const hit = findClipById(s.timeline!, cid);
            const tr = hit && s.timeline!.tracks?.find((x) => x.id === hit.trackId);
            if (tr?.locked) {
              preventAndRun(() => toast("Track is locked."));
              return;
            }
          }
          preventAndRun(() => runTimelineOp(() => s.deleteClipsByIds(rt.clipIds)));
          break;
        }

        case "copy_clip": {
          if (busy || !s.timeline) return;
          const rt = rtBase("copy_clip");
          const selList =
            s.selectedClipIds.length > 0
              ? [...s.selectedClipIds]
              : s.selectedClipId
                ? [s.selectedClipId]
                : [];
          const selSet = new Set(selList);
          let copyId: string | null = null;
          if (rt.useCursorTime && rt.primaryClipId && !selSet.has(rt.primaryClipId)) {
            copyId = rt.primaryClipId;
          } else if (selList.length > 0) {
            copyId = selList[selList.length - 1]!;
          } else if (rt.primaryClipId) {
            copyId = rt.primaryClipId;
          }
          if (!copyId) {
            preventAndRun(() => toast("Nothing to copy."));
            return;
          }
          const hit = findClipById(s.timeline, copyId);
          if (!hit) return;
          preventAndRun(() => {
            copyClipPayload({
              clip: hit.clip,
              sourceTrackId: hit.trackId,
              sourceTrackType: hit.trackType,
            });
          });
          break;
        }

        case "paste_clip": {
          const tl = s.timeline;
          const data = readClipFromClipboard();
          if (busy || !tl || !data) return;
          const rt = rtBase("paste_clip");
          applyCursorSelection(rt);
          const ph = rt.useCursorTime ? rt.timeSeconds : s.playheadSeconds;
          let targetTrackId: string | undefined;
          if (rt.useCursorTime && rt.trackId) {
            const st = data.sourceTrackType;
            const hitTrack = tl.tracks?.find((x) => x.id === rt.trackId);
            if (hitTrack) {
              if (st === "audio" && hitTrack.type === "audio") targetTrackId = hitTrack.id;
              else if (st === "caption" && hitTrack.type === "caption") targetTrackId = hitTrack.id;
              else if ((st === "video" || !st) && hitTrack.type === "video") targetTrackId = hitTrack.id;
            }
          }
          preventAndRun(() =>
            runTimelineOp(async () => {
              const videoTr = tl.tracks.find((x) => x.type === "video");
              const audioTr = tl.tracks.find((x) => x.type === "audio");
              const capTr = tl.tracks.find((x) => x.type === "caption");
              const st = data.sourceTrackType;
              const targetId =
                targetTrackId ||
                (st === "audio" && audioTr
                  ? audioTr.id
                  : st === "caption" && capTr
                    ? capTr.id
                    : videoTr?.id);
              const { group_id: _g, id: _i, ...clipRest } = data.clip;
              const newClip: Record<string, unknown> = {
                ...clipRest,
                id: crypto.randomUUID(),
                timeline_start: ph,
                created_by: "user",
              };
              if (st === "video" || (!st && !targetId)) {
                newClip.audio_source = "embedded";
              }
              const args: Record<string, unknown> = { clip: newClip };
              if (targetId) args.track_id = targetId;
              await s.applyOperation({ operation: "add_clip", arguments: args });
            }),
          );
          break;
        }

        case "separate_audio": {
          if (busy || !s.timeline) return;
          const rt = rtBase("separate_audio");
          applyCursorSelection(rt);
          const id = rt.primaryClipId ?? s.selectedClipId;
          if (!id || rt.fallbackNoClip) {
            preventAndRun(() => toast(rt.message ?? "No video clip."));
            return;
          }
          const hit = findClipById(s.timeline, id);
          if (hit?.trackType !== "video") {
            preventAndRun(() => toast("Separate audio needs a video clip."));
            return;
          }
          if (hit.clip.audio_source === "detached") {
            preventAndRun(() => toast("Audio already separated."));
            return;
          }
          preventAndRun(() => runTimelineOp(() => s.separateAudioForClip(id)));
          break;
        }

        case "reattach_audio": {
          if (busy || !s.timeline) return;
          const rt = rtBase("reattach_audio");
          applyCursorSelection(rt);
          const id = rt.primaryClipId ?? s.selectedClipId;
          if (!id || rt.fallbackNoClip) {
            preventAndRun(() => toast(rt.message ?? "No clip."));
            return;
          }
          preventAndRun(() => runTimelineOp(() => s.reattachAudioForClip(id)));
          break;
        }

        case "unlink_clips": {
          if (busy || !s.timeline) return;
          const rt = rtBase("unlink_clips");
          applyCursorSelection(rt);
          const id = rt.primaryClipId ?? s.selectedClipId;
          if (!id || rt.fallbackNoClip) {
            preventAndRun(() => toast(rt.message ?? "No clip."));
            return;
          }
          preventAndRun(() => runTimelineOp(() => s.unlinkClipsForClip(id)));
          break;
        }

        case "toggle_clip_linking":
          if (busy) return;
          preventAndRun(() => runTimelineOp(() => s.toggleClipLinking()));
          break;

        case "toggle_track_mute": {
          if (busy || !s.timeline) return;
          const rt = rtBase("toggle_track_mute");
          applyCursorSelection(rt);
          const tid =
            (rt.useCursorTime && rt.trackId) || (() => {
              const id = s.selectedClipId;
              if (!id) return null;
              const hit = findClipById(s.timeline!, id);
              return hit?.trackId ?? null;
            })();
          if (!tid) {
            preventAndRun(() => toast("No track under cursor."));
            return;
          }
          preventAndRun(() => runTimelineOp(() => s.toggleTrackMuteById(tid)));
          break;
        }

        case "toggle_track_lock": {
          if (busy || !s.timeline) return;
          const rt = rtBase("toggle_track_lock");
          applyCursorSelection(rt);
          if (!rt.trackId) {
            preventAndRun(() => toast("No track under cursor."));
            return;
          }
          preventAndRun(() => runTimelineOp(() => s.toggleTrackLockById(rt.trackId!)));
          break;
        }

        case "mute_clip": {
          if (busy || !s.timeline) return;
          const rt = rtBase("mute_clip");
          applyCursorSelection(rt);
          const id = rt.primaryClipId ?? s.selectedClipId;
          if (!id || rt.fallbackNoClip) {
            preventAndRun(() => toast(rt.message ?? "No clip."));
            return;
          }
          preventAndRun(() => runTimelineOp(() => s.muteClipToggleById(id)));
          break;
        }

        case "trim_start_to_cursor":
        case "trim_end_to_cursor": {
          if (busy || !s.timeline) return;
          const rt = rtBase(matchedId);
          applyCursorSelection(rt);
          if (rt.fallbackNoClip || !rt.primaryClipId) {
            preventAndRun(() => toast(rt.message ?? "No clip."));
            return;
          }
          const hit = findClipById(s.timeline, rt.primaryClipId);
          if (!hit || hit.trackType === "caption") {
            preventAndRun(() => toast("Cannot trim this clip."));
            return;
          }
          const tr = s.timeline.tracks?.find((x) => x.id === hit.trackId);
          if (tr?.locked) {
            preventAndRun(() => toast("Track is locked."));
            return;
          }
          const edge = matchedId === "trim_start_to_cursor" ? "start" : "end";
          const t = rt.timeSeconds;
          preventAndRun(() =>
            runTimelineOp(() =>
              s.trimTimelineEdge(rt.primaryClipId!, edge, t),
            ),
          );
          break;
        }

        case "move_playhead_to_cursor": {
          const rt = rtBase("move_playhead_to_cursor");
          if (!rt.useCursorTime) {
            preventAndRun(() => toast("Move pointer over the timeline."));
            return;
          }
          preventAndRun(() => {
            useTimelineStore.getState().setTimelinePlaying(false);
            s.setPlayheadSeconds(rt.timeSeconds);
          });
          break;
        }

        case "save_plan": {
          const canSave =
            Boolean(s.timeline && s.currentPlanName) &&
            s.isDirty &&
            s.saveStatus !== "saving" &&
            !s.timelineLoading;
          if (!canSave) return;
          preventAndRun(() => void s.savePlan());
          break;
        }
        case "export_render": {
          const rendering = s.renderStatus === "rendering";
          const canExport =
            Boolean(s.timeline && s.currentPlanName) &&
            !s.timelineLoading &&
            !rendering &&
            s.saveStatus !== "saving" &&
            !s.applyOperationInProgress;
          if (!canExport) return;
          preventAndRun(() => void s.exportPlan());
          break;
        }

        case "zoom_in": {
          preventAndRun(() => {
            const st = useTimelineStore.getState();
            const vp = timelineViewportElRef.current;
            const eds = useEditorSettingsStore.getState();
            const cur = getCursorContext();
            const useAnchor =
              eds.shortcutTargeting !== "playhead" &&
              cur.hasFinePointer &&
              (cur.region === "timeline" || cur.region === "ruler") &&
              vp &&
              st.timeline;
            if (!useAnchor) {
              st.setPxPerSecond(Math.min(MAX_PX_PER_SEC, st.pxPerSecond + ZOOM_STEP));
              return;
            }
            const raw = rawSecondsFromClientXInTimeline(
              cur.clientX,
              vp,
              st.pxPerSecond,
            );
            const t0 = snapShortcutTime(
              raw,
              st.timeline,
              st.pxPerSecond,
              st.playheadSeconds,
              eds.timelineSnapEnabled,
            );
            const oldPps = st.pxPerSecond;
            const newPps = Math.min(MAX_PX_PER_SEC, oldPps + ZOOM_STEP);
            const delta = t0 * newPps - t0 * oldPps;
            st.setPxPerSecond(newPps);
            vp.scrollLeft = Math.max(0, vp.scrollLeft + delta);
          });
          break;
        }
        case "zoom_out": {
          preventAndRun(() => {
            const st = useTimelineStore.getState();
            const vp = timelineViewportElRef.current;
            const eds = useEditorSettingsStore.getState();
            const cur = getCursorContext();
            const useAnchor =
              eds.shortcutTargeting !== "playhead" &&
              cur.hasFinePointer &&
              (cur.region === "timeline" || cur.region === "ruler") &&
              vp &&
              st.timeline;
            if (!useAnchor) {
              st.setPxPerSecond(Math.max(MIN_PX_PER_SEC, st.pxPerSecond - ZOOM_STEP));
              return;
            }
            const raw = rawSecondsFromClientXInTimeline(
              cur.clientX,
              vp,
              st.pxPerSecond,
            );
            const t0 = snapShortcutTime(
              raw,
              st.timeline,
              st.pxPerSecond,
              st.playheadSeconds,
              eds.timelineSnapEnabled,
            );
            const oldPps = st.pxPerSecond;
            const newPps = Math.max(MIN_PX_PER_SEC, oldPps - ZOOM_STEP);
            const delta = t0 * newPps - t0 * oldPps;
            st.setPxPerSecond(newPps);
            vp.scrollLeft = Math.max(0, vp.scrollLeft + delta);
          });
          break;
        }

        case "play_pause":
          if (s.previewPanelMode !== "timeline") return;
          preventAndRun(() => s.toggleTimelinePlaying());
          break;

        case "step_frame_back":
        case "step_frame_forward": {
          if (s.previewPanelMode !== "timeline" || !s.timeline) return;
          const fps =
            typeof s.timeline.settings?.fps === "number" && s.timeline.settings.fps > 0
              ? s.timeline.settings.fps
              : 30;
          const dt = matchedId === "step_frame_back" ? -1 / fps : 1 / fps;
          preventAndRun(() => {
            useTimelineStore.getState().setTimelinePlaying(false);
            s.setPlayheadSeconds(Math.max(0, s.playheadSeconds + dt));
          });
          break;
        }

        case "jump_start":
          if (!s.timeline) return;
          preventAndRun(() => {
            useTimelineStore.getState().setTimelinePlaying(false);
            s.setPlayheadSeconds(0);
          });
          break;

        case "jump_end": {
          const tl = s.timeline;
          if (!tl) return;
          preventAndRun(() => {
            useTimelineStore.getState().setTimelinePlaying(false);
            s.setPlayheadSeconds(timelineEnd(tl));
          });
          break;
        }

        case "select_all_clips": {
          const tl = s.timeline;
          if (!tl) return;
          const ids: string[] = [];
          for (const tr of tl.tracks ?? []) {
            for (const c of tr.clips ?? []) {
              if (c.id) ids.push(c.id);
            }
          }
          if (ids.length === 0) return;
          preventAndRun(() => {
            const next =
              clipLinkingEnabled(tl) ? expandLinkedSelection(tl, ids) : ids;
            s.setSelectedClipIds(next);
          });
          break;
        }

        case "deselect_clips":
          preventAndRun(() => s.setSelectedClipIds([]));
          break;

        case "cheat_sheet":
          preventAndRun(() => useKeybindingsStore.getState().setCheatSheetOpen(true));
          break;

        case "open_keyboard_settings":
          preventAndRun(() =>
            useKeybindingsStore.getState().setKeyboardSettingsOpen(true),
          );
          break;

        default:
          break;
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}

export { reservedReason };
