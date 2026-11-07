/**
 * One MediaElementAudioSourceNode per HTMLMediaElement per AudioContext.
 * Browsers throw if createMediaElementSource is called twice on the same element.
 */

type WireEntry = {
  context: AudioContext;
  source: MediaElementAudioSourceNode;
};

const mediaWireCache = new WeakMap<HTMLMediaElement, WireEntry>();

/**
 * Connect element audio to the graph once. Reuses cached source when ctx matches.
 * Returns null on failure (caller should surface UI message).
 */
export function ensureMediaElementSource(
  ctx: AudioContext,
  destination: AudioNode,
  el: HTMLMediaElement,
): MediaElementAudioSourceNode | null {
  const prev = mediaWireCache.get(el);
  if (prev && prev.context === ctx) {
    return prev.source;
  }
  if (prev && prev.context !== ctx) {
    try {
      prev.source.disconnect();
    } catch {
      /* ignore */
    }
    mediaWireCache.delete(el);
  }
  try {
    const source = ctx.createMediaElementSource(el);
    source.connect(destination);
    mediaWireCache.set(el, { context: ctx, source });
    return source;
  } catch (e) {
    console.error("ensureMediaElementSource failed:", e);
    return null;
  }
}

/** Disconnect and remove cache entry (e.g. effect cleanup). */
export function teardownMediaElementWire(el: HTMLMediaElement): void {
  const w = mediaWireCache.get(el);
  if (!w) return;
  try {
    w.source.disconnect();
  } catch {
    /* ignore */
  }
  mediaWireCache.delete(el);
}
