# Video editor UI

React + TypeScript + Vite + Zustand. Layout follows `docs/ui_spec.md`.

## Run with the backend

Use **two terminals** from the **repo root**:

**Terminal 1 — API**

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload --app-dir .
```

**Terminal 2 — UI**

```bash
cd frontend
npm install
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Vite proxies `/api` to `http://127.0.0.1:8000`.

Optional: pre-build proxies with `python scripts/make_proxies.py`.

## Scripts

| Command | Purpose |
|---------|---------|
| `npm run dev` | Dev server with HMR |
| `npm run build` | Production build to `dist/` |
| `npm run preview` | Serve production build |
