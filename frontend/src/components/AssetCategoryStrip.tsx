import { useTimelineStore, type MediaBinCategory } from "../store/timelineStore";

type TabDef =
  | { id: MediaBinCategory; label: string; stub?: false }
  | { id: string; label: string; stub: true };

const TABS: TabDef[] = [
  { id: "all", label: "All" },
  { id: "video", label: "Media" },
  { id: "audio", label: "Audio" },
  { id: "text", label: "Text", stub: true },
  { id: "stickers", label: "Stickers", stub: true },
  { id: "effects", label: "Effects", stub: true },
  { id: "transitions", label: "Transitions", stub: true },
  { id: "filters", label: "Filters", stub: true },
];

export default function AssetCategoryStrip() {
  const category = useTimelineStore((s) => s.mediaBinCategory);
  const setCategory = useTimelineStore((s) => s.setMediaBinCategory);

  return (
    <nav className="asset-strip" aria-label="Asset categories">
      {TABS.map((c) => {
        const stub = "stub" in c && c.stub;
        const active = !stub && category === c.id;
        return (
          <button
            key={c.id}
            type="button"
            className={
              "asset-strip__item" +
              (active ? " asset-strip__item--active" : "") +
              (stub ? " asset-strip__item--stub" : "")
            }
            aria-pressed={!stub ? active : undefined}
            disabled={stub}
            title={
              stub
                ? "Not implemented"
                : c.id === "all"
                  ? "Show all footage"
                  : c.id === "video"
                    ? "Video files in footage/"
                    : "Audio-only files in footage/"
            }
            onClick={() => {
              if (stub) return;
              setCategory(c.id as MediaBinCategory);
            }}
          >
            <span>{c.label}</span>
            {stub && (
              <span className="asset-strip__na" aria-hidden>
                —
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
