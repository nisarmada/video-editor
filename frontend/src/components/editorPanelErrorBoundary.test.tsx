/**
 * @vitest-environment jsdom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import EditorPanelErrorBoundary from "./EditorPanelErrorBoundary";

let shouldThrow = true;

function Flaky() {
  if (shouldThrow) {
    throw new Error("render boom");
  }
  return <span>ok</span>;
}

describe("EditorPanelErrorBoundary", () => {
  let container: HTMLDivElement;
  let root: Root;

  afterEach(() => {
    act(() => {
      root?.unmount();
    });
    container?.remove();
    shouldThrow = true;
  });

  it("catches render error; Retry re-renders children after failure cleared", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    vi.spyOn(console, "error").mockImplementation(() => {});

    act(() => {
      root.render(
        <EditorPanelErrorBoundary name="Test panel">
          <Flaky />
        </EditorPanelErrorBoundary>,
      );
    });

    expect(container.textContent).toContain("Test panel");
    expect(container.textContent).toContain("render boom");

    shouldThrow = false;

    const retry = container.querySelector(
      ".panel-error-boundary__retry",
    ) as HTMLButtonElement | null;
    expect(retry).toBeTruthy();

    act(() => {
      retry!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.textContent).toContain("ok");
  });
});
