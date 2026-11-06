import MediaBin from "./components/MediaBin";
import TimelineVideoPreview from "./components/TimelineVideoPreview";
import TimelinePanel from "./components/TimelinePanel";
import { useTimelineStore } from "./store/timelineStore";
import "./App.css";

export default function App() {
  const planName = useTimelineStore((s) => s.planName);
  const timelineBrief = useTimelineStore((s) => s.timeline?.brief);

  return (
    <div className="app">
      <header className="app-bar">
        <span className="app-bar__title">Video Editor</span>
        <span className="app-bar__plan">Plan: {planName}.json</span>
        <div className="app-bar__actions">
          <button type="button" className="app-bar__btn" disabled>
            Save
          </button>
          <button type="button" className="app-bar__btn" disabled>
            Export
          </button>
          <button type="button" className="app-bar__btn" disabled>
            Planner…
          </button>
        </div>
      </header>

      <div className="upper-workspace">
        <MediaBin />

        <div className="resize-handle" aria-hidden title="Resize (coming soon)" />

        <section className="panel panel--preview" aria-label="Preview">
          <div className="panel__header">Preview — timeline (video track)</div>
          <div className="panel__body panel__body--preview">
            <TimelineVideoPreview />
          </div>
        </section>

        <div className="resize-handle" aria-hidden title="Resize (coming soon)" />

        <section className="panel panel--properties" aria-label="Properties">
          <div className="panel__header">Properties</div>
          <div className="panel__body">
            <div className="props-grid">
              <div className="props-row">
                <label>Plan name</label>
                <span>{planName}</span>
              </div>
              <div className="props-row">
                <label>Brief</label>
                <span>{timelineBrief ?? "—"}</span>
              </div>
              <div className="props-row">
                <label>Selection</label>
                <span>None</span>
              </div>
            </div>
          </div>
        </section>
      </div>

      <div className="resize-handle resize-handle--horizontal" aria-hidden />

      <TimelinePanel />
    </div>
  );
}
