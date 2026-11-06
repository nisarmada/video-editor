import { useEffect, useState } from "react";
import {
  fetchSettings,
  putPlannerApiKey,
  putSettings,
  testPlannerConnection,
  type PublicSettings,
} from "../api/settings";
import { useTimelineStore } from "../store/timelineStore";

type Props = {
  open: boolean;
  onClose: () => void;
};

/**
 * Folder names are one segment under the project root (backend enforces).
 * API key is write-only on the server; we never show the value back.
 */
export default function SettingsPanel({ open, onClose }: Props) {
  const setUiBannerError = useTimelineStore((s) => s.setUiBannerError);
  const [loading, setLoading] = useState(false);
  const [s, setS] = useState<PublicSettings | null>(null);
  const [footage, setFootage] = useState("");
  const [plans, setPlans] = useState("");
  const [output, setOutput] = useState("");
  const [captions, setCaptions] = useState(false);
  const [maxLength, setMaxLength] = useState("");
  const [keyInput, setKeyInput] = useState("");
  const [testStatus, setTestStatus] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    void fetchSettings()
      .then((data) => {
        if (cancelled) return;
        setS(data);
        setFootage(data.paths.footage);
        setPlans(data.paths.plans);
        setOutput(data.paths.output);
        setCaptions(data.render_defaults.captions);
        setMaxLength(
          data.render_defaults.max_length != null
            ? String(data.render_defaults.max_length)
            : "",
        );
        setTestStatus(null);
      })
      .catch((e: unknown) => {
        setUiBannerError(
          e instanceof Error ? e.message : "Failed to load settings",
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, setUiBannerError]);

  if (!open) return null;

  const savePathsAndDefaults = async () => {
    setLoading(true);
    try {
      const ml = maxLength.trim() === "" ? null : Number(maxLength);
      const data = await putSettings({
        paths: { footage, plans, output },
        render_defaults: {
          captions,
          max_length: ml != null && !Number.isNaN(ml) ? ml : null,
        },
      });
      setS(data);
    } catch (e) {
      setUiBannerError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setLoading(false);
    }
  };

  const saveKey = async () => {
    if (!keyInput.trim()) {
      setUiBannerError("Paste an API key first.");
      return;
    }
    setLoading(true);
    try {
      await putPlannerApiKey(keyInput.trim());
      setKeyInput("");
      const data = await fetchSettings();
      setS(data);
    } catch (e) {
      setUiBannerError(e instanceof Error ? e.message : "Could not save key");
    } finally {
      setLoading(false);
    }
  };

  const runTest = async () => {
    setTestStatus(null);
    setLoading(true);
    try {
      await testPlannerConnection();
      setTestStatus("Connection OK.");
    } catch (e) {
      setTestStatus(e instanceof Error ? e.message : "Test failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="modal-sheet"
        role="dialog"
        aria-label="Settings"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-sheet__header">
          <h2 className="modal-sheet__title">Settings</h2>
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Close
          </button>
        </div>
        {loading && !s ? (
          <p className="modal-sheet__muted">Loading…</p>
        ) : (
          <div className="modal-sheet__body">
            <section className="settings-block">
              <h3>Planner API key</h3>
              <p className="settings-hint">
                Stored on disk only; the app never sends it back to the browser.
                Status:{" "}
                <strong>
                  {s?.planner_api_key_configured ? "Configured" : "Not set"}
                </strong>
              </p>
              <label className="settings-label">
                Key
                <input
                  type="password"
                  autoComplete="off"
                  value={keyInput}
                  onChange={(e) => setKeyInput(e.target.value)}
                  placeholder="sk-ant-…"
                />
              </label>
              <div className="settings-actions">
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={loading}
                  onClick={() => void saveKey()}
                >
                  Save key
                </button>
                <button
                  type="button"
                  className="btn btn--ghost"
                  disabled={loading}
                  onClick={() => void runTest()}
                >
                  Test connection
                </button>
              </div>
              {testStatus && (
                <p className={testStatus.startsWith("Connection") ? "settings-ok" : "settings-warn"}>
                  {testStatus}
                </p>
              )}
            </section>

            <section className="settings-block">
              <h3>Project folders</h3>
              <p className="settings-hint">
                Single folder name under the project root for each (e.g. footage,
                plans, output). Changing names creates those folders if needed.
              </p>
              <label className="settings-label">
                Footage
                <input value={footage} onChange={(e) => setFootage(e.target.value)} />
              </label>
              <label className="settings-label">
                Plans
                <input value={plans} onChange={(e) => setPlans(e.target.value)} />
              </label>
              <label className="settings-label">
                Output
                <input value={output} onChange={(e) => setOutput(e.target.value)} />
              </label>
            </section>

            <section className="settings-block">
              <h3>Default export options</h3>
              <label className="settings-inline">
                <input
                  type="checkbox"
                  checked={captions}
                  onChange={(e) => setCaptions(e.target.checked)}
                />
                Burn-in captions when exporting
              </label>
              <label className="settings-label">
                Max length (seconds, empty = no limit)
                <input
                  type="text"
                  inputMode="decimal"
                  value={maxLength}
                  onChange={(e) => setMaxLength(e.target.value)}
                />
              </label>
              <button
                type="button"
                className="btn btn--primary"
                disabled={loading}
                onClick={() => void savePathsAndDefaults()}
              >
                Save folders & defaults
              </button>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
