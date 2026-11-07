/**
 * @vitest-environment jsdom
 */
import { describe, expect, it, vi } from "vitest";
import { ensureMediaElementSource } from "./timelineAudioGraph";

function makeFakeAudioContext() {
  const nodes: { disconnect: () => void }[] = [];
  return {
    createGain() {
      const g = { connect: vi.fn(), gain: { value: 1 } };
      nodes.push(g as unknown as { disconnect: () => void });
      return g;
    },
    createMediaElementSource(_el: HTMLMediaElement) {
      const s = {
        connect: vi.fn(),
        disconnect: vi.fn(),
      };
      nodes.push(s);
      return s;
    },
    destination: {},
    close: vi.fn(),
  } as unknown as AudioContext;
}

describe("ensureMediaElementSource", () => {
  it("creates source once per element+context and reconnects after src change without second create", () => {
    const ctx = makeFakeAudioContext();
    const master = ctx.createGain();
    const el = document.createElement("audio");
    el.src = "/a.mp3";

    const spy = vi.spyOn(ctx, "createMediaElementSource");

    const s1 = ensureMediaElementSource(ctx, master, el);
    expect(s1).not.toBeNull();
    expect(spy).toHaveBeenCalledTimes(1);

    el.src = "/b.mp3";
    el.load();

    const s2 = ensureMediaElementSource(ctx, master, el);
    expect(s2).toBe(s1);
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
