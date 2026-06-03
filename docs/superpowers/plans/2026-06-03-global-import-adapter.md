# Global Import Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first global import path by supporting `universal_chat_json` through an adapter registry while preserving existing `wechat_txt` imports.

**Architecture:** Keep existing `RawMessage` and ETL storage unchanged. Add a focused parser for canonical chat JSON and a small registry that maps import `file_type` values to parser classes and metadata.

**Tech Stack:** Python 3.11/3.12, pytest, existing Remnant ETL pipeline, React copy updates for source-neutral import wording.

---

### Task 1: Adapter Registry

**Files:**
- Create: `python/remnant_etl/parsers/registry.py`
- Modify: `python/remnant_etl/pipeline.py`
- Test: `python/tests/test_etl.py`

- [ ] **Step 1: Write failing tests**

Add tests asserting that supported import types include `wechat_txt` and `universal_chat_json`, and that unknown types fail with a clear unsupported type error.

- [ ] **Step 2: Verify red**

Run: `cd python && .venv/bin/python -m pytest tests/test_etl.py::TestETLPipeline::test_unsupported_file_type -q`

Expected: existing unsupported type test still passes, and new registry tests fail because the registry does not exist.

- [ ] **Step 3: Implement registry**

Create a registry that exposes `get_parser(file_type)`, `list_supported_file_types()`, and `list_adapter_metadata()`.

- [ ] **Step 4: Wire pipeline**

Replace the private `_PARSER_REGISTRY` lookup in `ETLPipeline` with registry calls while preserving the existing `wechat_txt` behavior.

- [ ] **Step 5: Verify green**

Run: `cd python && .venv/bin/python -m pytest tests/test_etl.py -q`

Expected: ETL tests pass.

### Task 2: Universal Chat JSON Parser

**Files:**
- Create: `python/remnant_etl/parsers/universal_chat_json.py`
- Create: `python/tests/fixtures/sample_dataset/universal_chat_sample.json`
- Modify: `python/remnant_etl/parsers/registry.py`
- Test: `python/tests/test_etl.py`

- [ ] **Step 1: Write failing parser tests**

Add tests for a valid `universal_chat_json` import, invalid schema version,
missing required fields, and attachment metadata preservation.

- [ ] **Step 2: Verify red**

Run: `cd python && .venv/bin/python -m pytest tests/test_etl.py -q`

Expected: new tests fail because the parser and fixture do not exist.

- [ ] **Step 3: Implement parser**

Parse JSON with `version`, `source`, `conversation`, and `messages`. Convert each message to `RawMessage`, preserving `sender_id`, `message_id`, attachments, replies, reactions, source platform, and conversation metadata inside `RawMessage.metadata`.

- [ ] **Step 4: Verify green**

Run: `cd python && .venv/bin/python -m pytest tests/test_etl.py -q`

Expected: ETL tests pass.

### Task 3: Global Import Positioning

**Files:**
- Modify: `README.md`
- Modify: `docs/open-source-roadmap.md`
- Modify: `src/src/pages/Import.tsx`
- Test: `src/src/App.test.tsx` or existing frontend smoke tests

- [ ] **Step 1: Write or update frontend/docs checks when useful**

Ensure the import surface no longer frames WeChat as the only default source.

- [ ] **Step 2: Update copy**

Describe Remnant as a local-first memory import runtime with source adapters. Present WeChat as an existing regional adapter example.

- [ ] **Step 3: Verify**

Run: `cd src && npm test && npm run build`

Expected: frontend tests and build pass.

### Task 4: Final Verification And Commit

**Files:**
- All files touched by Tasks 1-3

- [ ] **Step 1: Run Python verification**

Run: `cd python && .venv/bin/python -m pytest tests/test_etl.py tests/test_preview_demo.py -q`

Expected: selected Python tests pass.

- [ ] **Step 2: Run frontend verification**

Run: `cd src && npm test && npm run build`

Expected: frontend tests and build pass.

- [ ] **Step 3: Check staged scope**

Run: `git status --short` and stage only global import adapter changes, not local workspace logs or unrelated scope API changes.

- [ ] **Step 4: Commit**

Commit message: `Add universal chat import adapter`
