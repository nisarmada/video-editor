import { useMemo, useState } from "react";
import {
  CANVAS_FPS_OPTIONS,
  DEFAULT_PROJECT_CANVAS,
  evenDimension,
  oddDimensionWarning,
  presetList,
  resolveProjectCanvas,
  scaledPresetSize,
  type CanvasPresetId,
  type ResolutionTier,
} from "../timeline/canvas";
import type { ProjectCanvas } from "../timeline/types";
import { useTimelineStore } from "../store/timelineStore";

/**
 * Preview limits: proxies are ~540p; fit/blur approximates export (CSS object-fit /
 * backdrop blur vs ffmpeg gblur). Cover position uses center in preview unless extended.
 */
export default function CanvasControls() {
  const timeline = useTimelineStore((s) => s.timeline);
  const applyOperation = useTimelineStore((s) => s.applyOperation);
  const busy = useTimelineStore((s) => s.applyOperationInProgress);

  const canvas = useMemo(
    () => resolveProjectCanvas(timeline?.settings),
    [timeline?.settings],
  );

  const [preset, setPreset] = useState<CanvasPresetId>("9:16");
  const [tier, setTier] = useState<ResolutionTier>("1080p");

  const warn = oddDimensionWarning(canvas);

  async function commitCanvas(next: ProjectCanvas) {
    if (!timeline) return;
    const width = evenDimension(next.width ?? 1080);
    const height = evenDimension(next.height ?? 1920);
    const fps = next.fps ?? 30;
    const block: ProjectCanvas = {
      width,
      height,
      fps,
      fit: next.fit ?? "contain",
      bar_fill: next.bar_fill ?? "black",
      fit_position_x: next.fit_position_x ?? 0.5,
      fit_position_y: next.fit_position_y ?? 0.5,
    };
    await applyOperation({
      operation: "set_timeline_settings",
      arguments: {
        properties: {
          canvas: block,
          width,
          height,
          fps,
        },
      },
    });
  }

  const applyPreset = async (
    id: CanvasPresetId,
    tierOverride?: ResolutionTier,
  ) => {
    setPreset(id);
    if (id === "custom") return;
    const t = tierOverride ?? tier;
    const { width, height } = scaledPresetSize(id, t);
    await commitCanvas({
      ...canvas,
      width,
      height,
      fps: canvas.fps ?? DEFAULT_PROJECT_CANVAS.fps,
    });
  };

  if (!timeline) return null;

  return (
    <div className="canvas-controls">
      <span className="canvas-controls__label">Canvas</span>
      <select
        aria-label="Canvas preset"
        disabled={busy}
        value={preset}
        onChange={(e) => void applyPreset(e.target.value as CanvasPresetId)}
      >
        {presetList().map((p) => (
          <option key={p.id} value={p.id}>
            {p.label}
          </option>
        ))}
        <option value="custom">Custom</option>
      </select>
      <select
        aria-label="Resolution tier"
        disabled={busy || preset === "custom"}
        value={tier}
        onChange={(e) => {
          const t = e.target.value as ResolutionTier;
          setTier(t);
          if (preset !== "custom") {
            void applyPreset(preset, t);
          }
        }}
      >
        <option value="720p">720p</option>
        <option value="1080p">1080p</option>
        <option value="1440p">1440p</option>
        <option value="4K">4K</option>
      </select>
      <span className="canvas-controls__size">
        {canvas.width}×{canvas.height} @ {canvas.fps} fps
      </span>
      <select
        aria-label="Frame rate"
        disabled={busy}
        value={canvas.fps ?? 30}
        onChange={(e) =>
          void commitCanvas({ ...canvas, fps: Number(e.target.value) })
        }
      >
        {CANVAS_FPS_OPTIONS.map((f) => (
          <option key={f} value={f}>
            {f} fps
          </option>
        ))}
      </select>
      <select
        aria-label="Fit mode"
        disabled={busy}
        value={canvas.fit ?? "contain"}
        onChange={(e) =>
          void commitCanvas({
            ...canvas,
            fit: e.target.value as "contain" | "cover",
          })
        }
      >
        <option value="contain">Contain</option>
        <option value="cover">Cover</option>
      </select>
      {(canvas.fit ?? "contain") === "contain" ? (
        <select
          aria-label="Letterbox fill"
          disabled={busy}
          value={canvas.bar_fill ?? "black"}
          onChange={(e) =>
            void commitCanvas({
              ...canvas,
              bar_fill: e.target.value as "black" | "blur",
            })
          }
        >
          <option value="black">Bars: black</option>
          <option value="blur">Bars: blur</option>
        </select>
      ) : null}
      {warn ? (
        <span className="canvas-controls__warn" title={warn}>
          ⚠
        </span>
      ) : null}
    </div>
  );
}
