import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import JASSUB from "jassub";
import {
  deleteUserCaptionStyle,
  fetchCaptionStylesList,
  postCaptionsAss,
  putUserCaptionStyle,
  type CaptionStylesListResponse,
} from "../api/captions";
import {
  JASSUB_DEFAULT_WOFF2_URL,
  JASSUB_LEGACY_WASM_URL,
  JASSUB_MODERN_WASM_URL,
  JASSUB_WASM_URL,
  JASSUB_WORKER_URL,
} from "../lib/jassubAssets";
import { useTimelineStore } from "../store/timelineStore";
import type {
  CaptionAnimation,
  CaptionStyle,
  TimelineClip,
  TimelineV2,
} from "../timeline/types";

const ANIMATIONS: CaptionAnimation[] = [
  "none",
  "word_highlight",
  "word_pop",
  "word_box",
  "karaoke_sweep",
  "typewriter",
  "bounce_in",
  "fade_in",
  "neon",
];

const PREVIEW_VIDEO_SRC = "/caption-preview-base.mp4";

const MINI_FONT_MAP: Record<string, string> = {
  "liberation sans": JASSUB_DEFAULT_WOFF2_URL,
  poppins: "/api/fonts/dir/Poppins-Regular.ttf",
  montserrat: "/api/fonts/dir/Montserrat-Variable.ttf",
  inter: "/api/fonts/dir/Inter-Variable.ttf",
  oswald: "/api/fonts/dir/Oswald-Variable.ttf",
  anton: "/api/fonts/dir/Anton-Regular.ttf",
  "bebas neue": "/api/fonts/dir/BebasNeue-Regular.ttf",
  bangers: "/api/fonts/dir/Bangers-Regular.ttf",
  arial: "/api/fonts/dir/Poppins-Regular.ttf",
};

function findVideoClipById(
  timeline: TimelineV2,
  clipId: string | null,
): TimelineClip | null {
  if (!clipId) return null;
  const vt = timeline.tracks.find((t) => t.type === "video");
  for (const c of vt?.clips ?? []) {
    if (c.id === clipId) return c;
  }
  return null;
}

/** Merge preset row + optional plan/clip fields into one editable style */
function mergeResolvedStyle(
  lists: CaptionStylesListResponse | null,
  raw: CaptionStyle | undefined,
): CaptionStyle {
  const built = lists?.built_in ?? [];
  const user = lists?.user ?? [];
  const pid = raw?.preset ?? "bold_pop";
  const presetRow =
    built.find((x) => x.id === pid) ?? user.find((x) => x.id === pid);
  const base: Record<string, unknown> = {};
  if (presetRow) {
    for (const [k, v] of Object.entries(presetRow)) {
      if (k === "id" || k === "name") continue;
      base[k] = v;
    }
  }
  const out: Record<string, unknown> = { ...base, ...(raw ?? {}) };
  if (out.preset == null || out.preset === "") out.preset = pid;
  return out as CaptionStyle;
}

function styleForEditor(
  applyScope: "plan" | "clip",
  timeline: TimelineV2,
  selectedClipId: string | null,
  lists: CaptionStylesListResponse | null,
): CaptionStyle {
  const planRaw = timeline.settings?.caption_style;
  if (applyScope === "clip" && selectedClipId) {
    const clip = findVideoClipById(timeline, selectedClipId);
    const ovr = clip?.style_override;
    if (ovr && typeof ovr === "object") {
      return mergeResolvedStyle(lists, {
        ...planRaw,
        ...ovr,
        preset: ovr.preset ?? planRaw?.preset ?? "bold_pop",
      });
    }
  }
  return mergeResolvedStyle(lists, planRaw);
}

function planBaselineStyle(
  lists: CaptionStylesListResponse | null,
  timeline: TimelineV2,
): CaptionStyle {
  return mergeResolvedStyle(lists, timeline.settings?.caption_style);
}

