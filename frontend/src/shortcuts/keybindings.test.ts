import { describe, expect, it } from "vitest";
import { chordKey, keydownMatchesChord } from "./normalize";
import {
  getEffectiveBindings,
  getBindingState,
  buildChordToActionMap,
  validateImportOverrides,
} from "./merge";
import { reservedReason } from "./reserved";

describe("normalize", () => {
  it("chordKey distinguishes mod", () => {
    expect(chordKey({ code: "KeyZ", mod: true })).toBe("mod+KeyZ");
    expect(chordKey({ code: "KeyZ" })).toBe("KeyZ");
  });

  it("keydownMatchesChord treats meta and ctrl as mod", () => {
    const chord = { code: "KeyS", mod: true };
    const ev = {
      code: "KeyS",
      metaKey: true,
      ctrlKey: false,
      shiftKey: false,
      altKey: false,
    } as KeyboardEvent;
    expect(keydownMatchesChord(ev, chord)).toBe(true);
  });
});

describe("merge overrides", () => {
  it("undefined override uses defaults", () => {
    const o = getEffectiveBindings("undo", {});
    expect(o.length).toBeGreaterThan(0);
    expect(o[0]?.code).toBe("KeyZ");
    expect(o[0]?.mod).toBe(true);
  });

  it("empty array means unbound", () => {
    expect(getEffectiveBindings("undo", { undo: [] })).toEqual([]);
    expect(getBindingState("undo", { undo: [] })).toBe("unbound");
  });

  it("custom list replaces defaults", () => {
    const custom = [{ code: "KeyY", mod: true }];
    expect(getEffectiveBindings("undo", { undo: custom })).toEqual(custom);
    expect(getBindingState("undo", { undo: custom })).toBe("customized");
  });
});

describe("conflict map", () => {
  it("last action in registry wins chord slot when duplicated", () => {
    const overrides = {
      undo: [{ code: "KeyX", mod: true }],
      redo: [{ code: "KeyX", mod: true }],
    };
    const map = buildChordToActionMap(overrides);
    /* SHORTCUT_ACTIONS lists undo before redo */
    expect(map.get("mod+KeyX")).toBe("redo");
  });
});

describe("import validation", () => {
  it("filters unknown ids", () => {
    const { overrides, unknownIds } = validateImportOverrides({
      keybindings: {
        undo: [{ code: "KeyP", mod: true }],
        not_a_real_action: [{ code: "KeyQ" }],
      },
    });
    expect(unknownIds).toContain("not_a_real_action");
    expect(overrides.undo?.length).toBe(1);
    expect(overrides.not_a_real_action).toBeUndefined();
  });
});

describe("reserved", () => {
  it("blocks ctrl+w style", () => {
    expect(reservedReason({ code: "KeyW", mod: true })).toBeTruthy();
  });
});
