import type { RefObject } from "react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useWaveformCacheStore } from "../store/waveformCacheStore";

type Props = {
  /** Scroll container for virtualized draw */
  scrollRootRef: RefObject<HTMLElement | null>;
  source: string;
  sourceIn: number;
  sourceOut: number;
  /** Reserved: timeline speed does not change source-time peak positions */
  speed?: number;
  widthPx: number;
  heightPx: number;
  variant: "video" | "audio";
};

export default function ClipWaveformCanvas({
  scrollRootRef,
  source,
  sourceIn,
  sourceOut,
  widthPx,
  heightPx,
  variant,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const ensureFetch = useWaveformCacheStore((s) => s.ensureFetch);
  const wf = useWaveformCacheStore((s) => s.bySource[source]);

  useEffect(() => {
    const el = containerRef.current;
    const root = scrollRootRef.current;
    if (!el) return;

    const io = new IntersectionObserver(
      (entries) => {
        const e = entries[0];
        setVisible(Boolean(e?.isIntersecting));
      },
      { root: root ?? undefined, rootMargin: "80px", threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [scrollRootRef]);

  useEffect(() => {
    if (!visible) return;
    ensureFetch(source);
  }, [visible, source, ensureFetch]);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !visible || widthPx < 2 || heightPx < 2) return;

    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(2, Math.floor(widthPx * dpr));
    const h = Math.max(2, Math.floor(heightPx * dpr));
    canvas.width = w;
    canvas.height = h;
    canvas.style.width = `${widthPx}px`;
    canvas.style.height = `${heightPx}px`;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, w, h);

    if (!wf || wf.kind === "loading" || wf.kind === "idle") {
      ctx.fillStyle = "rgba(255,255,255,0.06)";
      ctx.fillRect(0, h - 2 * dpr, w, 2 * dpr);
      return;
    }
    if (wf.kind === "processing") {
      ctx.fillStyle = "rgba(255,255,255,0.05)";
      ctx.fillRect(0, h - 3 * dpr, w, 3 * dpr);
      return;
    }
    if (wf.kind === "failed" || wf.kind === "no_audio") {
      return;
    }

    const { peaks, sample_rate_hz_of_peaks: hz } = wf.data;
    if (!peaks.length || hz <= 0) return;

    const srcSpan = Math.max(sourceOut - sourceIn, 1e-6);
    const peak0 = Math.max(0, Math.floor(sourceIn * hz));
    const peak1 = Math.min(peaks.length - 1, Math.ceil(sourceOut * hz) - 1);
    if (peak1 < peak0) return;

    const stripTop = variant === "video" ? Math.floor(h * 0.62) : 0;
    const stripH = h - stripTop;
    const midY = stripTop + stripH / 2;
    const amp = stripH * 0.45;

    ctx.fillStyle = "rgba(200, 220, 255, 0.28)";

    const n = Math.min(w, 2000);
    for (let xi = 0; xi < n; xi++) {
      const u = (xi + 0.5) / n;
      const srcT = sourceIn + u * srcSpan;
      const pIdx = Math.min(peak1, Math.max(peak0, Math.floor(srcT * hz)));
      const [pmin, pmax] = peaks[pIdx];
      const lo = Math.max(-1, Math.min(1, pmin));
      const hi = Math.max(-1, Math.min(1, pmax));
      const y1 = midY - hi * amp;
      const y2 = midY - lo * amp;
      const top = Math.min(y1, y2);
      const bh = Math.max(1, Math.abs(y2 - y1));
      const x = (xi / n) * w;
      const cw = Math.max(1, w / n);
      ctx.fillRect(x, top, cw, bh);
    }
  }, [wf, visible, sourceIn, sourceOut, widthPx, heightPx, variant]);

  return (
    <div
      ref={containerRef}
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
      }}
    >
      <canvas ref={canvasRef} style={{ display: "block" }} />
    </div>
  );
}