/** Looping mini-preview for each preset (same ASS generator as export). */
function MiniJassubPresetPreview({ style }: { style: Record<string, unknown> }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const jRef = useRef<InstanceType<typeof JASSUB> | null>(null);
  const key = JSON.stringify(style);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const parsed = JSON.parse(key) as Record<string, unknown>;
    const stub: TimelineV2 = {
      schema_version: 2,
      settings: { width: 108, height: 192 },
      tracks: [],
    };

    const j = new JASSUB({
      video,
      workerUrl: JASSUB_WORKER_URL,
      wasmUrl: JASSUB_WASM_URL,
      legacyWasmUrl: JASSUB_LEGACY_WASM_URL,
      modernWasmUrl: JASSUB_MODERN_WASM_URL,
      availableFonts: MINI_FONT_MAP,
      fallbackFont: "liberation sans",
      useLocalFonts: false,
      dropAllBlur: false,
      subContent: `[Events]\n`,
    });
    jRef.current = j;

    let cancelled = false;
    void (async () => {
      try {
        const { ass } = await postCaptionsAss({
          timeline: stub,
          preview_preset: parsed,
        });
        if (!cancelled && jRef.current) {
          jRef.current.setTrack(ass);
        }
      } catch (e) {
        console.warn("Preset preview ASS failed:", e);
      }
    })();

    video.loop = true;
    video.muted = true;
    video.playsInline = true;
    void video.play().catch(() => {});

    return () => {
      cancelled = true;
      j.destroy();
      jRef.current = null;
    };
  }, [key]);

  return (
    <div className="caption-preset-card__ass-host">
      <video
        ref={videoRef}
        className="caption-preset-card__ass-video"
        src={PREVIEW_VIDEO_SRC}
      />
    </div>
  );
}

