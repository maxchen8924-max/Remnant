# Changelog

## v0.1.1 Preview - In Progress

- Reframed README as an open-source architecture/runtime preview.
- Added open-source roadmap, release gates, and non-negotiable safety bounds.
- Added bridge runtime helpers for import, query, and scoped data destruction.
- Added `python -m remnant_bridge` package entrypoint.
- Fixed ephemeral token validation and `REMNANT_AUTH_TOKEN` handling.
- Accepted both `Authorization: Bearer` and `X-Remnant-Token` headers.
- Fixed scoped FTS helper parameter ordering.
- Added preview demo CLI for import, query, soft delete, and raw-data integrity.
- Added sidecar smoke test for the real `python -m remnant_bridge` entrypoint.
- Added Rust sidecar support for `REMNANT_PYTHON_BIN`.
- Declared Python 3.11/3.12 support for the HTTP sidecar preview.
- Added contributing, security, code-of-conduct, license, and issue-template
  files.

## v0.1.0

- Initial architecture preview.
- Added whitepaper, handover, schema, ETL, retrieval, scope, safety, and Tauri
  scaffold.
