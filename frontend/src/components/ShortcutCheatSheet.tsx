import { SHORTCUT_ACTIONS } from "../shortcuts/actions";
import { useKeybindingsStore } from "../store/keybindingsStore";
import { useEditorSettingsStore } from "../store/editorSettingsStore";
import { getBindingLabel } from "../shortcuts/tooltip";

type Props = {
  open: boolean;
  onClose: () => void;
};

export default function ShortcutCheatSheet({ open, onClose }: Props) {
  const overrides = useKeybindingsStore((s) => s.overrides);
  useEditorSettingsStore((s) => s.shortcutTargeting);
  useEditorSettingsStore((s) => s.perActionTargetMode);

  if (!open) return null;

  const byCat = new Map<string, typeof SHORTCUT_ACTIONS>();
  for (const a of SHORTCUT_ACTIONS) {
    const list = byCat.get(a.category) ?? [];
    list.push(a);
    byCat.set(a.category, list);
  }

  return (
    <div
      className="shortcut-overlay"
      role="dialog"
      aria-modal
      aria-label="Keyboard shortcuts"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="shortcut-overlay__panel">
        <div className="shortcut-overlay__head">
          <h2 className="shortcut-overlay__title">Shortcuts</h2>
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="shortcut-overlay__body">
          {[...byCat.entries()].map(([cat, actions]) => (
            <section key={cat} className="shortcut-overlay__section">
              <h3 className="shortcut-overlay__cat">{cat}</h3>
              <ul className="shortcut-overlay__list">
                {actions.map((a) => (
                  <li key={a.id} className="shortcut-overlay__row">
                    <span>{a.label}</span>
                    <span className="shortcut-overlay__keys">
                      {getBindingLabel(a.id, overrides)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
