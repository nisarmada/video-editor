import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { useKeybindingsStore } from "./store/keybindingsStore";
import { useEditorSettingsStore } from "./store/editorSettingsStore";
import App from "./App";
import "./index.css";

void (async () => {
  await useKeybindingsStore.getState().hydrateFromApi();
  await useEditorSettingsStore.getState().hydrateFromApi();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
})();