export default function CaptionsPanel() {
  const timeline = useTimelineStore((s) => s.timeline);
  const selectedClipId = useTimelineStore((s) => s.selectedClipId);
  const setCaptionStyleDraft = useTimelineStore((s) => s.setCaptionStyleDraft);
  const setClipStyleOverrideDraft = useTimelineStore(
    (s) => s.setClipStyleOverrideDraft,
  );
  const applyInProgress = useTimelineStore((s) => s.applyOperationInProgress);
  const previewClipOnly = useTimelineStore((s) => s.captionPreviewClipOnly);
  const setCaptionPreviewClipOnly = useTimelineStore(
    (s) => s.setCaptionPreviewClipOnly,
  );
  const safeAreaGuide = useTimelineStore((s) => s.captionSafeAreaGuide);
  const setCaptionSafeAreaGuide = useTimelineStore(
    (s) => s.setCaptionSafeAreaGuide,
  );

  const [lists, setLists] = useState<CaptionStylesListResponse | null>(null);
  const [listsErr, setListsErr] = useState<string | null>(null);
  const [applyScope, setApplyScope] = useState<"plan" | "clip">("plan");
  const [wordCount, setWordCount] = useState<number | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const data = await fetchCaptionStylesList();
        setLists(data);
        setListsErr(null);
      } catch (e) {
        setListsErr(e instanceof Error ? e.message : "Could not load presets");
      }
    })();
  }, []);

  const selectedVideoClip = useMemo(
    () => (timeline ? findVideoClipById(timeline, selectedClipId) : null),
    [timeline, selectedClipId],
  );

  const editorStyle = useMemo(
    () =>
      timeline
        ? styleForEditor(applyScope, timeline, selectedClipId, lists)
        : ({ preset: "bold_pop" } as CaptionStyle),
    [applyScope, timeline, selectedClipId, lists],
  );

  const presetId = String(editorStyle.preset ?? "bold_pop");

  useEffect(() => {
    if (!timeline) {
      setWordCount(null);
      return;
    }
    let cancelled = false;
    const t = window.setTimeout(() => {
      void (async () => {
        try {
          const { word_count: wc } = await postCaptionsAss({ timeline });
          if (!cancelled) setWordCount(wc);
        } catch {
          if (!cancelled) setWordCount(null);
        }
      })();
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [timeline]);

  const baselinePlan = useMemo(
    () => (timeline && lists ? planBaselineStyle(lists, timeline) : null),
    [timeline, lists],
  );

  const commitPlanStyle = useCallback(
    async (next: CaptionStyle) => {
      await setCaptionStyleDraft(next);
    },
    [setCaptionStyleDraft],
  );

  const commitClipOverride = useCallback(
    async (next: CaptionStyle) => {
      if (!selectedClipId || !selectedVideoClip || !timeline || !baselinePlan) {
        return;
      }
      const delta: Partial<CaptionStyle> = {};
      (Object.keys(next) as (keyof CaptionStyle)[]).forEach((k) => {
        if (next[k] !== baselinePlan[k]) {
          (delta as Record<string, unknown>)[k as string] = next[k];
        }
      });
      const hasDiff = Object.keys(delta).length > 0;
      await setClipStyleOverrideDraft(
        selectedClipId,
        hasDiff ? delta : null,
      );
    },
    [
      selectedClipId,
      selectedVideoClip,
      timeline,
      baselinePlan,
      setClipStyleOverrideDraft,
    ],
  );

  const patchField = useCallback(
    async <K extends keyof CaptionStyle>(key: K, value: CaptionStyle[K]) => {
      if (!timeline) return;
      const merged = { ...editorStyle, [key]: value };
      if (applyScope === "plan") {
        await commitPlanStyle(merged);
      } else {
        await commitClipOverride(merged);
      }
    },
    [timeline, editorStyle, applyScope, commitPlanStyle, commitClipOverride],
  );

  const fullPresetStyle = useCallback(
    (id: string): CaptionStyle => {
      const row =
        lists?.built_in.find((x) => x.id === id) ??
        lists?.user.find((x) => x.id === id);
      const o: Record<string, unknown> = row
        ? { ...row }
        : { preset: id };
      delete o.id;
      delete o.name;
      return o as CaptionStyle;
    },
    [lists],
  );

  const selectPreset = useCallback(
    async (id: string) => {
      const merged = fullPresetStyle(id);
      if (applyScope === "plan") {
        await setCaptionStyleDraft(merged);
      } else if (selectedClipId) {
        await setClipStyleOverrideDraft(selectedClipId, merged);
      }
    },
    [
      applyScope,
      selectedClipId,
      fullPresetStyle,
      setCaptionStyleDraft,
      setClipStyleOverrideDraft,
    ],
  );

  const resetToPreset = useCallback(async () => {
    if (applyScope === "plan") {
      await setCaptionStyleDraft(fullPresetStyle(presetId));
    } else if (selectedClipId) {
      await setClipStyleOverrideDraft(selectedClipId, null);
    }
  }, [
    applyScope,
    presetId,
    selectedClipId,
    fullPresetStyle,
    setCaptionStyleDraft,
    setClipStyleOverrideDraft,
  ]);

  const saveUserPreset = useCallback(async () => {
    const raw = window.prompt("New preset id (letters, numbers, underscore):");
    if (raw == null) return;
    const id = raw.trim();
    if (!id) return;
    const name = window.prompt("Display name:", id)?.trim() || id;
    try {
      const body: Record<string, unknown> = {
        id,
        name,
        ...editorStyle,
      };
      await putUserCaptionStyle(id, body);
      const data = await fetchCaptionStylesList();
      setLists(data);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "Save failed");
    }
  }, [editorStyle]);

  const renameUserPreset = useCallback(async () => {
    const user = lists?.user.find((x) => x.id === presetId);
    if (!user) {
      window.alert("Select a user preset first.");
      return;
    }
    const nid = window.prompt("New id:", String(user.id ?? ""))?.trim();
    if (nid == null || !nid) return;
    try {
      const body = { ...user, ...editorStyle, id: nid, name: user.name };
      await putUserCaptionStyle(nid, body);
      if (nid !== user.id) {
        await deleteUserCaptionStyle(String(user.id));
      }
      const data = await fetchCaptionStylesList();
      setLists(data);
      await selectPreset(nid);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "Rename failed");
    }
  }, [lists, presetId, editorStyle, selectPreset]);

  const deleteUserPreset = useCallback(async () => {
    const user = lists?.user.find((x) => x.id === presetId);
    if (!user) {
      window.alert("Only user presets can be deleted.");
      return;
    }
    if (!window.confirm(`Delete preset "${String(user.id)}"?`)) return;
    try {
      await deleteUserCaptionStyle(String(user.id));
      const data = await fetchCaptionStylesList();
      setLists(data);
      await selectPreset("bold_pop");
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "Delete failed");
    }
  }, [lists, presetId, selectPreset]);

  if (!timeline) {
    return <p className="panel-message">No timeline loaded.</p>;
  }

  const builtins = lists?.built_in ?? [];
  const userPresets = lists?.user ?? [];
  const allPresetRows = [...builtins, ...userPresets];

  return (
    <div className="captions-panel">
      {listsErr && <p className="captions-panel__warn">{listsErr}</p>}

      <div className="captions-panel__toolbar">
        <label className="captions-panel__check">
          <input
            type="checkbox"
            checked={previewClipOnly}
            onChange={(e) => setCaptionPreviewClipOnly(e.target.checked)}
          />
          Preview only selected clip
        </label>
        <label className="captions-panel__check">
          <input
            type="checkbox"
            checked={safeAreaGuide}
            onChange={(e) => setCaptionSafeAreaGuide(e.target.checked)}
          />
          9:16 safe area
        </label>
      </div>

      <fieldset className="captions-panel__scope" disabled={applyInProgress}>
        <legend>Apply style to</legend>
        <label>
          <input
            type="radio"
            name="cap-scope"
            checked={applyScope === "plan"}
            onChange={() => setApplyScope("plan")}
          />
          All captions (plan)
        </label>
        <label>
          <input
            type="radio"
            name="cap-scope"
            checked={applyScope === "clip"}
            onChange={() => setApplyScope("clip")}
            disabled={!selectedVideoClip}
          />
          Selected clip only
        </label>
      </fieldset>
      {applyScope === "clip" && !selectedVideoClip && (
        <p className="panel-message">
          Select a video clip on the timeline to edit overrides.
        </p>
      )}

      <section className="captions-panel__section">
        <h4 className="captions-panel__h">Presets</h4>
        <div className="caption-preset-grid">
          {allPresetRows.map((row) => {
            const id = String(row.id ?? "");
            const label = String(row.name ?? id);
            const previewStyle: Record<string, unknown> = { ...row };
            delete previewStyle.id;
            delete previewStyle.name;
            return (
              <button
                key={id || label}
                type="button"
                className={`caption-preset-card${presetId === id ? " caption-preset-card--active" : ""}`}
                onClick={() => void selectPreset(id)}
              >
                <MiniJassubPresetPreview style={previewStyle} />
                <span className="caption-preset-card__label">{label}</span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="captions-panel__section">
        <h4 className="captions-panel__h">Style</h4>
        <div className="captions-editor">
          <label className="props-row">
            Font
            <select
              value={String(editorStyle.font_family ?? "Poppins")}
              disabled={applyInProgress}
              className="caption-font-select"
              style={{
                fontFamily: `"${String(editorStyle.font_family ?? "Poppins")}", sans-serif`,
              }}
              onChange={(e) => void patchField("font_family", e.target.value)}
            >
              {[
                "Poppins",
                "Montserrat",
                "Inter",
                "Oswald",
                "Anton",
                "Bebas Neue",
                "Bangers",
                "Arial",
              ].map((f) => (
                <option
                  key={f}
                  value={f}
                  style={{ fontFamily: `"${f}", sans-serif` }}
                >
                  {f}
                </option>
              ))}
            </select>
          </label>

          <ColorRow
            label="Text"
            value={editorStyle.text_color ?? "#FFFFFF"}
            onChange={(v) => void patchField("text_color", v)}
            disabled={applyInProgress}
          />
          <ColorRow
            label="Active word"
            value={editorStyle.active_word_color ?? "#FFFF00"}
            onChange={(v) => void patchField("active_word_color", v)}
            disabled={applyInProgress}
          />
          <ColorRow
            label="Outline"
            value={editorStyle.outline_color ?? "#000000"}
            onChange={(v) => void patchField("outline_color", v)}
            disabled={applyInProgress}
          />
          <ColorRow
            label="Shadow"
            value={editorStyle.shadow_color ?? "#000000"}
            onChange={(v) => void patchField("shadow_color", v)}
            disabled={applyInProgress}
          />
          <ColorRow
            label="Box"
            value={editorStyle.box_color ?? "#000000"}
            onChange={(v) => void patchField("box_color", v)}
            disabled={applyInProgress}
          />

          <SliderRow
            label="Font size (× height)"
            min={0.02}
            max={0.12}
            step={0.002}
            value={Number(editorStyle.font_size ?? 0.04)}
            onChange={(v) => void patchField("font_size", v)}
            disabled={applyInProgress}
          />
          <SliderRow
            label="Outline width"
            min={0}
            max={8}
            step={0.25}
            value={Number(editorStyle.outline_width ?? 2)}
            onChange={(v) => void patchField("outline_width", v)}
            disabled={applyInProgress}
          />
          <SliderRow
            label="Shadow X"
            min={0}
            max={12}
            step={1}
            value={Number(editorStyle.shadow_offset?.[0] ?? 2)}
            onChange={(v) =>
              void patchField("shadow_offset", [
                v,
                Number(editorStyle.shadow_offset?.[1] ?? 2),
              ])
            }
            disabled={applyInProgress}
          />
          <SliderRow
            label="Shadow Y"
            min={0}
            max={12}
            step={1}
            value={Number(editorStyle.shadow_offset?.[1] ?? 2)}
            onChange={(v) =>
              void patchField("shadow_offset", [
                Number(editorStyle.shadow_offset?.[0] ?? 2),
                v,
              ])
            }
            disabled={applyInProgress}
          />
          <SliderRow
            label="Position Y (% from top)"
            min={5}
            max={95}
            step={1}
            value={Number(editorStyle.position_y ?? 78)}
            onChange={(v) => void patchField("position_y", v)}
            disabled={applyInProgress}
          />
          <SliderRow
            label="Animation intensity"
            min={0}
            max={1}
            step={0.05}
            value={Number(editorStyle.animation_intensity ?? 0.8)}
            onChange={(v) => void patchField("animation_intensity", v)}
            disabled={applyInProgress}
          />
          <SliderRow
            label="Active word scale"
            min={0.5}
            max={2}
            step={0.01}
            value={Number(editorStyle.active_word_scale ?? 1.15)}
            onChange={(v) => void patchField("active_word_scale", v)}
            disabled={applyInProgress}
          />
          <SliderRow
            label="Words per line"
            min={1}
            max={5}
            step={1}
            value={Number(editorStyle.max_words_per_line ?? 3)}
            onChange={(v) => void patchField("max_words_per_line", Math.round(v))}
            disabled={applyInProgress}
          />
          <SliderRow
            label="Max lines"
            min={1}
            max={5}
            step={1}
            value={Number(editorStyle.max_lines ?? 3)}
            onChange={(v) => void patchField("max_lines", Math.round(v))}
            disabled={applyInProgress}
          />
          <SliderRow
            label="Line spacing"
            min={1}
            max={2}
            step={0.05}
            value={Number(editorStyle.line_spacing ?? 1.1)}
            onChange={(v) => void patchField("line_spacing", v)}
            disabled={applyInProgress}
          />
          <SliderRow
            label="Box opacity"
            min={0}
            max={1}
            step={0.05}
            value={Number(editorStyle.box_opacity ?? 0)}
            onChange={(v) => void patchField("box_opacity", v)}
            disabled={applyInProgress}
          />
          <SliderRow
            label="Box padding"
            min={0}
            max={24}
            step={1}
            value={Number(editorStyle.box_padding ?? 4)}
            onChange={(v) => void patchField("box_padding", v)}
            disabled={applyInProgress}
          />

          <label className="props-row">
            Animation
            <select
              value={editorStyle.animation ?? "word_highlight"}
              disabled={applyInProgress}
              onChange={(e) =>
                void patchField("animation", e.target.value as CaptionAnimation)
              }
            >
              {ANIMATIONS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>

          <div className="captions-editor__toggles">
            <label>
              <input
                type="checkbox"
                checked={Boolean(editorStyle.bold)}
                disabled={applyInProgress}
                onChange={(e) => void patchField("bold", e.target.checked)}
              />
              Bold
            </label>
            <label>
              <input
                type="checkbox"
                checked={Boolean(editorStyle.italic)}
                disabled={applyInProgress}
                onChange={(e) => void patchField("italic", e.target.checked)}
              />
              Italic
            </label>
            <label>
              <input
                type="checkbox"
                checked={Boolean(editorStyle.uppercase)}
                disabled={applyInProgress}
                onChange={(e) => void patchField("uppercase", e.target.checked)}
              />
              Uppercase
            </label>
          </div>
        </div>
      </section>

      <div className="captions-panel__actions">
        <button
          type="button"
          className="btn btn--ghost"
          disabled={applyInProgress}
          onClick={() => void resetToPreset()}
        >
          Reset to preset
        </button>
        <button
          type="button"
          className="btn btn--primary"
          disabled={applyInProgress}
          onClick={() => void saveUserPreset()}
        >
          Save as preset
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          disabled={applyInProgress}
          onClick={() => void renameUserPreset()}
        >
          Rename
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          disabled={applyInProgress}
          onClick={() => void deleteUserPreset()}
        >
          Delete
        </button>
      </div>

      <section className="captions-panel__section">
        <h4 className="captions-panel__h">Words & generate</h4>
        <p className="panel-message">
          {wordCount === null
            ? "Checking transcript words…"
            : wordCount === 0
              ? 'No words yet — run the ingest pipeline (faster-whisper) on your footage so index/<clip>_transcript.json exists, then reload the plan.'
              : `${wordCount} word(s) on the timeline for captions.`}
        </p>
        <button
          type="button"
          className="btn btn--primary"
          disabled
          title="Run ingest / transcript on footage from the terminal; words load from index/"
        >
          Generate captions
        </button>
        <p className="panel-message captions-panel__hint">
          This button will call ingest once that API exists. For now, generate
          words with your pipeline scripts, then export with captions enabled in
          Settings.
        </p>
      </section>
    </div>
  );
}

function ColorRow({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  const hex = value.startsWith("#") ? value.slice(0, 7) : "#ffffff";
  return (
    <label className="props-row">
      {label}
      <input
        type="color"
        value={hex}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function SliderRow({
  label,
  min,
  max,
  step,
  value,
  onChange,
  disabled,
}: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  return (
    <label className="props-row">
      {label}{" "}
      <span className="captions-editor__slider-val">{value.toFixed(2)}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}
