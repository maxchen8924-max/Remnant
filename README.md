# Remnant v0.1
# 残响 · Local-First Digital Legacy Memory Runtime

## 项目结构

```
remnant/
├── docs/               # 技术架构白皮书
├── python/              # Python 后端 (FastAPI + SQLite)
│   ├── remnant_etl/     # ETL 管道
│   ├── remnant_core/    # 核心逻辑 (RAG, Claim, Prompt)
│   ├── remnant_policy/  # 策略中间件 (Safety, Consent, Scope)
│   ├── remnant_store/   # 存储层 (DB, Schema, DAO)
│   ├── remnant_bridge/  # FastAPI HTTP 桥接
│   └── tests/           # Python 测试
└── src/                 # Tauri 2.0 + React 前端
    ├── src/             # 前端源码 (Pages, Components, Hooks)
    └── src-tauri/       # Rust 侧 (SidecarManager, IPC Bridge)
```

## 开发环境

- Rust 1.96+ (rustup)
- Node.js 22+
- Python 3.11+
- SQLite 3.x (含 FTS5 支持)

## 快速开始

### Python 后端

```bash
cd python
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

### 前端

```bash
cd src
npm install
npm run dev
```

### Tauri 桌面端

```bash
cd src
npm run tauri dev
```

## 核心设计原则

- **Local-first**: 所有数据默认在用户本机处理
- **Evidence-first**: 没有证据不输出逝者事实
- **Provenance-first**: 每个事实性回答必须绑定原始数据来源
- **Raw Data Immutable**: 原始数据不可被覆盖、篡改或重写
- **Derived Annotation Only**: 清洗、切块、指代消解等都是派生标注
- **Consent-aware**: 预留授权、撤回、销毁和审计能力
- **Relationship Isolation**: 同一逝者面对不同亲属的交互历史必须隔离
- **Anti-dependency**: 使用时长、深夜活跃、情绪依赖等风险熔断

## 技术架构

详见 [技术架构白皮书](docs/remnant-v0.1-architecture-whitepaper.md)