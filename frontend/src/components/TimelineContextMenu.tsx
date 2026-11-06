import type { TrackType } from "../timeline/types";

export type ContextMenuState = {
  x: number;
  y: number;
  clipId: string;
  trackId: string;
  trackType: TrackType;
} | null;

type Item = {
  label: string;
  shortcut?: string;
  disabled?: boolean;
  onSelect: () => void;
};

export default function TimelineContextMenu({
  state,
  items,
  onClose,
}: {
  state: ContextMenuState;
  items: Item[];
  onClose: () => void;
}) {
  if (!state) return null;

  return (
    <>
      <div
        className="tl-context-menu-backdrop"
        aria-hidden
        onClick={onClose}
        onContextMenu={(e) => e.preventDefault()}
      />
      <div
        className="tl-context-menu"
        style={{ left: state.x, top: state.y }}
        role="menu"
      >
        {items.map((it) => (
          <button
            key={it.label}
            type="button"
            role="menuitem"
            className="tl-context-menu__item"
            disabled={it.disabled}
            onClick={() => {
              if (!it.disabled) it.onSelect();
              onClose();
            }}
          >
            <span>{it.label}</span>
            {it.shortcut ? (
              <span className="tl-context-menu__shortcut">{it.shortcut}</span>
            ) : null}
          </button>
        ))}
      </div>
    </>
  );
}
