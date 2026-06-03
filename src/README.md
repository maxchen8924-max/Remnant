# Remnant Frontend And Desktop Shell

This directory contains the Remnant React frontend and Tauri desktop bridge.

## Layout

```text
src/
├── src/          # React pages, hooks, shared styles, and UI components
├── src-tauri/    # Rust sidecar manager, IPC bridge, and Tauri config
├── package.json  # frontend scripts and dependencies
└── vite.config.ts
```

## Frontend Checks

```bash
npm install
npm test
npm run build
```

Run the local Vite preview:

```bash
npm run dev -- --host 127.0.0.1
```

## Desktop Bridge Checks

```bash
cd src-tauri
cargo check --locked
cargo test --locked
```

When launching the desktop app, set `REMNANT_PYTHON_BIN` if your default
`python3` is not Python 3.11 or 3.12:

```bash
REMNANT_PYTHON_BIN=python3.12 npm run tauri dev
```

## Runtime Notes

- The frontend calls the Tauri/Rust bridge through `src/hooks/useSidecar.ts`.
- The bridge manages a Python sidecar process and sends local token-authenticated
  requests.
- User-facing flows should prefer profile names and relationship-space names;
  internal IDs should remain implementation details.
- This is a runtime scaffold for a developer preview, not a polished production
  desktop app.

For the full project setup, see [../docs/quickstart.md](../docs/quickstart.md).
