/**
 * CapCut-style top strip. Only "Media" is wired; others are labeled as not built.
 */
const CATEGORIES: { id: string; label: string; implemented: boolean }[] = [
  { id: "media", label: "Media", implemented: true },
  { id: "audio", label: "Audio", implemented: false },
  { id: "text", label: "Text", implemented: false },
  { id: "stickers", label: "Stickers", implemented: false },
  { id: "effects", label: "Effects", implemented: false },
  { id: "transitions", label: "Transitions", implemented: false },
  { id: "filters", label: "Filters", implemented: false },
];

export default function AssetCategoryStrip() {
  return (
    <nav className="asset-strip" aria-label="Asset categories">
      {CATEGORIES.map((c) => (
        <div
          key={c.id}
          className={
            "asset-strip__item" +
            (c.implemented ? " asset-strip__item--active" : " asset-strip__item--stub")
          }
          title={
            c.implemented
              ? "Footage from footage/ folder"
              : "Not implemented in this app"
          }
        >
          <span>{c.label}</span>
          {!c.implemented && (
            <span className="asset-strip__na" aria-hidden>
              —
            </span>
          )}
        </div>
      ))}
    </nav>
  );
}
