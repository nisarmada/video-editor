import { useEffect, useState } from "react";
import {
  fetchSettings,
  PLANNER_DEFAULTS,
  putPlannerApiKey,
  putSettings,
  testPlannerConnection,
  TRANSCRIPTION_DEFAULTS,
  EMBEDDING_DEFAULTS,
  type EmbeddingSettings,
  type PlannerSettings,
  type PublicSettings,
  type TranscriptionSettings,
} from "../api/settings";
import {
  clearPaidCaptionCaches,
  clearRegenerableCaches,
  fetchStorageStats,
  formatBytes,
  type StorageStats,
} from "../api/storage";
import { useTimelineStore } from "../store/timelineStore";

type Props = {
  open: boolean;
  onClose: () => void;
  onOpenKeyboardShortcuts?: () => void;
};

/**
 * Folder names are one segment under the project root (backend enforces).
 * API key is write-only on the server; we never show the value back.
 */
export default function SettingsPanel({
  open,
  onClose,
  onOpenKeyboardShortcuts,
}: Props) {
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
  const [cutRefineOn, setCutRefineOn] = useState(true);
  const [preRollMs, setPreRollMs] = useState("120");
  const [postRollMs, setPostRollMs] = useState("150");
  const [snapWinMs, setSnapWinMs] = useState("80");
  const [cutFadeMs, setCutFadeMs] = useState("20");
  const [planner, setPlanner] = useState<PlannerSettings>(PLANNER_DEFAULTS);
  const [transcription, setTranscription] = useState<TranscriptionSettings>(
    TRANSCRIPTION_DEFAULTS,
  );
  const [embedding, setEmbedding] = useState<EmbeddingSettings>(EMBEDDING_DEFAULTS);
  const [storageStats, setStorageStats] = useState<StorageStats | null>(null);
  const [storageMsg, setStorageMsg] = useState<string | null>(null);

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
        const acr = data.audio_cut_refine ?? {};
        setCutRefineOn(acr.enabled !== false);
        setPreRollMs(String(acr.pre_roll_ms ?? 120));
        setPostRollMs(String(acr.post_roll_ms ?? 150));
        setSnapWinMs(String(acr.snap_window_ms ?? 80));
        setCutFadeMs(String(acr.fade_ms ?? 20));
        setPlanner({ ...PLANNER_DEFAULTS, ...(data.planner ?? {}) });
        setTranscription({
          ...TRANSCRIPTION_DEFAULTS,
          ...(data.transcription ?? {}),
        });
        setEmbedding({
          ...EMBEDDING_DEFAULTS,
          ...(data.embedding ?? {}),
        });
        void fetchStorageStats()
          .then((st) => {
            if (!cancelled) setStorageStats(st);
          })
          .catch(() => {
            if (!cancelled) setStorageStats(null);
          });
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
          <div className="modal-sheet__header-actions">
            {onOpenKeyboardShortcuts ? (
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => {
                  onOpenKeyboardShortcuts();
                  onClose();
                }}
              >
                Keyboard shortcuts…
              </button>
            ) : null}
            <button type="button" className="btn btn--ghost" onClick={onClose}>
              Close
            </button>
          </div>
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
              <h3>Narration cut refine</h3>
              <p className="settings-hint">
                Applied when the planner saves a plan and on Replace timeline / Refine
                cuts. Turn off to keep planner trims verbatim.
              </p>
              <label className="settings-inline">
                <input
                  type="checkbox"
                  checked={cutRefineOn}
                  onChange={(e) => setCutRefineOn(e.target.checked)}
                />
                Enable automatic refine
              </label>
              <label className="settings-label">
                Pre-roll (ms)
                <input
                  type="text"
                  inputMode="numeric"
                  value={preRollMs}
                  onChange={(e) => setPreRollMs(e.target.value)}
                />
              </label>
              <label className="settings-label">
                Post-roll (ms)
                <input
                  type="text"
                  inputMode="numeric"
                  value={postRollMs}
                  onChange={(e) => setPostRollMs(e.target.value)}
                />
              </label>
              <label className="settings-label">
                Snap window (ms)
                <input
                  type="text"
                  inputMode="numeric"
                  value={snapWinMs}
                  onChange={(e) => setSnapWinMs(e.target.value)}
                />
              </label>
              <label className="settings-label">
                Fade (ms)
                <input
                  type="text"
                  inputMode="numeric"
                  value={cutFadeMs}
                  onChange={(e) => setCutFadeMs(e.target.value)}
                />
              </label>
              <button
                type="button"
                className="btn btn--primary"
                disabled={loading}
                onClick={() => {
                  const num = (s: string, fb: number) => {
                    const n = Number(s);
                    return Number.isFinite(n) ? n : fb;
                  };
                  void putSettings({
                    audio_cut_refine: {
                      enabled: cutRefineOn,
                      pre_roll_ms: num(preRollMs, 120),
                      post_roll_ms: num(postRollMs, 150),
                      snap_window_ms: num(snapWinMs, 80),
                      fade_ms: num(cutFadeMs, 20),
                    },
                  })
                    .then(setS)
                    .catch((e: unknown) =>
                      setUiBannerError(e instanceof Error ? e.message : "Save failed"),
                    );
                }}
              >
                Save cut refine settings
              </button>
            </section>

            <section className="settings-block">
              <h3>Planner limits</h3>
              <p className="settings-hint">
                Draft mode stays inside these limits. A run asks before it goes
                over the confirm amount. The cheap model is for captions. The
                edit model writes the timeline.
              </p>
              <label className="settings-label">
                Catalog token budget
                <input
                  type="text"
                  inputMode="numeric"
                  value={String(planner.catalog_token_budget)}
                  onChange={(e) =>
                    setPlanner({
                      ...planner,
                      catalog_token_budget: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label className="settings-label">
                Confirm above ($)
                <input
                  type="text"
                  inputMode="decimal"
                  value={String(planner.confirm_above_usd)}
                  onChange={(e) =>
                    setPlanner({
                      ...planner,
                      confirm_above_usd: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label className="settings-label">
                Max input tokens
                <input
                  type="text"
                  inputMode="numeric"
                  value={String(planner.max_input_tokens)}
                  onChange={(e) =>
                    setPlanner({
                      ...planner,
                      max_input_tokens: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label className="settings-label">
                Max cost ($)
                <input
                  type="text"
                  inputMode="decimal"
                  value={String(planner.max_cost_usd)}
                  onChange={(e) =>
                    setPlanner({ ...planner, max_cost_usd: Number(e.target.value) })
                  }
                />
              </label>
              <label className="settings-label">
                Max model calls
                <input
                  type="text"
                  inputMode="numeric"
                  value={String(planner.max_iterations)}
                  onChange={(e) =>
                    setPlanner({
                      ...planner,
                      max_iterations: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label className="settings-label">
                Max images
                <input
                  type="text"
                  inputMode="numeric"
                  value={String(planner.max_images)}
                  onChange={(e) =>
                    setPlanner({ ...planner, max_images: Number(e.target.value) })
                  }
                />
              </label>
              <label className="settings-label">
                Max time (seconds)
                <input
                  type="text"
                  inputMode="numeric"
                  value={String(planner.max_wall_time_s)}
                  onChange={(e) =>
                    setPlanner({
                      ...planner,
                      max_wall_time_s: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label className="settings-label">
                Cheap model (captions)
                <input
                  type="text"
                  value={planner.triage_model}
                  onChange={(e) =>
                    setPlanner({ ...planner, triage_model: e.target.value })
                  }
                />
              </label>
              <label className="settings-label">
                Edit model
                <input
                  type="text"
                  value={planner.edit_model}
                  onChange={(e) =>
                    setPlanner({ ...planner, edit_model: e.target.value })
                  }
                />
              </label>
              <button
                type="button"
                className="btn btn--primary"
                disabled={loading}
                onClick={() => {
                  void putSettings({ planner })
                    .then((data) => {
                      setS(data);
                      setPlanner({ ...PLANNER_DEFAULTS, ...(data.planner ?? {}) });
                    })
                    .catch((e: unknown) =>
                      setUiBannerError(
                        e instanceof Error ? e.message : "Save failed",
                      ),
                    );
                }}
              >
                Save planner limits
              </button>
            </section>

            <section className="settings-block">
              <h3>Transcription</h3>
              <p className="settings-hint">
                faster-whisper runs locally. Word timestamps are always saved.
                Re-transcribe a file from Source preview after changing these.
              </p>
              <label className="settings-label">
                Model size
                <select
                  value={transcription.model_size}
                  onChange={(e) =>
                    setTranscription({
                      ...transcription,
                      model_size: e.target.value as "small" | "medium",
                    })
                  }
                >
                  <option value="small">small (faster)</option>
                  <option value="medium">medium (more accurate)</option>
                </select>
              </label>
              <label className="settings-inline">
                <input
                  type="checkbox"
                  checked={transcription.keep_quiet_speech}
                  onChange={(e) =>
                    setTranscription({
                      ...transcription,
                      keep_quiet_speech: e.target.checked,
                    })
                  }
                />
                Keep quiet speech (looser VAD)
              </label>
              <button
                type="button"
                className="btn btn--primary"
                disabled={loading}
                onClick={() => {
                  void putSettings({ transcription })
                    .then((data) => {
                      setS(data);
                      setTranscription({
                        ...TRANSCRIPTION_DEFAULTS,
                        ...(data.transcription ?? {}),
                      });
                    })
                    .catch((e: unknown) =>
                      setUiBannerError(
                        e instanceof Error ? e.message : "Save failed",
                      ),
                    );
                }}
              >
                Save transcription settings
              </button>
            </section>

            <section className="settings-block">
              <h3>Catalog embedding</h3>
              <p className="settings-hint">
                Used to rank files when the planner catalog is over token budget.
                Hashed bag-of-words is fast but literal. Sentence-transformer
                downloads a small local model (all-MiniLM-L6-v2) and falls back
                to hash if it fails.
              </p>
              <label className="settings-label">
                Method
                <select
                  value={embedding.method}
                  onChange={(e) =>
                    setEmbedding({
                      ...embedding,
                      method: e.target.value as EmbeddingSettings["method"],
                    })
                  }
                >
                  <option value="hash">Hashed bag-of-words (default)</option>
                  <option value="sentence_transformer">
                    Sentence-transformer (local)
                  </option>
                </select>
              </label>
              <label className="settings-label">
                Model name
                <input
                  value={embedding.model_name}
                  disabled={embedding.method === "hash"}
                  onChange={(e) =>
                    setEmbedding({ ...embedding, model_name: e.target.value })
                  }
                />
              </label>
              <button
                type="button"
                className="btn btn--primary"
                disabled={loading}
                onClick={() => {
                  void putSettings({ embedding })
                    .then((data) => {
                      setS(data);
                      setEmbedding({
                        ...EMBEDDING_DEFAULTS,
                        ...(data.embedding ?? {}),
                      });
                    })
                    .catch((e: unknown) =>
                      setUiBannerError(
                        e instanceof Error ? e.message : "Save failed",
                      ),
                    );
                }}
              >
                Save embedding settings
              </button>
            </section>

            <section className="settings-block">
              <h3>Storage</h3>
              <p className="settings-hint">
                Regenerable caches: perception JPEGs, keyframe images, and
                embedding JSON. AI frame captions are separate (paid API).
              </p>
              {storageStats ? (
                <ul className="settings-kv">
                  <li>
                    Perception images:{" "}
                    {formatBytes(storageStats.perception_images_bytes)}
                  </li>
                  <li>
                    Keyframe images:{" "}
                    {formatBytes(storageStats.keyframes_images_bytes)}
                  </li>
                  <li>
                    Embedding JSON:{" "}
                    {formatBytes(storageStats.embedding_json_bytes)}
                  </li>
                  <li>
                    Paid AI captions:{" "}
                    {formatBytes(storageStats.paid_caption_json_bytes ?? 0)}
                  </li>
                  <li>
                    <strong>
                      Total regenerable:{" "}
                      {formatBytes(storageStats.total_regenerable_bytes)}
                    </strong>
                  </li>
                </ul>
              ) : (
                <p className="modal-sheet__muted">Storage stats unavailable.</p>
              )}
              {storageMsg && <p className="settings-ok">{storageMsg}</p>}
              <div className="settings-actions">
                <button
                  type="button"
                  className="btn btn--ghost"
                  disabled={loading}
                  onClick={() => {
                    if (
                      !window.confirm(
                        "Clear regenerable caches? Analysis will rebuild on next run.",
                      )
                    ) {
                      return;
                    }
                    setLoading(true);
                    void clearRegenerableCaches()
                      .then((res) => {
                        setStorageStats(res.stats);
                        setStorageMsg(
                          `Freed ${formatBytes(res.freed_bytes)} (${res.removed_files} files).`,
                        );
                      })
                      .catch((e: unknown) =>
                        setUiBannerError(
                          e instanceof Error ? e.message : "Clear failed",
                        ),
                      )
                      .finally(() => setLoading(false));
                  }}
                >
                  Clear regenerable caches
                </button>
                <button
                  type="button"
                  className="btn btn--ghost"
                  disabled={loading}
                  onClick={() => {
                    if (
                      !window.confirm(
                        "Clear paid AI frame captions? Rebuilding them will call the paid caption API for each video.",
                      )
                    ) {
                      return;
                    }
                    setLoading(true);
                    void clearPaidCaptionCaches()
                      .then((res) => {
                        setStorageStats(res.stats);
                        setStorageMsg(
                          `Cleared paid captions: ${formatBytes(res.freed_bytes)} (${res.removed_files} files).`,
                        );
                      })
                      .catch((e: unknown) =>
                        setUiBannerError(
                          e instanceof Error ? e.message : "Clear failed",
                        ),
                      )
                      .finally(() => setLoading(false));
                  }}
                >
                  Clear paid AI descriptions…
                </button>
              </div>
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
