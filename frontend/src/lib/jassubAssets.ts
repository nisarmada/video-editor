/**
 * Local URLs for JASSUB worker + WASM (bundled by Vite from node_modules, no CDN).
 */
import defaultWoff2 from "jassub/dist/default.woff2?url";
import workerUrl from "jassub/dist/jassub-worker.js?url";
import wasmUrl from "jassub/dist/jassub-worker.wasm?url";
import legacyWasmUrl from "jassub/dist/jassub-worker.wasm.js?url";
import modernWasmUrl from "jassub/dist/jassub-worker-modern.wasm?url";

export const JASSUB_WORKER_URL = workerUrl;
export const JASSUB_WASM_URL = wasmUrl;
export const JASSUB_LEGACY_WASM_URL = legacyWasmUrl;
export const JASSUB_MODERN_WASM_URL = modernWasmUrl;
export const JASSUB_DEFAULT_WOFF2_URL = defaultWoff2;
