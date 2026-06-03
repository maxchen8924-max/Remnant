# Remnant v0.1

本地优先的数字遗产记忆运行时。

[English](README.md) | [简体中文](README.zh-CN.md)

Remnant 是一套 evidence-first 的开源架构，用于保存、查询并安全地互动逝者留下的数字记忆。
它不是“AI 复活”产品。当前版本是面向开发者的架构和运行时预览，适合研究或扩展存储模型、
来源追踪、关系空间隔离、检索 trace、安全策略和本地 sidecar 运行方式。

不要把真实聊天记录、日记、本地数据库、token，或任何可识别个人/家庭身份的数据提交到这个公开仓库。
测试和贡献时只使用虚构样例，或已经明确获得授权并完成脱敏的数据。

## 成熟度

**v0.1 是 developer preview，不是生产软件。**

已经有价值的部分：

- SQLite schema：不可变 raw message、derived chunks、relationship scopes、evidence、
  retrieval traces、safety events、consent records、deletion logs。
- 数据导入路径：Universal Chat JSON 和 WeChat TXT 可 parse、normalize、filter、chunk、
  attach spans、hash、persist。
- Scope-aware 的 FTS/vector 检索基础和 retrieval trace logging。
- Python sidecar bridge：localhost binding、ephemeral token auth、import、query、scope、
  safety、evidence、data-destroy routes。
- Tauri/React shell：Rust bridge 和 Python sidecar 生命周期管理。
- 回归测试覆盖 schema、ETL、scope safety、retrieval、token auth、bridge runtime。

暂未完成的部分：

- Local LLM generation 尚未集成。
- Embedding generation 尚未端到端接通。
- Voice synthesis 目前只是 schema，默认禁用。
- 前端是 runtime scaffold，不是完整应用。
- 安全审查已有清单，但尚未完成外部认证。

## 设计原则

- **Local-first**：数据默认在用户本机处理。
- **Evidence-first**：事实回答必须来自已存证据。
- **Provenance-first**：每个 claim 应能追溯到 source chunk/span。
- **Raw data immutable**：原始消息 append-only，并由 trigger 保护。
- **Derived annotation only**：清洗、分块、标签都是派生层。
- **Relationship isolation**：每个关系空间有独立可见性。
- **Consent-aware deletion**：scope 级软/硬删除必须可审计。
- **Anti-dependency**：安全策略应能打断高风险使用模式。

## 仓库结构

```text
remnant/
├── docs/               # 白皮书、API、交接、路线图、英文 quickstart/architecture
├── python/             # Python backend 和 local sidecar
│   ├── remnant_etl/    # parser、cleaner、chunker、span、ETL pipeline
│   ├── remnant_core/   # retrieval、rerank、trace、prompt/safety primitives
│   ├── remnant_policy/ # safety、consent、scope policy modules
│   ├── remnant_store/  # SQLite schema、DAO、visibility/deletion
│   ├── remnant_bridge/ # FastAPI routes 和 framework-light runtime helpers
│   └── tests/          # Python regression tests
└── src/                # Tauri 2 + React frontend
    ├── src/            # React pages、hooks、components
    └── src-tauri/      # Rust sidecar manager 和 IPC bridge
```

## 快速开始

完整英文设置说明见 [docs/quickstart.md](docs/quickstart.md)。

Python HTTP sidecar preview 需要 Python 3.11 或 3.12：

```bash
tools/bootstrap-python.sh
```

该脚本会选择 `python3.12` 或 `python3.11`，创建 `python/.venv`，安装 sidecar 依赖，
并运行 sidecar smoke test。如果你的解释器不在 `PATH`，可以使用：

```bash
REMNANT_PYTHON_BIN=/path/to/python3.12 tools/bootstrap-python.sh
tools/bootstrap-python.sh --python /path/to/python3.12
```

手动设置：

```bash
cd python
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests -q
```

运行 preview demo：

```bash
cd python
.venv/bin/python scripts/run_preview_demo.py
```

demo 会创建临时 SQLite DB，seed sample profile/scope，导入 sample chat export，
执行 scope 内 evidence query，做 scoped soft deletion，并验证 immutable raw messages 仍然完整。

启动 sidecar：

```bash
cd python
REMNANT_AUTH_TOKEN=dev-token REMNANT_ENABLE_DOCS=1 .venv/bin/python -m remnant_bridge
```

`dev-token` 只用于本地 quickstart 演示。不要在真实个人数据、共享机器或生产部署中复用它。

前端：

```bash
cd src
npm install
npm test
npm run build
```

Tauri：

```bash
cd src/src-tauri
cargo check
```

启动桌面 app 时，如果默认 `python3` 不是受支持解释器，请指定：

```bash
cd src
REMNANT_PYTHON_BIN=python3.12 npm run tauri dev
```

## API 认证

Rust bridge 使用 `Authorization: Bearer <token>`。Python sidecar 也接受
`X-Remnant-Token: <token>`，用于兼容白皮书和 API reference。

Tauri sidecar 启动 Python 时会注入 `REMNANT_AUTH_TOKEN`；如果独立运行 Python，可以手动设置该环境变量。

## 贡献方向

- Storage and privacy：schema hardening、encryption、deletion verification。
- Retrieval quality：query classification、embedding generation、rerank tuning。
- Safety policy：anti-dependency metrics、crisis templates、audit evidence。
- Frontend runtime：import/query/timeline workflows、evidence inspection。
- Docs and governance：threat model、security checklist、contribution guide。

## 从这里开始

- [Quickstart](docs/quickstart.md)：设置 Python、运行 demo、验证前端和 Tauri bridge。
- [Architecture overview](docs/architecture.md)：理解本地运行时、存储模型、证据管线、关系空间、安全层和 bridge。
- [API overview](docs/api-overview.md)：查看当前已注册 localhost sidecar routes、token auth、示例和 preview caveats。
- [Open-source roadmap](docs/open-source-roadmap.md)：当前成熟度、release gates、贡献轨道。
- [Contributing guide](CONTRIBUTING.md)：项目边界、检查项、PR 预期和 first issues。
- [Security policy](SECURITY.md)：安全问题报告和 preview security review 范围。

## 参考

- [Quickstart](docs/quickstart.md)
- [Architecture overview](docs/architecture.md)
- [API overview](docs/api-overview.md)
- [Architecture whitepaper](docs/remnant-v0.1-architecture-whitepaper.md)
- [API reference](docs/api_reference.md)
- [v0.1 handover](docs/handover-v0.1.md)
- [Open-source roadmap](docs/open-source-roadmap.md)
- [v0.1.1 preview release checklist](docs/release-v0.1.1-preview.md)
- [Security checklist](docs/security_review_checklist.md)
