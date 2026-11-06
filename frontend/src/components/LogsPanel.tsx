import { useEffect, useRef, useState } from "react";
import { fetchLogs, type LogEntry } from "../api/logsApi";

type Props = {
  expanded: boolean;
  onToggle: () => void;
};

export default function LogsPanel({ expanded, onToggle }: Props) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const sinceRef = useRef(0);

  useEffect(() => {
    if (!expanded) return;
    sinceRef.current = 0;
    setEntries([]);
    const tick = () => {
      void fetchLogs(sinceRef.current)
        .then((r) => {
          if (r.entries.length) {
            setEntries((prev) => [...prev, ...r.entries].slice(-300));
          }
          sinceRef.current = r.latest_id;
        })
        .catch(() => {
          /* keep last entries */
        });
    };
    tick();
    const id = window.setInterval(tick, 2000);
    return () => window.clearInterval(id);
  }, [expanded]);

  return (
    <div className={`logs-panel${expanded ? " logs-panel--open" : ""}`}>
      <button
        type="button"
        className="logs-panel__toggle"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        Server logs {expanded ? "▼" : "▶"}
      </button>
      {expanded && (
        <pre className="logs-panel__pre" role="log">
          {entries.length === 0
            ? "(no entries yet — use the app and refresh)"
            : entries
                .map(
                  (e) =>
                    `[${e.level}] ${new Date(e.ts * 1000).toLocaleTimeString()} ${e.message}`,
                )
                .join("\n")}
        </pre>
      )}
    </div>
  );
}
