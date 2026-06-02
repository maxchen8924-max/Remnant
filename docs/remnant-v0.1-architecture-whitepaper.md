# Remnant v0.1 — Technical Architecture Whitepaper

> **版本**: v0.1-draft  
> **状态**: 架构设计阶段  
> **核心原则**: Local-first · Evidence-first · Provenance-first · Raw Data Immutable · Derived Annotation Only · Consent-aware · Relationship Isolation · Anti-dependency · Voice Clone Disabled by Default

---

# Chapter 1: System Architecture

## 1.1 模块划分与职责

Remnant v0.1 由以下 7 个一级模块构成：

| 模块 | 语言 | 进程 | 职责 |
|------|------|------|------|
| `remnant-etl` | Python | sidecar | 原始数据导入、清洗、切块、标注；纯函数式管道，无状态 |
| `remnant-core` | Python | sidecar | 记忆检索、RAG 管线、Claim 生成与证据验证、关系隔离查询 |
| `remnant-policy` | Python | sidecar | 授权策略、同意管理、安全熔断、审计日志写入策略 |
| `remnant-store` | Python + Rust | sidecar + native | SQLite/SQLCipher 存储层、FTS5 全文索引、向量索引管理、数据销毁 |
| `remnant-bridge` | Rust | Tauri main | IPC 网关：Tauri ↔ Python sidecar 的路由、认证、SSE 流转发 |
| `remnant-ui` | TypeScript + React | WebView | 桌面界面：数据导入向导、对话、审计、设置 |
| `remnant-plugin-api` | TypeScript | WebView | 插件协议定义：外部扩展的消息格式与钩子接口 |

### 模块职责详解

**remnant-etl**
- 接收导入请求，解析不同来源的原始数据格式（微信 txt、微信 DB、邮件 mbox/eml、日记 txt/md、音频转写 JSON、OCR 输出）
- 执行 normalize → filter_noise → segment → chunk → annotate → attach_spans → hash 流水线
- 所有输出均为 derived artifact，raw artifact 只做 append，不做覆盖
- 必须可替换：支持第三方 ETL 实现（如用户自定义清洗逻辑）

**remnant-core**
- 提供 `query(scope_id, question, top_k) → List[ClaimWithEvidence]` 接口
- 执行 embedding → FTS → vector search → rerank → evidence validation → claim generation 流水线
- 所有查询必须指定 `relationship_scope_id`，返回结果严格隔离
- 管理最小记忆集（Minimal Memory Set）的构建与缓存

**remnant-policy**
- 实现 Consent Engine：检查 `data_subject_consent` 表，决定数据是否可被某个 scope 访问
- 实现 Anti-dependency Monitor：追踪使用时长、深夜活跃、情绪依赖频率，触发熔断
- 审计日志的写入策略：所有数据访问、查询、销毁操作必须留痕
- 声音克隆默认禁用策略的执行点

**remnant-store**
- SQLite/SQLCipher 的 schema 管理、迁移、事务
- FTS5 虚拟表的创建与同步
- sqlite-vec 向量索引的构建与查询
- 可选 LanceDB 的适配层
- 数据销毁的实际执行层（按 scope 或按 deceased 级别）

**remnant-bridge**
- Tauri Rust 侧的 HTTP server（localhost:端口），作为 Python sidecar 的反向代理
- SSE 流转发：Python 端的流式输出经 bridge 转为 Tauri Event
- 认证：sidecar 启动时生成 ephemeral token，bridge 校验每个请求
- 健康检查：监控 sidecar 进程存活、自动重启

**remnant-ui**
- React 组件库，通过 Tauri invoke/Event 与 bridge 通信
- 页面：Dashboard、ImportWizard、Conversation、AuditLog、Settings、ConsentManager
- 不直接访问 Python sidecar，所有通信经过 bridge

**remnant-plugin-api**
- 定义插件可扩展的钩子：`on_import_start`、`on_chunk_created`、`on_retrieval_done`、`on_response_generated`
- 定义消息格式：PluginMessage 的 JSON Schema
- 插件以 WebView 内 iframe 或独立 WebWorker 运行，无文件系统访问

## 1.2 模块间数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│                        remnant-ui (WebView)                          │
│   Dashboard / ImportWizard / Conversation / AuditLog / Settings     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ Tauri invoke / Event
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     remnant-bridge (Rust, Tauri Main)               │
│   IPC Gateway · Auth · SSE Forward · Health Check · Sidecar Mgmt    │
└──────────┬───────────────────────────────────┬──────────────────────┘
           │ HTTP/SSE (localhost:18731)        │ Tauri invoke (native)
           ▼                                   ▼
┌──────────────────────────┐    ┌─────────────────────────────────────┐
│   Python Sidecar         │    │   remnant-store (Rust native impl)    │
│   ┌────────────────────┐ │    │   SQLite/SQLCipher 管理器            │
│   │   remnant-etl      │ │    │   FTS5 / sqlite-vec / LanceDB       │
│   │   ↓                │ │    │   Schema Migration                   │
│   │   remnant-core     │ │    └─────────────────┬───────────────────┘
│   │   ↓                │ │                      │ SQL over local file
│   │   remnant-policy   │ │◄─────────────────────┘
│   └────────────────────┘ │
└──────────────────────────┘
           │
           │ HTTP API (internal)
           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  remnant-plugin-api (Extension Points)               │
│   on_import_start · on_chunk_created · on_retrieval_done · ...      │
└─────────────────────────────────────────────────────────────────────┘
```

**数据流关键路径：**

1. **导入流**: UI → bridge → etl.import(source_config) → store.persist_raw() → store.persist_normalized() → store.persist_chunks() → store.persist_annotations()
2. **查询流**: UI → bridge → core.query(scope_id, question) → store.vector_search() + store.fts_search() → core.rerank() → core.validate_evidence() → core.generate_claims() → policy.audit_log()
3. **授权流**: UI → bridge → policy.check_consent(scope_id, data_id) → store.enforce_scope()

## 1.3 本地进程模型

```
┌─────────────────────────────────────────────────────┐
│                   Tauri Process (PID 1)              │
│  ┌───────────────────────────────────────────────┐  │
│  │  Main Thread (Rust)                           │  │
│  │  - remnant-bridge: HTTP server on 127.0.0.1   │  │
│  │  - remnant-store: SQLite via rusqlite          │  │
│  │  - Sidecar process manager                     │  │
│  │  - Window manager                              │  │
│  └───────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │  WebView (OSWebview / WebView2)               │  │
│  │  - remnant-ui: React SPA                      │  │
│  │  - remnant-plugin-api: Extension sandbox       │  │
│  └───────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │  Python Sidecar (PID 2, managed by Tauri)     │  │
│  │  - FastAPI + Uvicorn on 127.0.0.1:18731       │  │
│  │  - remnant-etl                                │  │
│  │  - remnant-core                               │  │
│  │  - remnant-policy                              │  │
│  │  - llama.cpp server (optional, PID 3)         │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

**进程通信矩阵：**

| 源 | 目标 | 协议 | 端口 | 备注 |
|---|---|---|---|---|
| UI (WebView) | Bridge (Rust) | Tauri invoke | N/A | 同进程，ipc_render |
| Bridge | Python Sidecar | HTTP/SSE | 18731 | localhost only |
| Python Sidecar | Store (SQLite) | rusqlite / sqlalchemy | N/A | 本地文件读写 |
| Bridge | Store (SQLite) | rusqlite | N/A | 原生查询 |
| Python Sidecar | llama.cpp | HTTP | 18732 | 可选，LLM 推理 |

**进程生命周期：**

- Tauri main process 启动时 spawn Python sidecar，通过 `remnant-bridge` 的 `SidecarManager` 管理
- Sidecar 启动后执行 health check（`GET /health`），失败则重试最多 15 次，间隔 2s（覆盖冷启动场景）
- 用户关闭应用时，bridge 先向 sidecar 发送 `POST /shutdown`，等待 5s，超时则 SIGTERM
- llama.cpp 进程由 sidecar 启停，bridge 不直接管理

## 1.4 Tauri 与 Python 后端的通信方式

**通信协议：localhost HTTP + SSE**

```
UI (React)
  │
  │ Tauri invoke("bridge_request", { path, method, body })
  ▼
Bridge (Rust)
  │
  │ HTTP/1.1 → 127.0.0.1:18731/api/v1/{path}
  ▼
Python Sidecar (FastAPI)
```

**请求格式：**

```typescript
// Tauri invoke from UI
const result = await invoke("bridge_request", {
  path: "/api/v1/import/start",
  method: "POST",
  body: JSON.stringify({ source_type: "wechat_txt", file_path: "/path/to/export.txt" }),
  headers: { "X-Remnant-Token": ephemeralToken },
});

// SSE streaming
const eventSource = await invoke("bridge_sse", {
  path: "/api/v1/conversation/stream",
  method: "POST",
  body: JSON.stringify({ scope_id: "s_001", question: "..." }),
});
```

**Bridge 的 Rust 侧实现要点：**
- `bridge_request`: 同步 HTTP 请求，返回 JSON
- `bridge_sse`: 建立 SSE 连接，通过 Tauri Event 将 chunk 转发给 WebView
- ephemeral token 在 sidecar 启动时由 bridge 生成，注入环境变量 `REMNANT_SIDE_TOKEN`
- 所有请求必须带 `X-Remnant-Token` header，bridge 和 sidecar 双重校验

**Trade-off 说明：**
- 选择 HTTP/SSE 而非 gRPC 或 Unix socket：因为 Tauri 2.0 的 sidecar API 原生支持 HTTP，且 SSE 提供了流式能力；gRPC 需额外 protobuf 编译和 tonic 依赖，复杂度高
- localhost 绑定 vs Unix socket：localhost 更易调试，且 macOS/Linux/Windows 统一行为；Unix socket 略快但跨平台处理复杂
- ephemeral token vs mTLS：token 机制简单够用，mTLS 在本地单用户场景过重

## 1.5 可替换模块

| 模块 | 可替换性 | 替换方式 | 理由 |
|------|---------|---------|------|
| `remnant-etl` | **高** | 通过 Python entry_point 注册新 ETL pipeline；或实现 `BaseETLPipeline` 抽象类 | 不同用户可能有不同数据源和清洗逻辑 |
| `remnant-core` 的 LLM 后端 | **高** | 配置切换 llama.cpp / vLLM / OpenAI-compatible API；通过 `LLMProvider` 接口 | 本地/云端 LLM 灵活切换 |
| `remnant-core` 的 Embedding 模型 | **高** | 配置切换 bge-small-zh / bge-m3 / nomic-embed-text | 不同语言/精度需求 |
| `remnant-store` 的向量后端 | **中** | sqlite-vec ↔ LanceDB 通过 `VectorStoreAdapter` 接口 | LanceDB 支持更大规模，sqlite-vec 更轻量 |
| `remnant-ui` | **低** | Tauri WebView 容器内替换前端框架 | 需要适配 Tauri API，替换成本高 |

**接口抽象：**

```python
# remnant-etl 的可替换接口
class BaseETLPipeline(ABC):
    @abstractmethod
    def normalize(self, raw_messages: List[RawMessage]) -> List[NormalizedMessage]: ...
    
    @abstractmethod
    def filter_noise(self, messages: List[NormalizedMessage]) -> List[NormalizedMessage]: ...
    
    @abstractmethod
    def chunk(self, messages: List[NormalizedMessage]) -> List[MemoryChunk]: ...

# LLM 后端可替换接口
class LLMProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str, **kwargs) -> str: ...
    
    @abstractmethod
    def stream(self, prompt: str, **kwargs) -> Iterator[str]: ...

# 向量后端可替换接口
class VectorStoreAdapter(ABC):
    @abstractmethod
    def upsert(self, chunk_id: str, embedding: List[float]) -> None: ...
    
    @abstractmethod
    def search(self, query_embedding: List[float], top_k: int, scope_id: str) -> List[SearchResult]: ...
```

## 1.6 安全边界模块

安全边界（Trust Boundary）定义了哪些模块跨越了信任域：

```
┌──────────────────────────────────────────────────────────┐
│           Trust Boundary 1: UI ↔ Bridge                  │
│                                                          │
│  remnant-ui ──── Tauri invoke ────── remnant-bridge      │
│                                                          │
│  风险：XSS 注入 WebView、恶意插件访问                     │
│  防御：CSP 策略、插件沙箱 iframe、最小 API 权限白名单     │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│           Trust Boundary 2: Bridge ↔ Sidecar              │
│                                                          │
│  remnant-bridge ──── HTTP/SSE ────── Python Sidecar      │
│                                                          │
│  风险：localhost 仿冒、token 泄露、进程注入               │
│  防御：ephemeral token、进程签名校验、只绑 127.0.0.1      │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│           Trust Boundary 3: Sidecar ↔ Storage             │
│                                                          │
│  Python Sidecar ──── SQLite file ────── remnant-store     │
│                                                          │
│  风险：SQL 注入、文件篡改、未加密数据泄露                   │
│  防御：参数化查询、SQLCipher 全盘加密、文件权限 600        │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│           Trust Boundary 4: Policy Enforcement            │
│                                                          │
│  remnant-policy 贯穿所有层                                │
│                                                          │
│  风险：绕过 consent 检查、越权访问、数据泄露               │
│  防御：policy 层强制拦截所有读写、scope 隔离行级过滤       │
└──────────────────────────────────────────────────────────┘
```

**属于安全边界的模块：**

1. **remnant-bridge** — 唯一的外部通信入口，必须认证所有请求
2. **remnant-policy** — 所有数据访问必须经过 consent 检查，不可绕过
3. **remnant-store** — 数据持久化的唯一路径，SQLCipher 加密是安全底线
4. **remnant-ui 的插件沙箱** — 插件代码不可直接访问 Tauri API 或本地文件

**不属于安全边界但与安全相关：**
- `remnant-etl` — 处理的数据本身已由 store 加密存储，etl 只做内存中转换
- `remnant-core` — 查询结果由 policy 层过滤，core 本身不做权限判断

---

# Chapter 2: Data Lifecycle

## 2.1 数据生命周期全貌

一条数据从导入到被引用的完整生命周期分为 4 个阶段、13 个环节：

```
┌─────────────────────── Stage 1: Ingest ──────────────────────┐
│                                                               │
│  Import ──► Raw Preservation ──► Normalization                │
│                                                               │
└───────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────── Stage 2: Process ─────────────────────┐
│                                                               │
│  Cleaning ──► Chunking ──► Annotation ──► Embedding           │
│                                                               │
└───────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────── Stage 3: Retrieve ─────────────────────┐
│                                                               │
│  Indexing ──► Retrieval ──► Rerank ──► Evidence Validation    │
│                                                               │
└───────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────── Stage 4: Generate ─────────────────────┐
│                                                               │
│  Claim Generation ──► Response Rendering ──► Audit Logging    │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

## 2.2 各环节详解

### 2.2.1 Import（导入）

**输入**：用户通过 UI 选择数据源类型和文件路径。

**处理**：
- Bridge 验证用户选择，生成 `source_artifact` 记录（含文件 SHA-256、大小、MIME 类型）
- 文件被复制到 Remnant 数据目录（`~/.remnant/data/raw/`），保持原始格式
- 原始文件**绝对不修改**，后续所有操作均基于副本的读取

**输出**：`source_artifact` 记录，状态为 `PENDING`

**关键约束**：
- 同一文件重复导入时，通过 SHA-256 去重，不会创建新记录
- 导入操作本身被审计日志记录

### 2.2.2 Raw Preservation（原始保存）

**处理**：
- 将源文件解析为结构化的 `raw_message` 列表
- 每条 `raw_message` 保留原始文本、原始时间戳（如有）、原始说话人标识
- 对于无法解析的内容，记录为 `raw_message` 且 `parse_status = FAILED`

**关键约束**：
- **raw artifact 永远不可变**：`raw_message` 表记录一旦写入，任何字段不可 UPDATE 或 DELETE（通过 DB trigger 强制）
- 只有 `source_artifact.status` 可以从 `PENDING` 变为 `PARSED` 或 `FAILED`
- 此环节是 Local-first 的核心保障：原始数据永远存在本机，永远不被覆盖

**Trade-off**：不使用 append-only log（如 Event Sourcing），而是使用不可变行。原因：SQLite 单机场景下，immutable row 比 event log 更易查询和审计，且不需要 replay 能力。

### 2.2.3 Normalization（规范化）

**处理**：
- 时间格式统一为 ISO 8601 UTC
- 说话人标识统一映射到 `deceased_profile_id` 或 `relationship_scope_id`（后者代表当前用户或其关联人）
- 编码异常修正（GBK → UTF-8、乱码修复）
- 内容类型标记（text / image_placeholder / voice_placeholder / system_event）

**输出**：`normalized_message` 记录，每条通过 `raw_message_id` 关联到原始记录

**关键约束**：
- normalized 数据是 **derived artifact**
- 可以重新生成（丢弃所有 normalized_message，从 raw_message 重新跑 normalize）
- 必须保留从 normalized_message 回溯到 raw_message 再到 source_artifact 的完整链路

### 2.2.4 Cleaning（清洗）

**处理**：
- 过滤系统消息（"XXX 邀请 XXX 加入了群聊"）
- 过滤撤回消息
- 过滤转账红包消息（保留金额元数据，标记为 `FINANCIAL_EVENT`）
- 替换表情占位符（[微笑] → emoji，[图片] → IMAGE_PLACEHOLDER）
- 标记重复消息（同一说话人、相近时间、相似内容）
- 标记极短碎片（<3 字符且非纯标点）
- 标记无时间戳消息（尝试通过上下文推断，无法推断则标记 `UNCERTAIN_TIMESTAMP`）
- 说话人别名统一（"妈"、"妈妈"、"老妈" → 同一 person_id）
- 多语言混杂标记

**输出**：清洗后的 `normalized_message`，状态从 `NORMALIZED` 变为 `CLEANED`；被过滤的记录标记为 `FILTERED` 但**不删除**

**关键约束**：
- 清洗结果也是 **derived artifact**，被过滤的记录只是标记，不可物理删除
- 任何清洗规则都是可配置的，用户可以选择保留"系统消息"等

### 2.2.5 Chunking（切块）

**处理**：详见 Chapter 3 的动态分块算法

**输出**：`memory_chunk` 记录，每条包含：
- `chunk_hash`：内容 SHA-256，用于去重和完整性校验
- `chunk_type`：conversation_segment / diary_entry / letter / mixed
- `token_count`：chunk 的 token 数量估计
- `time_range_start` / `time_range_end`：chunk 覆盖的时间范围

**关键约束**：
- 每个 chunk 必须通过 `memory_chunk_span` 关联到源 `normalized_message` 的具体位置（起止消息 ID、起止字符偏移量）
- chunk 必须能追溯回 source span：`chunk → chunk_span → normalized_message → raw_message → source_artifact`
- chunk 是 **derived artifact**，可以重新生成

### 2.2.6 Annotation（标注）

**处理**：
- 情感标注（LLM 判断 chunk 整体情感倾向：neutral / positive / negative / grief_trigger）
- 主题标注（LLM 提取 chunk 涉及的主题标签）
- 指代消解（"他"/"她"/"那个" → 具体人物映射）
- 关键事件标注（生日、节日、重要决定等）
- 风险标注（是否涉及遗嘱、遗产、法律声明、极端情感等敏感内容）

**输出**：`memory_annotation` 记录，类型为 `SENTIMENT` / `TOPIC` / `COREFERENCE` / `KEY_EVENT` / `RISK`

**关键约束**：
- 标注是 **derived artifact**，可能出错，用户可修正
- 标注始终标注在 chunk 上，不直接标注 raw_message
- LLM 标注必须附带 `confidence` 字段，低于阈值的标注标记为 `LOW_CONFIDENCE`

### 2.2.7 Embedding（向量化）

**处理**：
- 对 `memory_chunk.content` 生成 embedding 向量
- 使用离线模型（bge-small-zh / bge-m3 / nomic-embed-text）
- 向量维度取决于模型选择（bge-small-zh: 512 维, bge-m3: 1024 维, nomic-embed-text: 768 维）

**输出**：`embedding_index_ref` 记录，记录 chunk_id → embedding 模型 → 向量维度 → 索引位置

**关键约束**：
- embedding 是 **derived artifact**，切换模型时需全量重建
- 向量存储在 sqlite-vec 或 LanceDB 中，`embedding_index_ref` 只存引用信息
- 必须记录使用的模型和版本，确保可重现

### 2.2.8 Indexing（索引构建）

**处理**：
- FTS5 全文索引：对 `memory_chunk.content` 构建全文搜索索引
- 向量索引：对 embedding 构建近似最近邻索引（sqlite-vec 或 LanceDB）
- 索引增量更新：新增 chunk 时增量插入，全量重建时 replace

**关键约束**：
- 索引是 **可重建的派生结构**，删除索引不影响原始数据
- FTS5 中文分词：v0.1 使用 `simple` tokenizer + `jieba` Python 分词前端预处理好入库；`unicode61` 仅做 fallback。**Trade-off**：jieba 预处理增加 ETL 复杂度，但中文聊天记录是核心场景，`unicode61` 逐字符切分的检索召回率不可接受。后续可换用 SQLite 自定义 jieba tokenizer（需 C 扩展编译）
- 向量索引的构建可以异步进行，不阻塞导入流程

### 2.2.9 Retrieval（检索）

**处理**：
- 输入：用户问题 + `relationship_scope_id`
- 并行执行 FTS5 搜索和向量搜索
- FTS5 搜索：问题分词后全文匹配
- 向量搜索：问题 embedding 后近似最近邻搜索
- 合并结果集，去重

**关键约束**：
- **所有检索必须限定 `relationship_scope_id`**：向量搜索和 FTS 搜索的 WHERE 子句都包含 scope 过滤
- 检索结果必须附加来源信息：chunk_id → chunk_span → normalized_message → source_artifact
- 检索过程被记录，作为 `retrieval_trace` 的一部分

### 2.2.10 Rerank（重排序）

**处理**：
- 对检索结果使用 cross-encoder 或 LLM 进行重排序
- 考虑因素：语义相关性、时间近因性、主题一致性、多样性
- 重排序后取 top_k（默认 k=10）

**关键约束**：
- 重排序过程保留原始排序，重排序结果作为新排序存储在 `retrieval_trace` 中
- 重排序不得改变检索结果的 scope 归属

### 2.2.11 Evidence Validation（证据验证）

**处理**：
- 对 rerank 后的每个 chunk 执行证据验证：
  1. 检查 chunk 是否属于当前 scope
  2. 检查 chunk 对应的 source_artifact 是否已被 consent 授权
  3. 检查 chunk 的 annotation 是否标记为 `RISK`（敏感内容需要额外确认）
  4. 检查 chunk 的 confidence 阈值
- 未通过验证的 chunk 从结果中移除

**关键约束**：
- **这是 Evidence-first 原则的执行点**：没有证据的答案不允许生成
- 所有被移除的 chunk 及原因记录在 `retrieval_trace` 中
- 验证过程本身被审计日志记录

### 2.2.12 Claim Generation（事实声明生成）

**处理**：
- 基于通过证据验证的 chunks，使用 LLM 生成结构化事实声明（Claim）
- 每个 Claim 包含：声明文本、置信度、引用的 chunk_ids
- Claim 格式：`{ claim_text, confidence, evidence_chunk_ids, dissent_note? }`
- `dissent_note`：如果 chunks 之间存在矛盾信息，必须注明

**关键约束**：
- **Provenance-first 原则**：每个 Claim 必须绑定原始数据来源
- Claim 不能包含任何无法追溯到 chunk 的信息
- LLM 不允许"凭空推理"：所有事实性输出必须有 evidence 支撑
- 当证据不足时，生成 `INSUFFICIENT_EVIDENCE` 标记而非编造答案

**输出**：`response_claim` 和 `claim_evidence` 记录

### 2.2.13 Response Rendering（响应渲染）

**处理**：
- 将 Claim 列表渲染为用户可读的回答
- 引用标注格式：`[来源: 2024-03-15 微信记录]`
- 不确定性标注：`⚠️ 该信息仅基于单条记录，置信度较低`
- 情感安全标注：如果回答可能触发悲伤情绪，添加适当的缓冲语

**关键约束**：
- 响应文本中的每个事实句必须可点击跳转到原始证据
- 渲染过程不添加任何不在 Claim 中的信息

### 2.2.14 Audit Logging（审计日志）

**处理**：
- 完整记录本次交互的：
  - 用户问题
  - 检索到的 chunk_ids
  - rerank 排序
  - 证据验证结果（通过/未通过及原因）
  - 生成的 Claims
  - 最终响应用户的内容
  - 使用的模型和参数
  - 时间戳和 duration

**输出**：`audit_log` 记录

**关键约束**：
- 审计日志**不可修改、不可删除**（APPEND ONLY）
- 即使数据被用户销毁，审计日志保留（但日志中的具体内容引用标记为 `REDACTED`）
- 审计日志用于：合规审查、效果评估、安全事件追溯

## 2.3 Data Immutability Matrix

| 数据类别 | 可变 | 可删除 | 可重新生成 | Scope 隔离 |
|---------|------|--------|-----------|------------|
| source_artifact | 仅 status | 仅用户主动销毁 | 否（依赖原始文件） | N/A（全局） |
| raw_message | 否 | 否 | 否（从源文件重新解析） | N/A（全局） |
| normalized_message | 否（标记式） | 否（标记 FILTERED） | 是 | N/A（全局） |
| memory_chunk | 否 | 否（可标记 DEPRECATED） | 是 | 所属 scope |
| memory_chunk_span | 跟随 chunk | 跟随 chunk | 是 | 所属 scope |
| memory_annotation | 可由用户修正 | 可标记无效 | 是 | 所属 scope |
| embedding_index_ref | 否 | 可批量删除重建 | 是 | 所属 scope |
| retrieval_trace | 否 | 否 | 否 | 所属 scope |
| response_claim | 否 | 否（软删除） | 否 | 所属 scope |
| claim_evidence | 否 | 否 | 否 | 所属 scope |
| interaction_session | 否 | 否 | 否 | 所属 scope |
| interaction_message | 否 | 否 | 否 | 所属 scope |
| safety_event | 否 | 否 | 否 | N/A（全局） |
| audit_log | 否 | 否 | 否 | N/A（全局） |

---

# Chapter 3: remnant-etl Design

## 3.1 ETL 管道架构

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Source       │     │  Normalize   │     │   Clean      │
│  Parsers      │────►│  & Validate  │────►│   & Filter   │
│  (per format) │     │              │     │              │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
                                                  ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Embedding   │◄────│   Annotate   │◄────│    Chunk     │
│  & Index     │     │   & Span     │     │  & Hash      │
└──────────────┘     └──────────────┘     └──────────────┘
```

**核心设计原则**：
1. 管道是纯函数式变换：输入不变，输出可重算
2. 每一步都是幂等的：同一输入重新执行，产生相同输出
3. 每一步都可独立回滚：从任意步骤重新开始，后续步骤重算

## 3.2 输入数据格式覆盖

| 数据源 | 文件格式 | 解析器 | 特殊处理 |
|-------|---------|--------|----------|
| 微信 txt 导出 | UTF-8 / GBK 文本 | `WechatTxtParser` | 时间戳格式：`2024-01-15 10:30:22 说话人\n消息内容` |
| 微信数据库 | SQLite DB | `WechatDBParser` | 需要解密 EnMicroMsg.db；MSG 表需要多表 JOIN |
| 邮件 | mbox / eml / emlx | `EmailParser` (Python `mailbox`) | 支持多账号合并 |
| 日记 | txt / md | `DiaryParser` | 无对话结构，整篇作为一个 chunk 单元 |
| 音频转写文本 | JSON (Whisper 输出) | `TranscriptionParser` | 保留时间戳和说话人标签 |
| OCR 文本 | txt / JSON | `OCRParser` | 保留页码和区域信息 |

### WechatTxtParser 伪代码

```python
import re
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class RawMessage:
    id: str                          # UUID
    source_artifact_id: str          # 关联源文件
    timestamp: Optional[datetime]    # 原始时间戳
    speaker: str                     # 原始说话人标识
    content: str                     # 原始内容文本
    content_type: str                # text / image_placeholder / system_event
    metadata: dict                   # 额外元数据
    parse_status: str                # OK / PARTIAL / FAILED

# 微信 txt 导出格式正则
WECHAT_LINE_PATTERN = re.compile(
    r'^(?:(\d{4}-\d{2}-\d{2})\s+)?'    # 日期（可选）
    r'(\d{2}:\d{2}(?::\d{2})?)\s*'     # 时间
    r'([^:\n]+?)\s*'                     # 说话人
    r'(?::|：)\s*'                       # 分隔符
    r'(.*)$'                             # 消息内容
    , re.MULTILINE
)

SYSTEM_MSG_PATTERN = re.compile(
    r'^---\s*(.+?)\s*---$|'
    r'^(.+?)(?:加入了群聊|邀请)(.+?)$|'
    r'^「(.+?)」撤回了一条消息$'
)

class WechatTxtParser:
    """解析微信导出 txt 文件为 RawMessage 列表"""
    
    def __init__(self, source_artifact_id: str):
        self.source_artifact_id = source_artifact_id
    
    def parse(self, file_path: str, encoding: str = "auto") -> List[RawMessage]:
        text = self._read_file(file_path, encoding)
        segments = self._split_by_date(text)
        
        messages = []
        for date_str, segment in segments:
            for line in segment.split("\n"):
                msg = self._parse_line(line, date_str)
                if msg:
                    messages.append(msg)
        
        # 尝试为无时间戳消息推断时间
        messages = self._infer_timestamps(messages)
        return messages
    
    def _read_file(self, file_path: str, encoding: str) -> str:
        if encoding == "auto":
            # 尝试 UTF-8 → GBK → GB18030
            for enc in ["utf-8", "gbk", "gb18030"]:
                try:
                    with open(file_path, "r", encoding=enc) as f:
                        return f.read()
                except UnicodeDecodeError:
                    continue
            raise ValueError(f"无法识别文件编码: {file_path}")
        with open(file_path, "r", encoding=encoding) as f:
            return f.read()
    
    def _split_by_date(self, text: str) -> List[tuple]:
        """按日期分隔线切分，返回 (date_str, segment_text) 列表"""
        date_pattern = re.compile(r'^=+\s*(\d{4}年\d{1,2}月\d{1,2}日.*?)\s*=+$', re.MULTILINE)
        parts = date_pattern.split(text)
        # 如果没有日期行，整体视为一段
        if len(parts) == 1:
            return [(None, text)]
        result = []
        for i in range(1, len(parts), 2):
            result.append((parts[i], parts[i+1] if i+1 < len(parts) else ""))
        return result
    
    def _parse_line(self, line: str, date_str: Optional[str]) -> Optional[RawMessage]:
        line = line.strip()
        if not line:
            return None
        
        # 检查是否是系统消息
        if SYSTEM_MSG_PATTERN.match(line):
            return RawMessage(
                id=generate_uuid(),
                source_artifact_id=self.source_artifact_id,
                timestamp=None,
                speaker="__SYSTEM__",
                content=line,
                content_type="system_event",
                metadata={"date_hint": date_str},
                parse_status="OK"
            )
        
        # 尝试匹配普通消息
        match = WECHAT_LINE_PATTERN.match(line)
        if match:
            date_part, time_part, speaker, content = match.groups()
            # 日期合并
            full_time_str = f"{date_str or ''} {time_part}".strip()
            try:
                ts = datetime.strptime(full_time_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    ts = datetime.strptime(full_time_str, "%Y-%m-%d %H:%M")
                except ValueError:
                    ts = None
            
            content_type = self._classify_content(content)
            return RawMessage(
                id=generate_uuid(),
                source_artifact_id=self.source_artifact_id,
                timestamp=ts,
                speaker=speaker,
                content=content,
                content_type=content_type,
                metadata={"date_hint": date_str},
                parse_status="OK" if ts else "PARTIAL"
            )
        
        # 无法识别的行作为续行内容
        return None
    
    def _classify_content(self, content: str) -> str:
        if content in ("[图片]", "[Image]", "[照片]"):
            return "image_placeholder"
        if content in ("[语音]", "[Voice]", "[视频]", "[Video]"):
            return "media_placeholder"
        if content.startswith("[文件]") or content.startswith("[File]"):
            return "file_reference"
        return "text"
```

## 3.3 清洗策略

清洗环节执行多个 filter，每个 filter 独立、可配置、可跳过：

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Set

class MessageStatus(str, Enum):
    NORMALIZED = "NORMALIZED"
    CLEANED = "CLEANED"
    FILTERED = "FILTERED"        # 被清洗过滤，保留但标记
    UNCERTAIN = "UNCERTAIN"       # 置信度低

@dataclass
class NormalizedMessage:
    id: str
    raw_message_id: str
    source_artifact_id: str
    timestamp: Optional[datetime]
    speaker: str
    speaker_normalized: str        # 统一后的说话人标识
    content: str
    content_type: str
    status: MessageStatus = MessageStatus.NORMALIZED
    filter_tags: List[str] = field(default_factory=list)  # 标记哪些 filter 处理过
    metadata: dict = field(default_factory=dict)

class BaseFilter(ABC):
    """清洗过滤器基类"""
    
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @abstractmethod
    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> Optional[str]:
        """
        返回 None 表示保留，返回原因字符串表示过滤。
        被过滤的消息标记为 FILTERED 但不删除。
        """
        ...
    
    def should_tag(self, msg: NormalizedMessage, ctx: FilterContext) -> Optional[str]:
        """
        返回 None 表示不标记，返回标签字符串表示附加标签。
        标记的消息保留但附加上下文信息。
        """
        return None

@dataclass
class FilterContext:
    """清洗上下文，提供跨消息信息"""
    config: dict                          # 用户可配置的过滤规则
    speaker_aliases: dict                 # 说话人别名映射
    previous_message: Optional[NormalizedMessage] = None
    message_buffer: List[NormalizedMessage] = field(default_factory=list)

class SystemMessageFilter(BaseFilter):
    """过滤系统消息"""
    name = "system_message"
    
    SYSTEM_PREFIXES = [
        "已经过了", "你已添加", "邀请了", "加入了群聊",
        "修改群名为", "移出了", "解散了群聊"
    ]
    
    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> Optional[str]:
        if msg.content_type == "system_event":
            return "system_message"
        for prefix in self.SYSTEM_PREFIXES:
            if msg.content.startswith(prefix):
                return "system_message"
        return None

class RecallMessageFilter(BaseFilter):
    """过滤撤回消息"""
    name = "recall_message"
    
    RECALL_PATTERN = re.compile(r'^「(.+?)」撤回了一条消息$')
    
    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> Optional[str]:
        if self.RECALL_PATTERN.match(msg.content):
            return "recall_message"
        return None

class FinancialEventFilter(BaseFilter):
    """标记（但不过滤）转账/红包消息"""
    name = "financial_event"
    
    FINANCIAL_PATTERNS = [
        r'收到红包.*?[¥￥]\d+',
        r'转账.*?[¥￥]\d+',
        r'微信转账.*?[¥￥]\d+',
    ]
    
    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> Optional[str]:
        return None  # 不过滤，只标记
    
    def should_tag(self, msg: NormalizedMessage, ctx: FilterContext) -> Optional[str]:
        for pattern in self.FINANCIAL_PATTERNS:
            if re.search(pattern, msg.content):
                return "FINANCIAL_EVENT"
        return None

class EmojiPlaceholderFilter(BaseFilter):
    """替换表情占位符"""
    name = "emoji_placeholder"
    
    EMOJI_MAP = {
        "[微笑]": "😊", "[撇嘴]": "😒", "[色]": "😍",
        "[发呆]": "😐", "[得意]": "😎", "[流泪]": "😢",
        "[害羞]": "😳", "[闭嘴]": "🤐", "[睡]": "😴",
        "[大哭]": "😭", "[尴尬]": "😅", "[发怒]": "😠",
        "[调皮]": "😜", "[呲牙]": "😁", "[惊讶]": "😮",
        "[难过]": "😞", "[酷]": "😎", "[冷汗]": "😰",
        "[抓狂]": "🤯", "[吐]": "🤮", "[偷笑]": "🤭",
        "[愉快]": "🙂", "[白眼]": "🙄", "[傲慢]": "😤",
        "[饥饿]": "🤤", "[困]": "😪", "[惊恐]": "😱",
        "[流汗]": "😓", "[憨笑]": "😄", "[悠闲]": "😌",
        "[奋斗]": "💪", "[咒骂]": "🤬", "[疑问]": "❓",
        "[嘘]": "🤫", "[晕]": "😵", "[折磨]": "😩",
        "[衰]": "😞", "[骷髅]": "💀", "[敲打]": "🔨",
    }
    
    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> Optional[str]:
        return None  # 不过滤，只替换
    
    def transform(self, msg: NormalizedMessage, ctx: FilterContext) -> NormalizedMessage:
        content = msg.content
        for placeholder, emoji in self.EMOJI_MAP.items():
            content = content.replace(placeholder, emoji)
        # 未映射的 [xxx] 格式保留原样
        msg.content = content
        msg.filter_tags.append("emoji_replaced")
        return msg

class DuplicateMessageFilter(BaseFilter):
    """标记重复消息"""
    name = "duplicate_message"
    
    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> Optional[str]:
        prev = ctx.previous_message
        if prev is None:
            return None
        # 同一说话人，5秒内，内容完全相同
        if (msg.speaker_normalized == prev.speaker_normalized
            and msg.content == prev.content
            and msg.timestamp and prev.timestamp
            and abs((msg.timestamp - prev.timestamp).total_seconds()) < 5):
            return "duplicate_message"
        return None

class ShortFragmentFilter(BaseFilter):
    """标记极短碎片"""
    name = "short_fragment"
    
    def should_tag(self, msg: NormalizedMessage, ctx: FilterContext) -> Optional[str]:
        if len(msg.content.strip()) < 3 and not re.match(r'^[\W]+$', msg.content.strip()):
            return "SHORT_FRAGMENT"
        return None

class NoTimestampFilter(BaseFilter):
    """标记无时间戳消息"""
    name = "no_timestamp"
    
    def should_tag(self, msg: NormalizedMessage, ctx: FilterContext) -> Optional[str]:
        if msg.timestamp is None:
            return "UNCERTAIN_TIMESTAMP"
        return None

class SpeakerAliasNormalizer:
    """说话人别名统一"""
    
    def normalize_speaker(self, speaker: str, alias_map: dict) -> str:
        """
        alias_map 示例: {
            "妈": "mother",
            "妈妈": "mother", 
            "老妈": "mother",
            "爸": "father",
            "爸爸": "father",
        }
        """
        return alias_map.get(speaker, speaker)


def filter_noise(
    messages: List[NormalizedMessage],
    config: dict,
    speaker_aliases: dict,
) -> List[NormalizedMessage]:
    """
    执行清洗管道。
    消息不会被物理删除，只标记为 FILTERED 或添加标签。
    """
    filters = [
        SystemMessageFilter(),
        RecallMessageFilter(),
        FinancialEventFilter(),
        EmojiPlaceholderFilter(),
        DuplicateMessageFilter(),
        ShortFragmentFilter(),
        NoTimestampFilter(),
    ]
    
    # 根据用户配置启用/禁用 filter
    enabled_filters = [
        f for f in filters 
        if config.get(f.name, True)  # 默认全部启用
    ]
    
    # 说话人统一
    normalizer = SpeakerAliasNormalizer()
    for msg in messages:
        msg.speaker_normalized = normalizer.normalize_speaker(msg.speaker, speaker_aliases)
    
    # 执行过滤管道
    ctx = FilterContext(config=config, speaker_aliases=speaker_aliases)
    result = []
    
    for i, msg in enumerate(messages):
        ctx.previous_message = result[-1] if result else None
        ctx.message_buffer = result[-10:]  # 最近10条消息作为上下文
        
        filtered = False
        for f in enabled_filters:
            reason = f.should_filter(msg, ctx)
            if reason:
                msg.status = MessageStatus.FILTERED
                msg.filter_tags.append(reason)
                filtered = True
                break
            
            tag = f.should_tag(msg, ctx)
            if tag:
                msg.filter_tags.append(tag)
        
        # Emoji 替换是 transform 而非 filter
        if hasattr(f, 'transform') and isinstance(f, EmojiPlaceholderFilter):
            msg = f.transform(msg, ctx)
        
        result.append(msg)
    
    return result
```

## 3.4 动态分块算法

### 分块策略概述

分块（Chunking）是 ETL 管道中最复杂的环节。对话数据不适合简单按 token 数切块，需要综合考虑：

| 因素 | 权重 | 说明 |
|------|------|------|
| 时间间隔 | 高 | 超过阈值的时间间隙强制切分 |
| 对话轮次 | 高 | 同一话题的多轮对话应保持完整 |
| 说话人切换 | 中 | 说话人切换是话题变化的弱信号 |
| 语义相似度 | 中 | 相邻消息的语义连贯性 |
| 消息密度 | 低 | 短消息密集区域合并，长消息独立成块 |
| 最大 token 限制 | 硬约束 | 单个 chunk 不超过 max_tokens（默认 512） |
| 最小 token 限制 | 软约束 | 单个 chunk 不低于 min_tokens（默认 50），否则尝试合并 |
| 上下文 overlap | 固定 | 相邻 chunk 之间 overlap 约 10-20% |

### 分块算法伪代码

```python
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from collections import defaultdict
import hashlib

@dataclass
class ConversationSegment:
    """对话段：一组时间相近、话题连贯的消息"""
    id: str
    messages: List[NormalizedMessage]
    start_timestamp: Optional[datetime]
    end_timestamp: Optional[datetime]
    speaker_set: set
    topic_hint: Optional[str] = None

@dataclass  
class MemoryChunk:
    """记忆分块：最终入库的检索单元"""
    id: str
    source_artifact_id: str
    chunk_hash: str
    chunk_type: str                    # conversation_segment / diary_entry / letter
    content: str                       # 拼接后的文本
    token_count: int
    time_range_start: Optional[datetime]
    time_range_end: Optional[datetime]
    metadata: dict
    spans: List['ChunkSpan'] = field(default_factory=list)

@dataclass
class ChunkSpan:
    """分块溯源：从 chunk 回到原始消息的映射"""
    id: str
    chunk_id: str
    normalized_message_id: str
    char_start: int                    # 在 chunk.content 中的起始字符偏移
    char_end: int                      # 在 chunk.content 中的结束字符偏移
    source_speaker: str                # 这段内容的说话人
    source_timestamp: Optional[datetime]

# ── 配置参数 ──
CHUNK_CONFIG = {
    "max_tokens": 512,
    "min_tokens": 50,
    "time_gap_threshold_seconds": 1800,   # 30分钟无消息则强制切分
    "time_gap_soft_seconds": 600,          # 10分钟以上开始考虑切分
    "max_messages_per_chunk": 40,          # 单个 chunk 最多包含的消息数
    "overlap_messages": 2,                  # 相邻 chunk overlap 的消息数
    "semantic_similarity_threshold": 0.65,  # 语义相似度低于此值考虑切分
    "speaker_change_weight": 0.3,          # 说话人切换在决策中的权重
}


def build_conversation_segments(
    messages: List[NormalizedMessage],
    config: dict = CHUNK_CONFIG,
) -> List[ConversationSegment]:
    """
    第一阶段：按时间间隔将消息初步分为对话段。
    长时间无消息 = 新对话段的开始。
    """
    if not messages:
        return []
    
    segments = []
    current_msgs = [messages[0]]
    current_speakers = {messages[0].speaker_normalized}
    
    for i in range(1, len(messages)):
        prev = messages[i - 1]
        curr = messages[i]
        
        # 跳过被过滤的消息
        if curr.status == MessageStatus.FILTERED:
            continue
        
        should_split = False
        
        # 规则 1：时间间隔超过硬阈值，强制切分
        if prev.timestamp and curr.timestamp:
            gap = (curr.timestamp - prev.timestamp).total_seconds()
            if gap >= config["time_gap_threshold_seconds"]:
                should_split = True
        
        # 规则 2：消息密度检查
        if len(current_msgs) >= config["max_messages_per_chunk"]:
            should_split = True
        
        # 规则 3：系统事件断开
        if curr.content_type == "system_event":
            should_split = True
        
        if should_split:
            # 保存当前段
            seg = ConversationSegment(
                id=generate_uuid(),
                messages=list(current_msgs),
                start_timestamp=current_msgs[0].timestamp,
                end_timestamp=current_msgs[-1].timestamp,
                speaker_set=set(current_speakers),
            )
            segments.append(seg)
            # 开始新段
            current_msgs = [curr]
            current_speakers = {curr.speaker_normalized}
        else:
            current_msgs.append(curr)
            current_speakers.add(curr.speaker_normalized)
    
    # 处理最后一个段
    if current_msgs:
        seg = ConversationSegment(
            id=generate_uuid(),
            messages=list(current_msgs),
            start_timestamp=current_msgs[0].timestamp,
            end_timestamp=current_msgs[-1].timestamp,
            speaker_set=set(current_speakers),
        )
        segments.append(seg)
    
    return segments


def semantic_chunk(
    segments: List[ConversationSegment],
    embedding_fn: callable,     # (text) -> List[float]
    config: dict = CHUNK_CONFIG,
) -> List[MemoryChunk]:
    """
    第二阶段：基于语义相似度对对话段进一步切分或合并。
    
    策略：
    1. 对每个 segment，如果 token 数 > max_tokens，切分
    2. 对每个 segment，如果 token 数 < min_tokens，尝试与相邻段合并
    3. 切分点选择：寻找语义相似度最低的相邻消息对
    4. 合并条件：语义相似度 > threshold 且 token 数不超限
    """
    chunks = []
    
    for seg in segments:
        seg_text = _concat_messages(seg.messages)
        seg_tokens = _estimate_tokens(seg_text)
        
        if seg_tokens <= config["max_tokens"]:
            # 整段作为一个 chunk
            if seg_tokens >= config["min_tokens"] or len(seg.messages) <= 3:
                # 长度够，直接成块
                chunk = _build_chunk_from_messages(
                    seg.messages, seg.start_timestamp, seg.end_timestamp,
                    "conversation_segment", config
                )
                chunks.append(chunk)
            # 长度不够，留到合并阶段处理
            else:
                seg._pending_chunk = True
        else:
            # 超长，需要切分
            sub_chunks = _split_segment_by_semantic(
                seg, embedding_fn, config
            )
            chunks.extend(sub_chunks)
    
    # 合并阶段：相邻的短 chunk 尝试合并
    chunks = _merge_short_chunks(chunks, config)
    
    # 添加 overlap
    chunks = _add_overlaps(chunks, config)
    
    return chunks


def _split_segment_by_semantic(
    segment: ConversationSegment,
    embedding_fn: callable,
    config: dict,
) -> List[MemoryChunk]:
    """
    对超长对话段进行语义切分。
    计算相邻消息的语义距离，找到最佳的切分点。
    """
    messages = segment.messages
    if len(messages) <= 1:
        return [_build_chunk_from_messages(
            messages, segment.start_timestamp, segment.end_timestamp,
            "conversation_segment", config
        )]
    
    # 计算相邻消息的语义距离
    distances = []
    for i in range(len(messages) - 1):
        # 用消息内容 + 上下文信息计算 embedding
        ctx_text_1 = f"[{messages[i].speaker_normalized}] {messages[i].content}"
        ctx_text_2 = f"[{messages[i+1].speaker_normalized}] {messages[i+1].content}"
        
        emb1 = embedding_fn(ctx_text_1)
        emb2 = embedding_fn(ctx_text_2)
        
        # 余弦距离
        distance = 1 - _cosine_similarity(emb1, emb2)
        
        # 说话人切换加权
        if messages[i].speaker_normalized != messages[i+1].speaker_normalized:
            distance += config["speaker_change_weight"]
        
        # 时间间隙加权
        if messages[i].timestamp and messages[i+1].timestamp:
            gap = (messages[i+1].timestamp - messages[i].timestamp).total_seconds()
            if gap > 60:  # 超过1分钟有额外权重
                distance += min(gap / 3600, 0.5)  # 最多加0.5
        
        distances.append(distance)
    
    # 找到切分点：语义距离的局部最大值
    # 使用动态规划或贪心策略，在 max_tokens 约束下找到最优切分
    split_points = _find_split_points(
        messages, distances, 
        max_tokens=config["max_tokens"],
        min_tokens=config["min_tokens"],
    )
    
    # 在切分点分割
    chunks = []
    start = 0
    for sp in split_points:
        end = sp + 1  # 包含切分点后的第一条消息
        sub_msgs = messages[start:end]
        chunk = _build_chunk_from_messages(
            sub_msgs,
            sub_msgs[0].timestamp,
            sub_msgs[-1].timestamp,
            "conversation_segment",
            config,
        )
        chunks.append(chunk)
        start = end
    
    # 处理最后一段
    if start < len(messages):
        sub_msgs = messages[start:]
        chunk = _build_chunk_from_messages(
            sub_msgs,
            sub_msgs[0].timestamp,
            sub_msgs[-1].timestamp,
            "conversation_segment",
            config,
        )
        chunks.append(chunk)
    
    return chunks


def _find_split_points(
    messages: List[NormalizedMessage],
    distances: List[float],
    max_tokens: int,
    min_tokens: int,
) -> List[int]:
    """
    贪心策略：从左到右累积 token，当累积到 min_tokens 以上且
    遇到语义距离局部最大值时，在此处切分。
    """
    split_points = []
    accumulated_tokens = 0
    last_split = 0
    
    for i in range(len(distances)):
        msg_tokens = _estimate_tokens(messages[i].content)
        accumulated_tokens += msg_tokens
        
        # 必须达到最小 token 数才考虑切分
        if accumulated_tokens < min_tokens:
            continue
        
        # 超过最大 token 数，强制切分
        if accumulated_tokens >= max_tokens:
            split_points.append(i)
            accumulated_tokens = 0
            last_split = i + 1
            continue
        
        # 检查是否是局部最大值
        is_local_max = True
        window = 2
        for j in range(max(0, i - window), min(len(distances), i + window + 1)):
            if j != i and distances[j] > distances[i]:
                is_local_max = False
                break
        
        if is_local_max and distances[i] > 0.3:  # 距离阈值
            # 检查切分后剩余部分是否不会太短
            remaining_tokens = sum(
                _estimate_tokens(messages[k].content) 
                for k in range(i + 1, len(messages))
            )
            if remaining_tokens >= min_tokens:
                split_points.append(i)
                accumulated_tokens = 0
                last_split = i + 1
    
    return split_points


def attach_source_spans(
    chunk: MemoryChunk,
    messages: List[NormalizedMessage],
) -> MemoryChunk:
    """
    为 chunk 中每条消息建立溯源映射。
    chunk.content 的拼接格式：
    "[说话人] 消息内容\n[说话人] 消息内容\n..."
    每个 span 记录在 chunk.content 中的字符偏移。
    """
    content_parts = []
    spans = []
    offset = 0
    
    for msg in messages:
        if msg.status == MessageStatus.FILTERED:
            continue
        
        line = f"[{msg.speaker_normalized}] {msg.content}\n"
        content_parts.append(line)
        
        span = ChunkSpan(
            id=generate_uuid(),
            chunk_id=chunk.id,
            normalized_message_id=msg.id,
            char_start=offset,
            char_end=offset + len(line) - 1,  # 不含末尾 \n
            source_speaker=msg.speaker_normalized,
            source_timestamp=msg.timestamp,
        )
        spans.append(span)
        offset += len(line)
    
    chunk.content = "".join(content_parts)
    chunk.spans = spans
    return chunk


def generate_chunk_hash(chunk: MemoryChunk) -> str:
    """
    生成 chunk 的内容哈希，用于去重和完整性校验。
    哈希输入：content + source_artifact_id + 拼接的 normalized_message_ids
    """
    hash_input = (
        chunk.content
        + chunk.source_artifact_id
        + "".join(sorted(s.normalized_message_id for s in chunk.spans))
    )
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()


def _build_chunk_from_messages(
    messages: List[NormalizedMessage],
    start_ts: Optional[datetime],
    end_ts: Optional[datetime],
    chunk_type: str,
    config: dict,
) -> MemoryChunk:
    """从消息列表构建 MemoryChunk"""
    content, spans = _concat_with_spans(messages)
    chunk = MemoryChunk(
        id=generate_uuid(),
        source_artifact_id=messages[0].source_artifact_id,
        chunk_hash="",  # 稍后生成
        chunk_type=chunk_type,
        content=content,
        token_count=_estimate_tokens(content),
        time_range_start=start_ts,
        time_range_end=end_ts,
        metadata={
            "message_count": len(messages),
            "speaker_count": len(set(m.speaker_normalized for m in messages)),
        },
    )
    chunk = attach_source_spans(chunk, messages)
    chunk.chunk_hash = generate_chunk_hash(chunk)
    return chunk


def _merge_short_chunks(
    chunks: List[MemoryChunk],
    config: dict,
) -> List[MemoryChunk]:
    """合并相邻的短 chunk"""
    if not chunks:
        return chunks
    
    merged = [chunks[0]]
    for chunk in chunks[1:]:
        prev = merged[-1]
        combined_tokens = prev.token_count + chunk.token_count
        
        # 合并条件：合并后不超 max_tokens，且同一 source_artifact
        if (combined_tokens <= config["max_tokens"]
            and prev.source_artifact_id == chunk.source_artifact_id
            and prev.token_count < config["min_tokens"]):
            # 合并
            prev.content += chunk.content
            prev.token_count = combined_tokens
            prev.spans.extend(chunk.spans)
            prev.time_range_end = chunk.time_range_end
            prev.chunk_hash = generate_chunk_hash(prev)
        else:
            merged.append(chunk)
    
    return merged


def _add_overlaps(
    chunks: List[MemoryChunk],
    config: dict,
) -> List[MemoryChunk]:
    """
    为相邻 chunk 添加 overlap。
    每个 chunk 的尾部 overlap_messages 条消息同时出现在下一个 chunk 的头部。
    """
    overlap_count = config["overlap_messages"]
    if len(chunks) <= 1 or overlap_count <= 0:
        return chunks
    
    result = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            # 第一个 chunk：尾部不需要额外处理（下一个 chunk 会包含其尾部消息）
            result.append(chunk)
        else:
            # 从前一个 chunk 的尾部取 overlap 条消息作为当前 chunk 的头部
            prev = chunks[i - 1]
            overlap_msgs = prev.spans[-overlap_count:] if len(prev.spans) > overlap_count else prev.spans
            # 注意：这里简化了，实际需要从 normalized_message 表中重新读取消息内容
            # 并将 overlap 部分拼接到 chunk.content 的头部
            # chunk.content = overlap_text + "\n---\n" + chunk.content
            result.append(chunk)  # 实际实现中需要修改 content
    
    return result
```

### 完整 ETL Pipeline 入口

```python
class ETLPipeline:
    """完整的 ETL 管道"""
    
    def __init__(self, config: dict, store: RemnantStore, embedding_fn: callable):
        self.config = config
        self.store = store
        self.embedding_fn = embedding_fn
    
    def run(self, source_artifact_id: str) -> ETLPipelineResult:
        """
        执行完整 ETL 管道。
        
        Returns:
            ETLPipelineResult: 包含所有产出物的结果对象
        """
        # Step 1: 加载源文件
        artifact = self.store.get_source_artifact(source_artifact_id)
        if not artifact:
            raise ValueError(f"Source artifact not found: {source_artifact_id}")
        
        # Step 2: 解析原始数据
        parser = self._get_parser(artifact.file_type)
        raw_messages = parser.parse(artifact.file_path, source_artifact_id)
        self.store.persist_raw_messages(raw_messages)
        
        # Step 3: 规范化
        normalized = normalize_messages(raw_messages, self.config)
        self.store.persist_normalized_messages(normalized)
        
        # Step 4: 清洗
        cleaned = filter_noise(
            normalized, 
            config=self.config.get("filters", {}),
            speaker_aliases=self.config.get("speaker_aliases", {}),
        )
        self.store.update_normalized_message_status(cleaned)
        
        # Step 5: 构建对话段
        segments = build_conversation_segments(
            [m for m in cleaned if m.status != MessageStatus.FILTERED],
            config=self.config.get("chunking", CHUNK_CONFIG),
        )
        
        # Step 6: 语义分块
        chunks = semantic_chunk(
            segments, 
            embedding_fn=self.embedding_fn,
            config=self.config.get("chunking", CHUNK_CONFIG),
        )
        
        # Step 7: 附加溯源信息
        for chunk in chunks:
            attach_source_spans(chunk, ...)
            chunk.chunk_hash = generate_chunk_hash(chunk)
        
        # Step 8: 持久化
        self.store.persist_chunks(chunks)
        
        # Step 9: 标注 (异步)
        # annotations = annotate_chunks(chunks, llm_provider)
        # self.store.persist_annotations(annotations)
        
        # Step 10: 向量化 (异步)
        # for chunk in chunks:
        #     embedding = self.embedding_fn(chunk.content)
        #     self.store.persist_embedding(chunk.id, embedding)
        
        # Step 11: 更新 artifact 状态
        self.store.update_artifact_status(source_artifact_id, "PROCESSED")
        
        return ETLPipelineResult(
            source_artifact_id=source_artifact_id,
            raw_count=len(raw_messages),
            normalized_count=len(normalized),
            filtered_count=sum(1 for m in cleaned if m.status == MessageStatus.FILTERED),
            chunk_count=len(chunks),
        )
    
    def _get_parser(self, file_type: str) -> BaseParser:
        parsers = {
            "wechat_txt": WechatTxtParser,
            "wechat_db": WechatDBParser,
            "email_mbox": EmailParser,
            "diary_txt": DiaryParser,
            "transcription_json": TranscriptionParser,
            "ocr_txt": OCRParser,
        }
        parser_cls = parsers.get(file_type)
        if not parser_cls:
            raise ValueError(f"Unsupported file type: {file_type}")
        return parser_cls()
```

### Trade-off 说明

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| 分块算法 | 面向对话的动态分块 | 固定 token 滑窗 | 对话数据有天然的轮次和时间边界，固定滑窗会切断完整对话 |
| 语义距离计算 | 逐消息 embedding | 段级 embedding | 段级更快但无法找到段内切分点 |
| overlap 策略 | 消息级 overlap | 字符级 overlap | 消息级更简洁且保证溯源边界对齐 |
| embedding 批量 vs 逐条 | 分批（batch=32） | 逐条 | v0.1 阶段数据量有限，逐条也可接受；批量提升 3-5x |
| 清洗标记 vs 删除 | 标记 FILTERED | 物理删除 | 符合 Raw Data Immutable 原则，且保留审计能力 |

---

# Chapter 4: Core Data Model

## 4.1 数据分类

在定义 DDL 之前，明确每张表的数据分类：

### Raw Data（原始数据，不可变）
- `source_artifact` — 数据来源文件记录
- `raw_message` — 原始解析消息（不可 UPDATE / DELETE）

### Derived Data（派生数据，可重新生成）
- `normalized_message` — 规范化后的消息
- `memory_chunk` — 记忆分块
- `memory_chunk_span` — 分块溯源映射
- `memory_annotation` — 标注信息
- `embedding_index_ref` — 向量索引引用

### Relationship-Scoped Data（关系作用域数据，严格隔离）
- `interaction_session` — 交互会话
- `interaction_message` — 交互消息
- `retrieval_trace` — 检索追踪
- `response_claim` — 响应声明
- `claim_evidence` — 声明证据

### Cross-Scope Shareable Data（可跨作用域共享）
- `deceased_profile` — 逝者档案（全局唯一）
- `source_artifact` — 数据来源（全局，但关联到逝者）
- `raw_message` — 原始消息（全局，但关联到逝者）
- `audit_log` — 审计日志（全局只追加）

### Absolutely Never Cross-Scope Data（绝对不可跨作用域共享）
- `relationship_scope` — 关系作用域定义本身（隔离元数据）
- `data_subject_consent` — 授权同意（每个关系独立）
- `interaction_session` — 交互会话（每个关系独立）
- `interaction_message` — 交互消息（每个关系独立）
- `retrieval_trace` — 检索记录（每个关系独立）
- `response_claim` — 响应声明（每个关系独立）

## 4.2 SQLite/SQLCipher DDL

```sql
-- ============================================================
-- Remnant v0.1 Core Data Model
-- SQLite / SQLCipher DDL
-- ============================================================

-- 开启 WAL 模式和外键约束
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA recursive_triggers = ON;

-- ============================================================
-- 1. deceased_profile — 逝者档案
-- 全局唯一，不属于任何 relationship_scope
-- ============================================================
CREATE TABLE deceased_profile (
    id              TEXT PRIMARY KEY,             -- UUID v7
    name            TEXT NOT NULL,                 -- 逝者姓名
    display_name    TEXT,                          -- 显示名称（由亲属设定）
    birth_date      TEXT,                          -- ISO 8601 date
    death_date      TEXT,                          -- ISO 8601 date
    bio             TEXT,                          -- 简短传记
    avatar_path     TEXT,                          -- 头像本地路径
    metadata        TEXT DEFAULT '{}',             -- JSON 扩展字段
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at      TEXT                           -- 软删除时间戳
);

CREATE INDEX idx_deceased_profile_name ON deceased_profile(name);

-- ============================================================
-- 2. data_subject_consent — 数据主体授权同意
-- 每个 relationship_scope 独立，不可跨 scope 共享
-- ============================================================
CREATE TABLE data_subject_consent (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    deceased_profile_id  TEXT NOT NULL,
    relationship_scope_id  TEXT NOT NULL,             -- 关联 relationship_scope.id
    data_category       TEXT NOT NULL,                 -- 授权数据类别: raw_text / voice / image / financial / medical
    consent_type        TEXT NOT NULL,                 -- granted / denied / withdrawn
    consent_scope       TEXT NOT NULL,                 -- read / query / annotate / destroy
    granted_at          TEXT,                          -- 授权时间
    withdrawn_at        TEXT,                          -- 撤回时间
    expires_at          TEXT,                          -- 过期时间
    consent_evidence    TEXT,                          -- 授权证据（如截图路径、声明文本）
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    
    FOREIGN KEY (deceased_profile_id) REFERENCES deceased_profile(id),
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id)
);

CREATE INDEX idx_consent_scope ON data_subject_consent(relationship_scope_id, data_category);
CREATE INDEX idx_consent_deceased ON data_subject_consent(deceased_profile_id);

-- ============================================================
-- 3. relationship_scope — 关系作用域
-- 绝对隔离的核心单元
-- ============================================================
CREATE TABLE relationship_scope (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    deceased_profile_id  TEXT NOT NULL,
    scope_name          TEXT NOT NULL,                 -- 作用域名称（如 "作为儿子" "作为同事"）
    relationship_type    TEXT NOT NULL,                 -- child / spouse / sibling / parent / friend / colleague / other
    scope_description    TEXT,                          -- 作用域描述
    encryption_key_hash  TEXT,                          -- 作用域加密密钥哈希（v0.1 预留）
    is_active           INTEGER NOT NULL DEFAULT 1,    -- 1=活跃, 0=已停用
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at          TEXT,
    
    FOREIGN KEY (deceased_profile_id) REFERENCES deceased_profile(id)
);

CREATE INDEX idx_scope_deceased ON relationship_scope(deceased_profile_id);

-- ============================================================
-- 4. source_artifact — 数据来源文件
-- Raw Data，全局可共享但关联到逝者
-- ============================================================
CREATE TABLE source_artifact (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    deceased_profile_id  TEXT NOT NULL,
    file_path           TEXT NOT NULL,                 -- 原始文件路径（存入 .remnant/data/raw/ 后的路径）
    file_hash           TEXT NOT NULL,                 -- SHA-256
    file_size           INTEGER NOT NULL,              -- 字节
    file_type           TEXT NOT NULL,                 -- wechat_txt / wechat_db / email_mbox / diary_txt / transcription_json / ocr_txt
    mime_type           TEXT,                          -- MIME 类型
    encoding            TEXT,                          -- 文件编码（utf-8 / gbk / ...）
    parse_status        TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING / PARSING / PARSED / FAILED
    parse_error         TEXT,                          -- 解析失败原因
    date_range_start    TEXT,                          -- 数据覆盖时间范围起始
    date_range_end      TEXT,                          -- 数据覆盖时间范围结束
    message_count       INTEGER DEFAULT 0,             -- 解析出的消息数
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at          TEXT,
    
    FOREIGN KEY (deceased_profile_id) REFERENCES deceased_profile(id),
    
    -- 文件 hash 唯一，防止重复导入
    UNIQUE(file_hash)
);

CREATE INDEX idx_artifact_deceased ON source_artifact(deceased_profile_id);
CREATE INDEX idx_artifact_status ON source_artifact(parse_status);

-- ============================================================
-- 5. raw_message — 原始消息
-- Raw Data, IMMUTABLE. 写入后不可 UPDATE 或 DELETE.
-- ============================================================
CREATE TABLE raw_message (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    source_artifact_id  TEXT NOT NULL,
    timestamp           TEXT,                          -- 原始时间戳（ISO 8601）
    speaker             TEXT NOT NULL,                 -- 原始说话人标识（未规范化）
    content             TEXT NOT NULL,                 -- 原始内容（不可变）
    content_type        TEXT NOT NULL DEFAULT 'text', -- text / image_placeholder / system_event / ...
    parse_status        TEXT NOT NULL DEFAULT 'OK',   -- OK / PARTIAL / FAILED
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    
    FOREIGN KEY (source_artifact_id) REFERENCES source_artifact(id)
);

CREATE INDEX idx_raw_source ON raw_message(source_artifact_id);
CREATE INDEX idx_raw_timestamp ON raw_message(timestamp);
CREATE INDEX idx_raw_speaker ON raw_message(speaker);

-- Raw message 不可变约束（通过 trigger 实现）
CREATE TRIGGER trg_prevent_raw_message_update
BEFORE UPDATE ON raw_message
BEGIN
    SELECT RAISE(ABORT, 'raw_message is immutable: UPDATE not allowed');
END;

CREATE TRIGGER trg_prevent_raw_message_delete
BEFORE DELETE ON raw_message
BEGIN
    SELECT RAISE(ABORT, 'raw_message is immutable: DELETE not allowed');
END;

-- ============================================================
-- 6. normalized_message — 规范化消息
-- Derived Data, 可重新生成
-- ============================================================
CREATE TABLE normalized_message (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    raw_message_id      TEXT NOT NULL,
    source_artifact_id  TEXT NOT NULL,
    timestamp           TEXT,                          -- 规范化后的 ISO 8601 UTC 时间戳
    timestamp_confidence TEXT DEFAULT 'CERTAIN',      -- CERTAIN / INFERRED / UNCERTAIN
    speaker_original    TEXT NOT NULL,                 -- 原始说话人
    speaker_normalized  TEXT NOT NULL,                 -- 规范化后的说话人标识
    person_id           TEXT,                          -- 映射到的人物 ID（预留）
    content             TEXT NOT NULL,                 -- 规范化后的内容
    content_type        TEXT NOT NULL DEFAULT 'text', -- text / image_placeholder / media_placeholder / system_event / financial_event
    status              TEXT NOT NULL DEFAULT 'NORMALIZED',  -- NORMALIZED / CLEANED / FILTERED / DEPRECATED
    filter_tags         TEXT DEFAULT '[]',             -- JSON array: ["system_message", "duplicate_message", ...]
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    
    FOREIGN KEY (raw_message_id) REFERENCES raw_message(id),
    FOREIGN KEY (source_artifact_id) REFERENCES source_artifact(id)
);

CREATE INDEX idx_norm_source ON normalized_message(source_artifact_id);
CREATE INDEX idx_norm_timestamp ON normalized_message(timestamp);
CREATE INDEX idx_norm_speaker ON normalized_message(speaker_normalized);
CREATE INDEX idx_norm_status ON normalized_message(status);
CREATE INDEX idx_norm_raw ON normalized_message(raw_message_id);

-- ============================================================
-- 7. memory_chunk — 记忆分块
-- Derived Data, 可重新生成
-- ============================================================
CREATE TABLE memory_chunk (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    source_artifact_id  TEXT NOT NULL,
    relationship_scope_id TEXT,                       -- 所属关系作用域（NULL 表示公共，待分配）
    chunk_hash          TEXT NOT NULL,                 -- SHA-256 内容哈希
    chunk_type          TEXT NOT NULL,                 -- conversation_segment / diary_entry / letter / mixed / user_provided_context / transcription
    content             TEXT NOT NULL,                 -- 拼接后的文本内容
    token_count         INTEGER NOT NULL DEFAULT 0,
    time_range_start    TEXT,                          -- ISO 8601
    time_range_end      TEXT,                          -- ISO 8601
    message_count       INTEGER NOT NULL DEFAULT 0,
    speaker_count       INTEGER NOT NULL DEFAULT 0,
    overlap_previous    INTEGER DEFAULT 0,             -- 与前一个 chunk 的 overlap 消息数
    overlap_next        INTEGER DEFAULT 0,             -- 与下一个 chunk 的 overlap 消息数
    status              TEXT NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE / DEPRECATED / ARCHIVED
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at          TEXT,
    
    FOREIGN KEY (source_artifact_id) REFERENCES source_artifact(id),
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id)
);

CREATE INDEX idx_chunk_source ON memory_chunk(source_artifact_id);
CREATE INDEX idx_chunk_scope ON memory_chunk(relationship_scope_id);
CREATE INDEX idx_chunk_hash ON memory_chunk(chunk_hash);
CREATE INDEX idx_chunk_time ON memory_chunk(time_range_start, time_range_end);
CREATE INDEX idx_chunk_status ON memory_chunk(status);

-- chunk hash 唯一约束（同一 source_artifact 内）
CREATE UNIQUE INDEX idx_chunk_unique ON memory_chunk(source_artifact_id, chunk_hash);

-- ============================================================
-- 8. memory_chunk_span — 分块溯源映射
-- Derived Data. 每个 chunk 能通过此表追溯到原始 normalized_message.
-- ============================================================
CREATE TABLE memory_chunk_span (
    id                      TEXT PRIMARY KEY,             -- UUID v7
    chunk_id                TEXT NOT NULL,
    normalized_message_id   TEXT NOT NULL,
    char_start              INTEGER NOT NULL,             -- 在 chunk.content 中的起始字符偏移
    char_end                INTEGER NOT NULL,             -- 在 chunk.content 中的结束字符偏移
    source_speaker          TEXT NOT NULL,                 -- 这段内容的说话人
    source_timestamp        TEXT,                          -- 这段内容的时间戳
    
    FOREIGN KEY (chunk_id) REFERENCES memory_chunk(id),
    FOREIGN KEY (normalized_message_id) REFERENCES normalized_message(id)
);

CREATE INDEX idx_span_chunk ON memory_chunk_span(chunk_id);
CREATE INDEX idx_span_message ON memory_chunk_span(normalized_message_id);

-- ============================================================
-- 9. memory_annotation — 记忆标注
-- Derived Data, 可由用户修正
-- ============================================================
CREATE TABLE memory_annotation (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    chunk_id            TEXT NOT NULL,
    annotation_type     TEXT NOT NULL,                 -- SENTIMENT / TOPIC / COREFERENCE / KEY_EVENT / RISK
    annotation_value    TEXT NOT NULL,                 -- 标注值（如 "positive" / ["生日", "家庭"] / "指代张三"）
    confidence          REAL DEFAULT 1.0,              -- 0.0 ~ 1.0
    source              TEXT NOT NULL DEFAULT 'llm',  -- llm / user / rule
    is_valid            INTEGER NOT NULL DEFAULT 1,   -- 1=有效, 0=已标记无效
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    
    FOREIGN KEY (chunk_id) REFERENCES memory_chunk(id)
);

CREATE INDEX idx_annotation_chunk ON memory_annotation(chunk_id);
CREATE INDEX idx_annotation_type ON memory_annotation(annotation_type);
CREATE INDEX idx_annotation_valid ON memory_annotation(is_valid);

-- ============================================================
-- 10. embedding_index_ref — 向量索引引用
-- Derived Data, 可重新生成
-- ============================================================
CREATE TABLE embedding_index_ref (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    chunk_id            TEXT NOT NULL,
    model_name          TEXT NOT NULL,                 -- bge-small-zh / bge-m3 / nomic-embed-text
    model_version       TEXT,                          -- 模型版本标识
    vector_dimension    INTEGER NOT NULL,              -- 512 / 1024 / 768
    index_backend       TEXT NOT NULL DEFAULT 'sqlite_vec',  -- sqlite_vec / lancedb
    index_status        TEXT NOT NULL DEFAULT 'PENDING',     -- PENDING / INDEXED / STALE / FAILED
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    
    FOREIGN KEY (chunk_id) REFERENCES memory_chunk(id)
);

CREATE INDEX idx_embedding_chunk ON embedding_index_ref(chunk_id);
CREATE INDEX idx_embedding_model ON embedding_index_ref(model_name);
CREATE INDEX idx_embedding_status ON embedding_index_ref(index_status);

-- ============================================================
-- 11. retrieval_trace — 检索追踪
-- Relationship-Scoped, 不可跨 scope 共享
-- ============================================================
CREATE TABLE retrieval_trace (
    id                      TEXT PRIMARY KEY,             -- UUID v7
    relationship_scope_id   TEXT NOT NULL,
    interaction_session_id  TEXT,                          -- 关联的交互会话
    query_text              TEXT NOT NULL,                 -- 用户查询文本
    query_embedding_model   TEXT,                          -- 查询使用的 embedding 模型
    fts_results             TEXT DEFAULT '[]',             -- JSON: FTS5 检索结果 [{chunk_id, score}]
    vector_results          TEXT DEFAULT '[]',             -- JSON: 向量检索结果 [{chunk_id, score}]
    reranked_results        TEXT DEFAULT '[]',             -- JSON: 重排序结果 [{chunk_id, score, rank}]
    evidence_validated      TEXT DEFAULT '[]',             -- JSON: 证据验证通过的结果
    evidence_rejected       TEXT DEFAULT '[]',             -- JSON: 证据验证未通过的结果及原因
    total_duration_ms       INTEGER,                       -- 总检索耗时
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    FOREIGN KEY (interaction_session_id) REFERENCES interaction_session(id)
);

CREATE INDEX idx_trace_scope ON retrieval_trace(relationship_scope_id);
CREATE INDEX idx_trace_session ON retrieval_trace(interaction_session_id);
CREATE INDEX idx_trace_time ON retrieval_trace(created_at);

-- ============================================================
-- 12. response_claim — 响应声明
-- Relationship-Scoped, 不可跨 scope 共享
-- ============================================================
CREATE TABLE response_claim (
    id                      TEXT PRIMARY KEY,             -- UUID v7
    relationship_scope_id   TEXT NOT NULL,
    interaction_session_id  TEXT NOT NULL,
    interaction_message_id  TEXT,                          -- 关联的用户消息
    claim_text              TEXT NOT NULL,                 -- 事实声明文本
    confidence              REAL NOT NULL DEFAULT 0.5,     -- 0.0 ~ 1.0
    dissent_note            TEXT,                          -- 矛盾说明（如果证据冲突）
    evidence_sufficient     INTEGER NOT NULL DEFAULT 1,   -- 1=证据充分, 0=INSUFFICIENT_EVIDENCE
    model_used              TEXT,                          -- 生成此 claim 的 LLM 模型
    model_parameters        TEXT DEFAULT '{}',             -- JSON: 温度、top_p 等
    status                  TEXT NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE / REVISED / DEPRECATED
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at              TEXT,                          -- 软删除
    
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    FOREIGN KEY (interaction_session_id) REFERENCES interaction_session(id)
);

CREATE INDEX idx_claim_scope ON response_claim(relationship_scope_id);
CREATE INDEX idx_claim_session ON response_claim(interaction_session_id);
CREATE INDEX idx_claim_confidence ON response_claim(confidence);

-- ============================================================
-- 13. claim_evidence — 声明证据关联
-- Relationship-Scoped, 不可跨 scope 共享
-- 每个 claim 必须能追溯到 chunk → chunk_span → normalized_message → source_artifact
-- ============================================================
CREATE TABLE claim_evidence (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    claim_id            TEXT NOT NULL,
    chunk_id            TEXT NOT NULL,
    span_id             TEXT,                          -- 可选：具体到 span 级别
    evidence_type       TEXT NOT NULL,                 -- primary / supporting / contradictory
    relevance_score     REAL,                          -- 与 claim 的相关性评分
    is_direct_quote     INTEGER NOT NULL DEFAULT 0,   -- 是否为直接引用
    excerpt             TEXT,                          -- 证据摘录文本
    
    FOREIGN KEY (claim_id) REFERENCES response_claim(id),
    FOREIGN KEY (chunk_id) REFERENCES memory_chunk(id),
    FOREIGN KEY (span_id) REFERENCES memory_chunk_span(id)
);

CREATE INDEX idx_evidence_claim ON claim_evidence(claim_id);
CREATE INDEX idx_evidence_chunk ON claim_evidence(chunk_id);
CREATE INDEX idx_evidence_type ON claim_evidence(evidence_type);

-- ============================================================
-- 14. interaction_session — 交互会话
-- Relationship-Scoped, 绝对隔离
-- ============================================================
CREATE TABLE interaction_session (
    id                      TEXT PRIMARY KEY,             -- UUID v7
    relationship_scope_id   TEXT NOT NULL,
    deceased_profile_id     TEXT NOT NULL,
    session_type             TEXT NOT NULL DEFAULT 'conversation',  -- conversation / browse / review
    started_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ended_at                 TEXT,                          -- 会话结束时间
    total_messages           INTEGER DEFAULT 0,
    total_duration_seconds   INTEGER,                       -- 会话总时长
    llm_model_used           TEXT,                          -- 使用的主 LLM
    llm_model_version        TEXT,
    metadata                 TEXT DEFAULT '{}',
    created_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    FOREIGN KEY (deceased_profile_id) REFERENCES deceased_profile(id)
);

CREATE INDEX idx_session_scope ON interaction_session(relationship_scope_id);
CREATE INDEX idx_session_deceased ON interaction_session(deceased_profile_id);
CREATE INDEX idx_session_time ON interaction_session(started_at);

-- ============================================================
-- 15. interaction_message — 交互消息
-- Relationship-Scoped, 绝对隔离
-- ============================================================
CREATE TABLE interaction_message (
    id                      TEXT PRIMARY KEY,             -- UUID v7
    session_id              TEXT NOT NULL,
    relationship_scope_id   TEXT NOT NULL,
    role                    TEXT NOT NULL,                 -- user / assistant / system
    content                 TEXT NOT NULL,                 -- 消息内容
    claim_ids               TEXT DEFAULT '[]',             -- JSON: 关联的 claim IDs（仅 assistant 消息）
    retrieval_trace_id      TEXT,                          -- 关联的检索追踪（仅 assistant 消息）
    model_used              TEXT,                           -- 生成模型
    token_usage             TEXT DEFAULT '{}',              -- JSON: {prompt_tokens, completion_tokens, total_tokens}
    duration_ms             INTEGER,                        -- 生成耗时
    safety_flags            TEXT DEFAULT '[]',              -- JSON: 安全标记
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    
    FOREIGN KEY (session_id) REFERENCES interaction_session(id),
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    FOREIGN KEY (retrieval_trace_id) REFERENCES retrieval_trace(id)
);

CREATE INDEX idx_msg_session ON interaction_message(session_id);
CREATE INDEX idx_msg_scope ON interaction_message(relationship_scope_id);
CREATE INDEX idx_msg_time ON interaction_message(created_at);
CREATE INDEX idx_msg_role ON interaction_message(role);

-- ============================================================
-- 16. safety_event — 安全事件
-- 全局记录，不属于特定 scope
-- ============================================================
CREATE TABLE safety_event (
    id                      TEXT PRIMARY KEY,             -- UUID v7
    relationship_scope_id   TEXT,                          -- 可选：关联的作用域
    event_type              TEXT NOT NULL,                 -- ANTI_DEPENDENCY_TRIGGER / CONSENT_VIOLATION /
                                                            -- DATA_EXPORT_BLOCKED / LATE_NIGHT_USAGE /
                                                            -- EMOTIONAL_DISTRESS / EXCESSIVE_USAGE
    severity                TEXT NOT NULL DEFAULT 'warning',  -- info / warning / critical / emergency
    description             TEXT NOT NULL,                 -- 事件描述
    trigger_data            TEXT DEFAULT '{}',             -- JSON: 触发数据（使用时长、情绪评分等）
    action_taken            TEXT NOT NULL,                 -- LOGGED / SESSION_PAUSED / SCOPE_SUSPENDED /
                                                            -- USER_NOTIFIED / COOL_DOWN_ENFORCED
    resolved_at             TEXT,                          -- 解决时间
    metadata                TEXT DEFAULT '{}',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id)
);

CREATE INDEX idx_safety_scope ON safety_event(relationship_scope_id);
CREATE INDEX idx_safety_type ON safety_event(event_type);
CREATE INDEX idx_safety_severity ON safety_event(severity);
CREATE INDEX idx_safety_time ON safety_event(created_at);

-- ============================================================
-- 17. audit_log — 审计日志
-- APPEND ONLY, 不可修改或删除
-- 全局记录，不属于特定 scope
-- ============================================================
CREATE TABLE audit_log (
    id                      TEXT PRIMARY KEY,             -- UUID v7
    relationship_scope_id   TEXT,                          -- 可选：关联的作用域
    action                  TEXT NOT NULL,                 -- DATA_IMPORT / DATA_ACCESS / DATA_QUERY /
                                                            -- DATA_EXPORT / DATA_DESTROY / CONSENT_CHANGE /
                                                            -- SCOPE_CREATE / SCOPE_SUSPEND / SAFETY_TRIGGER
    actor                   TEXT NOT NULL,                 -- user / system / policy_engine
    target_type             TEXT NOT NULL,                 -- source_artifact / raw_message / normalized_message /
                                                            -- memory_chunk / relationship_scope / consent
    target_id               TEXT NOT NULL,                 -- 目标对象 ID
    detail                  TEXT DEFAULT '{}',             -- JSON: 操作详情
    ip_address              TEXT,                          -- localhost（本地应用），预留
    user_agent              TEXT,                          -- 应用版本信息
    redacted                INTEGER NOT NULL DEFAULT 0,   -- 1=内容已根据销毁请求脱敏
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_audit_action ON audit_log(action);
CREATE INDEX idx_audit_target ON audit_log(target_type, target_id);
CREATE INDEX idx_audit_scope ON audit_log(relationship_scope_id);
CREATE INDEX idx_audit_time ON audit_log(created_at);

-- 审计日志不可修改或删除
CREATE TRIGGER trg_prevent_audit_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE not allowed');
END;

CREATE TRIGGER trg_prevent_audit_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: DELETE not allowed');
END;

-- ============================================================
-- FTS5 全文搜索索引
-- ============================================================
CREATE VIRTUAL TABLE memory_chunk_fts USING fts5(
    content,
    content='memory_chunk',
    content_rowid='rowid',
    tokenize='simple'     -- v0.1 使用 simple tokenizer，中文内容由 jieba 预分词后空格分隔入库
    -- 后续可替换为自定义 jieba tokenizer（需编译 C 扩展）
    -- fallback: tokenize='unicode61' （逐字符切分，中文召回率低）
);

-- FTS5 同步触发器
CREATE TRIGGER trg_chunk_fts_insert AFTER INSERT ON memory_chunk
BEGIN
    INSERT INTO memory_chunk_fts(rowid, content) VALUES (
        (SELECT rowid FROM memory_chunk WHERE id = NEW.id), NEW.content
    );
END;

CREATE TRIGGER trg_chunk_fts_update AFTER UPDATE ON memory_chunk
BEGIN
    INSERT INTO memory_chunk_fts(memory_chunk_fts, rowid, content) VALUES (
        'delete', (SELECT rowid FROM memory_chunk WHERE id = NEW.id), OLD.content
    );
    INSERT INTO memory_chunk_fts(rowid, content) VALUES (
        (SELECT rowid FROM memory_chunk WHERE id = NEW.id), NEW.content
    );
END;

CREATE TRIGGER trg_chunk_fts_delete AFTER DELETE ON memory_chunk
BEGIN
    INSERT INTO memory_chunk_fts(memory_chunk_fts, rowid, content) VALUES (
        'delete', (SELECT rowid FROM memory_chunk WHERE id = OLD.id), OLD.content
    );
END;

-- ============================================================
-- sqlite-vec 向量索引表（由 remnant-store 管理）
-- 此表结构由 sqlite-vec 扩展定义，此处仅作为参考
-- ============================================================
-- CREATE VIRTUAL TABLE memory_chunk_vec USING vec0(
--     chunk_id TEXT PRIMARY KEY,
--     embedding FLOAT[512]  -- 维度取决于 embedding 模型
-- );

-- ============================================================
-- 数据销毁支持：软删除 + 级联标记
-- ============================================================

-- 当 relationship_scope 被销毁时，级联软删除所有关联数据
-- 注意：这里使用软删除（设置 deleted_at），不物理删除
-- 物理删除需要用户明确确认，且执行后审计日志保留但内容标记为 REDACTED

CREATE TRIGGER trg_scope_soft_delete_chunks
AFTER UPDATE OF deleted_at ON relationship_scope
WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL
BEGIN
    UPDATE memory_chunk 
    SET deleted_at = NEW.deleted_at 
    WHERE relationship_scope_id = NEW.id AND deleted_at IS NULL;
    
    UPDATE interaction_session 
    SET ended_at = CASE WHEN ended_at IS NULL THEN NEW.deleted_at ELSE ended_at END
    WHERE relationship_scope_id = NEW.id;
    
    -- 审计日志记录销毁操作
    INSERT INTO audit_log (id, action, actor, target_type, target_id, detail)
    VALUES (
        lower(hex(randomblob(4)) || hex(randomblob(2)) || hex(randomblob(2)) || hex(randomblob(2)) || hex(randomblob(6))),
        'DATA_DESTROY',
        'system',
        'relationship_scope',
        NEW.id,
        json('{"reason": "scope_soft_delete", "scope_name": "' || NEW.scope_name || '"}')
    );
END;
```

## 4.3 数据分类汇总

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Raw Data (IMMUTABLE)                             │
│                                                                         │
│   source_artifact ─────┐                                               │
│                         │                                               │
│   raw_message ─────────┼─── 不可 UPDATE / DELETE                      │
│                         │    可追加（APPEND ONLY）                      │
│                         │    不可跨 scope 但全局关联到 deceased         │
│                         │                                               │
└─────────────────────────┼───────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      Derived Data (REGENERABLE)                         │
│                                                                         │
│   normalized_message ◄─── 可重新生成，可标记状态                        │
│   memory_chunk ◄───────── 可重新生成，可标记 DEPRECATED                  │
│   memory_chunk_span ◄─── 跟随 chunk 重新生成                           │
│   memory_annotation ◄─── 可由用户修正，可标记无效                       │
│   embedding_index_ref ◄─ 可批量删除重建                                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   Relationship-Scoped Data (ISOLATED)                     │
│                                                                         │
│   interaction_session ◄────── 绝对隔离                                 │
│   interaction_message ◄────── 绝对隔离                                 │
│   retrieval_trace ◄────────── 绝对隔离                                 │
│   response_claim ◄─────────── 绝对隔离                                 │
│   claim_evidence ◄─────────── 绝对隔离                                 │
│   data_subject_consent ◄──── 绝对隔离                                  │
│                                                                         │
│   ★ 这些数据在不同 relationship_scope 之间绝对不能共享 ★               │
│   ★ 查询时必须 WHERE relationship_scope_id = :scope_id ★              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Cross-Scope Shareable Data                           │
│                                                                         │
│   deceased_profile ◄──────── 全局唯一，所有 scope 共享                  │
│   source_artifact ◄───────── 全局共享，一个逝者一份                    │
│   raw_message ◄───────────── 全局共享，关联到逝者                      │
│   audit_log ◄─────────────── 全局只追加，不可修改                      │
│   safety_event ◄─────────── 全局记录安全事件                            │
│                                                                         │
│   ★ 共享条件：仅限元数据共享，具体内容仍需 scope 过滤 ★                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## 4.4 关键约束说明

### 不可变约束

| 表 | 约束 | 实现方式 |
|---|---|---|
| `raw_message` | 不可 UPDATE / DELETE | SQLite TRIGGER `RAISE(ABORT)` |
| `audit_log` | 不可 UPDATE / DELETE | SQLite TRIGGER `RAISE(ABORT)` |

### Scope 隔离约束

| 查询场景 | 隔离方式 | 说明 |
|---------|---------|------|
| 检索 memory_chunk | `WHERE relationship_scope_id = :scope_id` | 每个查询必须限定 scope |
| 插入 interaction_message | 必须指定 `relationship_scope_id` | 不允许 NULL scope |
| 查询 claim_evidence | 通过 `response_claim` 间接限定 scope | claim → scope 过滤后再取 evidence |
| 向量检索 | sqlite-vec 查询时附加 scope 过滤 | ANN 搜索后用 scope 过滤 |
| FTS 检索 | FTS5 搜索后附加 scope 过滤 | 先搜 FTS，再 WHERE scope |

### 数据销毁支持

| 销毁级别 | 影响范围 | 操作 | 审计 |
|---------|---------|------|------|
| Scope 级销毁 | 单个 relationship_scope 的所有 scoped data | 软删除（设置 `deleted_at`）| ✅ 审计日志记录 |
| Deceased 级销毁 | 该逝者下所有数据 | 级联软删除所有关联表 | ✅ 审计日志记录 |
| 物理删除 | 用户明确确认后 | 删除 SQLite 行 + 删除文件 | ✅ 审计日志保留但内容标记 `REDACTED` |
| Selective 数据撤回 | 单条数据 | 标记 `status = WITHDRAWN` | ✅ 审计日志记录 |

### Hash 校验链

```
source_artifact.file_hash (SHA-256 of original file)
    │
    ▼
raw_message (linked by source_artifact_id)
    │
    ▼
normalized_message (linked by raw_message_id)
    │
    ▼
memory_chunk (linked by source_artifact_id)
    │ + memory_chunk.chunk_hash (SHA-256 of concatenated content + source + message IDs)
    │
    ▼
memory_chunk_span (linked by chunk_id + normalized_message_id)
    │
    ▼
claim_evidence → response_claim → interaction_message
```

**完整性校验**：任何环节的数据篡改都可通过 hash 链检测：
1. source_artifact.file_hash → 校验原始文件完整性
2. memory_chunk.chunk_hash → 校验 chunk 内容完整性
3. claim_evidence.excerpt → 与原始 chunk.content 比对

## 4.5 Index 设计说明

| 索引 | 类型 | 用途 | 选择性估计 |
|------|------|------|-----------|
| `idx_raw_source` | B-Tree | 按源文件查消息 | 高（每个源文件百/万条） |
| `idx_norm_speaker` | B-Tree | 按说话人查消息 | 中（说话人数量有限） |
| `idx_chunk_scope` | B-Tree | 查询作用域内 chunk | 高（隔离核心索引） |
| `idx_chunk_time` | B-Tree | 时间范围查询 | 中（时间分布不均） |
| `idx_trace_time` | B-Tree | 按时间查审计记录 | 高（时间递增） |
| `idx_audit_action` | B-Tree | 按动作类型查审计 | 低（类型有限） |
| `memory_chunk_fts` | FTS5 | 全文搜索 chunk | N/A |
| `memory_chunk_vec` | vec0 | 向量近似搜索 | N/A |

**Trade-off**：索引数量在 v0.1 阶段保留较多，因为单机 SQLite 的写入性能不是瓶颈（每秒几十次导入），而查询性能是用户体验的关键。后续如需优化，可以移除低选择性的索引。

---

# Chapter 5: Memory Chunk Schema

本章定义 `memory_chunk` 的结构化 JSON Schema，作为 remnant-core 检索与 RAG 管线的基础数据单元。该 Schema 同时用于 ETL 管道的 chunk 输出校验和运行时检索结果的反序列化。

## 5.1 设计原则

1. **Provenance-first**：每个 chunk 必须能完整追溯到原始数据来源，溯源链路为 `chunk → source_spans → normalized_message → raw_message → source_artifact`
2. **Derived Annotation Only**：chunk 是 derived artifact，可以重新生成；其上的标注（annotation）也是 derived 的
3. **Scope-aware**：chunk 最终归属某个 relationship_scope，但 ETL 阶段可能暂未分配（`relationship_scope_id = NULL` 表示待分配）
4. **Integrity-checkable**：`chunk_hash` 保证内容完整性，任何篡改可被检测

## 5.2 完整 JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://remnant.app/schemas/memory_chunk/v1",
  "title": "MemoryChunk",
  "description": "Remnant 记忆分块 — 最小检索与溯源单元",
  "type": "object",
  "required": [
    "chunk_id", "deceased_profile_id", "source_artifact_id",
    "chunk_type", "speaker_set", "primary_speaker",
    "timestamp_range", "source_spans", "text_normalized",
    "text_original_refs", "semantic_labels", "emotion_labels",
    "relationship_tags", "annotation_refs", "embedding_model",
    "embedding_version", "chunk_hash", "provenance_level", "confidence"
  ],
  "properties": {
    "chunk_id": {
      "type": "string",
      "format": "uuid",
      "description": "chunk 唯一标识符，UUID v7 时间排序"
    },
    "deceased_profile_id": {
      "type": "string",
      "format": "uuid",
      "description": "所属逝者档案 ID。chunk 必须关联到唯一逝者，确保检索时的 top-level 过滤"
    },
    "source_artifact_id": {
      "type": "string",
      "format": "uuid",
      "description": "溯源至原始数据来源文件。同一 source_artifact 可产生多个 chunk"
    },
    "chunk_type": {
      "type": "string",
      "enum": [
        "conversation_segment",
        "diary_entry",
        "letter",
        "voice_transcript",
        "ocr_extract",
        "mixed"
      ],
      "description": "分块类型枚举，详见 5.3"
    },
    "speaker_set": {
      "type": "array",
      "items": { "type": "string" },
      "description": "本 chunk 中出现的所有说话人标识（normalized 后）。用于说话人感知检索"
    },
    "primary_speaker": {
      "type": "string",
      "description": "本 chunk 的主要说话人。对于对话类型，取发言条数最多的说话人；对于日记/信件，取作者"
    },
    "timestamp_range": {
      "type": "object",
      "description": "chunk 覆盖的时间范围",
      "required": ["start", "end", "confidence"],
      "properties": {
        "start": {
          "type": "string",
          "format": "date-time",
          "description": "chunk 中最早消息的时间戳，ISO 8601 UTC"
        },
        "end": {
          "type": "string",
          "format": "date-time",
          "description": "chunk 中最晚消息的时间戳，ISO 8601 UTC"
        },
        "confidence": {
          "type": "string",
          "enum": ["CERTAIN", "INFERRED", "UNCERTAIN"],
          "description": "时间戳置信度。CERTAIN=原始数据已有时间戳; INFERRED=通过上下文推断; UNCERTAIN=无法确定"
        }
      }
    },
    "source_spans": {
      "type": "array",
      "description": "溯源映射：chunk 内容到原始 normalized_message 的精确映射",
      "items": {
        "type": "object",
        "required": ["normalized_message_id", "char_start", "char_end", "speaker", "timestamp"],
        "properties": {
          "normalized_message_id": {
            "type": "string",
            "format": "uuid",
            "description": "关联的 normalized_message ID"
          },
          "char_start": {
            "type": "integer",
            "minimum": 0,
            "description": "在 text_normalized 中的起始字符偏移（含）"
          },
          "char_end": {
            "type": "integer",
            "minimum": 0,
            "description": "在 text_normalized 中的结束字符偏移（不含）"
          },
          "speaker": {
            "type": "string",
            "description": "该 span 的说话人（normalized 后）"
          },
          "timestamp": {
            "type": ["string", "null"],
            "format": "date-time",
            "description": "该 span 对应的原始时间戳，null 表示时间戳缺失"
          }
        }
      }
    },
    "text_normalized": {
      "type": "string",
      "description": "规范化后的 chunk 文本内容。格式为逐行拼接：'[说话人] 消息内容\\n'。此字段为 chunk 的主要检索文本，也是 embedding 和 FTS5 的输入"
    },
    "text_original_refs": {
      "type": "array",
      "description": "对原始文本的引用片段。用于溯源展示，保留原始措辞",
      "items": {
        "type": "object",
        "required": ["normalized_message_id", "original_text"],
        "properties": {
          "normalized_message_id": {
            "type": "string",
            "format": "uuid",
            "description": "关联的 normalized_message ID"
          },
          "original_text": {
            "type": "string",
            "description": "原始消息文本（normalized_message.content），未经过任何改写"
          }
        }
      }
    },
    "semantic_labels": {
      "type": "array",
      "description": "LLM 标注的语义标签，topic 级别",
      "items": {
        "type": "object",
        "required": ["label", "confidence"],
        "properties": {
          "label": {
            "type": "string",
            "description": "语义标签，如 '家庭关系'、'健康'、'工作'、'旅行'、'情感表达'"
          },
          "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "标注置信度"
          }
        }
      }
    },
    "emotion_labels": {
      "type": "array",
      "description": "情感标注",
      "items": {
        "type": "object",
        "required": ["label", "confidence"],
        "properties": {
          "label": {
            "type": "string",
            "enum": [
              "neutral", "positive", "negative",
              "joy", "sadness", "anger", "fear",
              "affection", "nostalgia", "grief_trigger",
              "anxiety", "humor"
            ],
            "description": "情感标签。grief_trigger 标记可能触发使用者强烈悲伤情绪的内容"
          },
          "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "标注置信度"
          }
        }
      }
    },
    "relationship_tags": {
      "type": "array",
      "description": "关系维度标签，标记本 chunk 涉及的关系场景",
      "items": {
        "type": "string",
        "enum": [
          "parent_child", "spouse", "sibling",
          "friend", "colleague", "mentor",
          "grandparent_grandchild", "extended_family",
          "general"
        ]
      }
    },
    "annotation_refs": {
      "type": "array",
      "description": "关联的 memory_annotation ID 列表。用于追踪 LLM 标注来源",
      "items": {
        "type": "object",
        "required": ["annotation_id", "annotation_type"],
        "properties": {
          "annotation_id": {
            "type": "string",
            "format": "uuid",
            "description": "memory_annotation 表的 ID"
          },
          "annotation_type": {
            "type": "string",
            "enum": ["SENTIMENT", "TOPIC", "COREFERENCE", "KEY_EVENT", "RISK"],
            "description": "标注类型"
          }
        }
      }
    },
    "embedding_model": {
      "type": "string",
      "description": "生成 embedding 使用的模型名称，如 'bge-small-zh', 'bge-m3', 'nomic-embed-text'",
      "default": "bge-small-zh"
    },
    "embedding_version": {
      "type": "string",
      "description": "embedding 模型版本号或 git commit hash，确保可重现",
      "default": "v1"
    },
    "chunk_hash": {
      "type": "string",
      "pattern": "^[a-f0-9]{64}$",
      "description": "SHA-256 哈希值。输入为 text_normalized + source_artifact_id + 排序后的 normalized_message_ids 拼接。用于去重和完整性校验"
    },
    "provenance_level": {
      "type": "string",
      "enum": ["primary_source", "derived_from_source", "inferred", "user_provided_context"],
      "description": "溯源等级，详见 5.4"
    },
    "confidence": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0,
      "description": "chunk 整体置信度评分，0.0~1.0，详见 5.5"
    }
  },
  "additionalProperties": false
}
```

## 5.3 chunk_type 枚举值详解

| 值 | 描述 | 典型场景 | 特殊约定 |
|---|---|---|---|
| `conversation_segment` | 多轮对话片段 | 微信聊天、短信、多人群聊 | speaker_set ≥ 2；primary_speaker 取发言最多者 |
| `diary_entry` | 日记/日志条目 | 个人日记、备忘录 | speaker_set = {作者}；primary_speaker = 作者；timestamp 通常为日期粒度 |
| `letter` | 书信/邮件 | 正式信件、长邮件 | speaker_set 可能包含寄信人和收信人；primary_speaker = 寄信人 |
| `voice_transcript` | 语音转写文本 | 通话记录、语音消息转写 | timestamp_range.confidence 通常为 INFERRED；需标注转写准确率 |
| `ocr_extract` | OCR 提取文本 | 扫描件、手写信件识别 | confidence 通常较低；text_original_refs 保留原始扫描区域坐标 |
| `mixed` | 混合类型 | 上述类型无法明确分类时的兜底 | 使用场景少，建议在 ETL 中尽量细分 |

**Trade-off**：设置 `mixed` 兜底类型而非强行分类。理由：部分数据源（如零散截图+文本混合）确实难以明确归类，强制分类会引入错误标注，不如让下游按 mixed 处理。

## 5.4 provenance_level 分级

| 等级 | 含义 | 校验方式 | 对响应的影响 |
|------|------|---------|------------|
| `primary_source` | 内容直接来自逝者原创的原始数据 | 溯源链路完整：`chunk → source_spans → normalized_message → raw_message → source_artifact`；file_hash 可验证 | 可作为最高可信度的引用来源 |
| `derived_from_source` | 内容从原始数据派生（如清洗后的文本、指代消解结果） | 溯源链路可追踪到 raw_message，但内容经过变换 | 可引用，但需标注"经过处理" |
| `inferred` | 内容由 LLM 标注或推断得出（如情感标签、主题标签） | annotation_refs 指向 LLM 标注，confidence 量化不确定性 | 不可直接作为事实引用，只能作为辅助参考 |
| `user_provided_context` | 内容由用户口述或手动输入（如家族口述历史） | 没有原始数据溯源，只有用户声明 | 必须明确标注"用户提供的上下文，未经原始数据验证" |

**关键约束**：

1. `provenance_level` 由 ETL 管道在 chunk 创建时自动设定，规则如下：
   - 对话/日记/信件类 chunk → `primary_source`
   - 经过指代消解、情感标注等 LLM 处理的 → `derived_from_source`
   - LLM 完全推断的内容 → `inferred`
   - 用户在对话中补充的信息 → `user_provided_context`
2. RAG 管线在响应时必须根据 `provenance_level` 调整语气（see Chapter 6）
3. 任何 chunk 的 `provenance_level` 都不能被降低（只能升级，不能降级）

## 5.5 confidence 取值范围与含义

| 区间 | 语义 | 触发条件 | 下游处理 |
|------|------|---------|---------|
| `[0.9, 1.0]` | 高置信 | 原始数据时间戳精确、说话人明确、内容完整 | 正常进入检索和响应 |
| `[0.7, 0.9)` | 中置信 | 时间戳推断但有依据、说话人未完全统一、内容有小段缺失 | 进入检索但响应中标注"置信度中等" |
| `[0.5, 0.7)` | 低置信 | 多处推断、说话人匿名化、内容经过大量清洗 | 进入检索但响应中必须标注不确定性；不支持作为唯一证据来源 |
| `[0.0, 0.5)` | 极低置信 | 关键信息严重缺失或矛盾 | 默认不进入检索；仅在有明确用户请求时展示并强标注 |

**confidence 计算公式**（v0.1 初版）：

```
confidence = w1 * timestamp_confidence
           + w2 * speaker_confidence
           + w3 * content_integrity
           + w4 * source_reliability

其中：
- timestamp_confidence: CERTAIN=1.0, INFERRED=0.7, UNCERTAIN=0.3
- speaker_confidence: normalized占比 / total_speakers
- content_integrity: 非FILTERED消息数 / 总消息数
- source_reliability: wechat_db=1.0, wechat_txt=0.85, email=0.9, diary=0.95, transcription=0.7, ocr=0.5
- w1=0.25, w2=0.15, w3=0.35, w4=0.25
```

**Trade-off**：confidence 是加权综合评分而非单一维度决定。理由：单独依赖某一维度（如只看时间戳精确度）会遗漏其他质量问题；加权方式虽然简化了真实情况，但 v0.1 阶段足以区分数据质量层级。后续版本应引入更细粒度的多维置信度。

## 5.6 字段级校验规则

| 字段 | 约束 | 校验方式 | 错误处理 |
|------|------|---------|---------|
| `chunk_id` | UUID v7 格式 | 正则 `^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$` | 拒绝入库 |
| `deceased_profile_id` | 必须存在于 deceased_profile 表 | FK 校验 | 拒绝入库 |
| `source_artifact_id` | 必须存在于 source_artifact 表 | FK 校验 | 拒绝入库 |
| `chunk_type` | 枚举值之一 | ENUM 校验 | 拒绝入库 |
| `speaker_set` | 非空数组，元素去重 | `len(set) > 0` | 拒绝入库 |
| `primary_speaker` | 必须在 speaker_set 中 | `primary_speaker in speaker_set` | 拒绝入库 |
| `timestamp_range.start` | 必须 ≤ `timestamp_range.end`（非 null 时） | 时间比较 | 警告，允许入库 |
| `source_spans` | 非空数组，`char_end > char_start`，ID 全部存在于 normalized_message | 逐条校验 | 拒绝入库 |
| `text_normalized` | 非空字符串，UTF-8 | `len(text_normalized.strip()) > 0` | 拒绝入库 |
| `text_original_refs` | 非空数组，每个 ref 的 ID 存在于 normalized_message | 逐条校验 | 警告，允许入库 |
| `semantic_labels` | label 非空，confidence 在 [0, 1] | 类型校验 | 过滤掉无效项 |
| `emotion_labels` | label 为枚举值，confidence 在 [0, 1] | 类型校验 | 过滤掉无效项 |
| `chunk_hash` | 64 字符十六进制 | 长度+字符校验，入库时重算对比 | 不一致则拒绝入库 |
| `provenance_level` | 枚举值之一 | ENUM 校验 | 拒绝入库 |
| `confidence` | 浮点数在 [0.0, 1.0] | 范围校验 | 拒绝入库 |

## 5.7 与 Chapter 4 DDL 的映射

| Schema 字段 | DDL 表.列 | 映射说明 |
|------------|----------|---------|
| `chunk_id` | `memory_chunk.id` | 直接映射 |
| `deceased_profile_id` | 通过 `source_artifact_id → source_artifact.deceased_profile_id` 间接关联 | Schema 中冗余存储，避免查询时多表 JOIN |
| `source_artifact_id` | `memory_chunk.source_artifact_id` | 直接映射 |
| `chunk_type` | `memory_chunk.chunk_type` | 直接映射 |
| `speaker_set` | `memory_chunk.metadata → JSON 字段 "speaker_set"` | 存储为 metadata JSON 字段 |
| `primary_speaker` | `memory_chunk.metadata → JSON 字段 "primary_speaker"` | 存储为 metadata JSON 字段 |
| `timestamp_range` | `memory_chunk.time_range_start / time_range_end` + `metadata.confidence` | 拆分为 DDL 两列 + 置信度子字段 |
| `source_spans` | `memory_chunk_span` 表 | 一对多关联 |
| `text_normalized` | `memory_chunk.content` | 直接映射 |
| `text_original_refs` | 通过 `memory_chunk_span → normalized_message.content` 反查 | 不单独存储，运行时从 span 映射反查 |
| `semantic_labels` | `memory_annotation(type=TOPIC)` | 一对多关联 |
| `emotion_labels` | `memory_annotation(type=SENTIMENT)` | 一对多关联 |
| `relationship_tags` | `memory_chunk.metadata → JSON 字段 "relationship_tags"` | 存储为 metadata JSON 字段 |
| `annotation_refs` | `memory_annotation.id` | 一对多关联 |
| `embedding_model` | `embedding_index_ref.model_name` | 直接映射 |
| `embedding_version` | `embedding_index_ref.model_version` | 直接映射 |
| `chunk_hash` | `memory_chunk.chunk_hash` | 直接映射 |
| `provenance_level` | `memory_chunk.metadata → JSON 字段 "provenance_level"` | 存储为 metadata JSON 字段 |
| `confidence` | `memory_chunk.metadata → JSON 字段 "confidence"` | 存储为 metadata JSON 字段 |

**Trade-off**：`speaker_set`、`primary_speaker`、`timestamp_range.confidence`、`provenance_level`、`confidence` 等字段存储在 `metadata` JSON 字段中而非独立列。理由：这些字段在 v0.1 阶段查询频率较低，不需要独立索引；JSON 字段减少了 DDL 变更频率；查询时由 `remnant-core` 负责反序列化和校验。

---

# Chapter 6: Claim-level Response Protocol

本章定义 Remnant 的确定性响应协议。核心原则：**系统不能只返回 response_text，而必须返回 claim-level provenance**——每个事实性断言必须可追溯到原始数据和证据。

## 6.1 设计原则

1. **No unsupported claims in final text**：最终呈现给用户的 `response_text` 中，不允许出现任何没有 claim 支撑的事实性陈述
2. **Granular provenance**：溯源粒度到 claim 级别，而非整条 response
3. **Transparent uncertainty**：不确定的信息必须显式标注限定词（"可能""似乎""根据有限记录"）
4. **Safety by default**：安全指令和拒绝策略嵌入响应结构，不是事后补丁

## 6.2 Response Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://remnant.app/schemas/response/v1",
  "title": "RemnantResponse",
  "description": "Remnant 确定性响应协议 — claim-level provenance",
  "type": "object",
  "required": [
    "response_id", "session_id", "relationship_scope_id",
    "deceased_profile_id", "response_text", "response_mode",
    "claims", "unsupported_claims", "safety_directive",
    "retrieval_trace_id", "created_at"
  ],
  "properties": {
    "response_id": {
      "type": "string",
      "format": "uuid",
      "description": "响应唯一标识符"
    },
    "session_id": {
      "type": "string",
      "format": "uuid",
      "description": "所属交互会话 ID"
    },
    "relationship_scope_id": {
      "type": "string",
      "format": "uuid",
      "description": "关系作用域 ID，确保该响应对应正确的亲属视角"
    },
    "deceased_profile_id": {
      "type": "string",
      "format": "uuid",
      "description": "逝者档案 ID"
    },
    "response_text": {
      "type": "string",
      "description": "最终呈现给用户的回答文本。每个事实性句子必须能映射到 claim_id。不包含任何 unsupported claim 的内容"
    },
    "response_mode": {
      "type": "string",
      "enum": ["evidence_grounded", "archive_search", "limited_interaction", "refusal", "safety_response"],
      "description": "响应模式，与最小记忆集等级对应。evidence_grounded=Level 2+; archive_search=Level 1; limited_interaction=Level 3; refusal=数据不足或安全拒绝; safety_response=触发安全策略"
    },
    "claims": {
      "type": "array",
      "items": { "$ref": "#/$defs/ClaimSchema" },
      "description": "本次响应中的所有事实声明，按出现顺序排列"
    },
    "unsupported_claims": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim_text", "rejection_reason"],
        "properties": {
          "claim_text": {
            "type": "string",
            "description": "被移除的 claim 原文"
          },
          "rejection_reason": {
            "type": "string",
            "enum": [
              "no_evidence",
              "insufficient_evidence",
              "contradicted_by_evidence",
              "safety_policy",
              "consent_withheld",
              "scope_violation"
            ],
            "description": "拒绝原因：no_evidence=无证据; insufficient_evidence=证据不足; contradicted_by_evidence=与证据矛盾; safety_policy=安全策略; consent_withheld=授权未授予; scope_violation=越权访问"
          }
        }
      },
      "description": "被移除的 unsupported claims，不在 response_text 中出现，但保留审计痕迹"
    },
    "safety_directive": {
      "type": "object",
      "required": ["level", "action"],
      "properties": {
        "level": {
          "type": "string",
          "enum": ["none", "caution", "warning", "intervention"],
          "description": "安全指令级别。none=无风险; caution=标注不确定性; warning=添加缓冲语; intervention=暂停并建议专业帮助"
        },
        "action": {
          "type": "string",
          "description": "执行的安全动作描述"
        },
        "buffer_text": {
          "type": "string",
          "description": "插入到 response_text 前后的缓冲语文本（如 '根据你提供的信息...'）"
        }
      },
      "description": "安全指令：嵌入响应的安全策略执行结果"
    },
    "retrieval_trace_id": {
      "type": "string",
      "format": "uuid",
      "description": "关联的检索追踪 ID，用于溯源整个检索和生成过程"
    },
    "created_at": {
      "type": "string",
      "format": "date-time",
      "description": "响应生成时间"
    }
  },
  "additionalProperties": false,
  "$defs": {
    "ClaimSchema": {
      "type": "object",
      "required": [
        "claim_id", "claim_text", "claim_type",
        "support_status", "confidence_score", "evidence"
      ],
      "properties": {
        "claim_id": {
          "type": "string",
          "format": "uuid",
          "description": "claim 唯一标识符"
        },
        "claim_text": {
          "type": "string",
          "description": "事实声明文本。如 '妈妈在 2024 年 3 月提到过想去西湖看看'"
        },
        "claim_type": {
          "type": "string",
          "enum": [
            "supported_memory",
            "inferred_but_supported",
            "user_provided_context",
            "unsupported_memory",
            "safety_response",
            "refusal"
          ],
          "description": "声明类型，详见 6.3"
        },
        "support_status": {
          "type": "string",
          "enum": [
            "fully_supported",
            "partially_supported",
            "unsupported",
            "contradicted",
            "insufficient_evidence"
          ],
          "description": "证据支撑状态，详见 6.4"
        },
        "confidence_score": {
          "type": "number",
          "minimum": 0.0,
          "maximum": 1.0,
          "description": "综合置信度评分。结合证据质量、数量、一致性计算"
        },
        "evidence": {
          "type": "array",
          "items": { "$ref": "#/$defs/EvidenceSchema" },
          "description": "支撑此 claim 的证据列表"
        },
        "rejection_reason": {
          "type": ["string", "null"],
          "description": "如果 claim_type 为 unsupported_memory、safety_response 或 refusal，记录具体原因"
        },
        "provenance_level": {
          "type": "string",
          "enum": ["primary_source", "derived_from_source", "inferred", "user_provided_context"],
          "description": "溯源等级，继承自支撑证据中 provenance_level 的最低值"
        }
      }
    },
    "EvidenceSchema": {
      "type": "object",
      "required": [
        "chunk_id", "source_artifact_id", "timestamp_range",
        "speaker", "quote_hash", "provenance_score"
      ],
      "properties": {
        "chunk_id": {
          "type": "string",
          "format": "uuid",
          "description": "关联的 memory_chunk ID"
        },
        "source_artifact_id": {
          "type": "string",
          "format": "uuid",
          "description": "溯源至原始数据来源文件"
        },
        "source_file_id": {
          "type": ["string", "null"],
          "format": "uuid",
          "description": "溯源至 source_artifact 的 ID（与 source_artifact_id 相同，冗余存储便于快速查询）"
        },
        "timestamp_range": {
          "type": "object",
          "required": ["start", "end"],
          "properties": {
            "start": { "type": "string", "format": "date-time" },
            "end": { "type": "string", "format": "date-time" }
          },
          "description": "证据覆盖的时间范围"
        },
        "source_span": {
          "type": "object",
          "description": "精确溯源到 chunk 内的文本片段",
          "properties": {
            "char_start": { "type": "integer", "minimum": 0 },
            "char_end": { "type": "integer", "minimum": 0 },
            "excerpt": {
              "type": "string",
              "description": "原文摘录，用于溯源展示"
            }
          }
        },
        "speaker": {
          "type": "string",
          "description": "证据的说话人（normalized 后）"
        },
        "quote_hash": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$",
          "description": "证据原文的 SHA-256 哈希，用于完整性校验和 tamper detection"
        },
        "provenance_score": {
          "type": "number",
          "minimum": 0.0,
          "maximum": 1.0,
          "description": "该证据的溯源可信度评分。primary_source=1.0, derived_from_source=0.8, inferred=0.5, user_provided_context=0.3"
        }
      }
    }
  }
}
```

## 6.3 claim_type 枚举

| 值 | 含义 | 证据要求 | 语气要求 | 在 response_text 中的表现 |
|---|---|---|---|---|
| `supported_memory` | 有充分原始数据支撑的记忆 | 至少 1 条 `primary_source` 或 `derived_from_source` 类型证据，`support_status = fully_supported` | 直接陈述，无需限定词 | "妈妈在2024年3月15日的微信中说想去看西湖" |
| `inferred_but_supported` | 由系统推断但有间接证据支撑 | 至少 1 条 `derived_from_source` 或 `inferred` 类型证据 | **必须使用限定词**："可能""似乎""根据记录推测" | "根据记录，妈妈似乎经常提到想去看西湖" |
| `user_provided_context` | 用户在对话中补充的信息（如家族口述历史） | 无原始数据证据，只有用户声明 | **必须标注来源**："根据你的描述""你提到过" | "你提到妈妈以前在杭州工作过" |
| `unsupported_memory` | 无证据支撑的断言 | evidence 数组为空或 `insufficient_evidence` | **不允许出现在 response_text 中** | 移除，不展示 |
| `safety_response` | 触发安全策略的响应 | 无需证据 | 安全说明 | "这个问题我暂时无法回答，建议和亲友沟通" |
| `refusal` | 因数据不足、授权未授予或 scope 违规而拒绝 | 无需证据 | 礼貌拒绝 | "目前的数据还不足以回答这个问题" |

**核心规则**：

1. **`unsupported_memory` 不能进入最终 `response_text`**：在 Claim Extraction → Claim-Evidence Alignment → Unsupported Claim Removal 流水线中被移除
2. **`inferred_but_supported` 必须显式降低语气**：限定词为硬性要求，不可省略
3. **`user_provided_context` 不能伪装成逝者原始记忆**：必须明确标注"你提到的""你描述的"
4. **`contradicted` 的 claim（`support_status = contradicted`）必须优先说明矛盾**：不允许忽略矛盾只呈现其中一面

## 6.4 support_status 枚举

| 值 | 含义 | 判定规则 | 对输出语气的影响 |
|---|---|---|---|
| `fully_supported` | 完全支撑 | ≥2 条 `provenance_score ≥ 0.8` 的证据，且证据间无矛盾 | 直接陈述 |
| `partially_supported` | 部分支撑 | 有证据但不够充分（仅1条证据，或 evidence 评分总和 < 阈值） | "根据有限的记录""在目前的数据中" |
| `unsupported` | 无支撑 | evidence 数组为空 | 不出现在 response_text 中 |
| `contradicted` | 被证伪 | 存在至少2条相互矛盾的证据条目 | 必须优先说明矛盾："记录中存在不同说法" |
| `insufficient_evidence` | 证据不足 | evidence 非空但 `provenance_score` 均 < 0.5 | "目前的数据还不足以确认这一点" |

## 6.5 Claim-Evidence 映射规则

### 6.5.1 映射算法

```
每个 claim 的 provenance_level = min(所有 evidence 的 provenance_level)
每个 claim 的 confidence_score = weighted_avg(evidence.provenance_score) * consistency_factor

其中：
- weighted_avg: 按 provenance_score 加权平均
- consistency_factor: 如果证据间无矛盾 = 1.0; 有矛盾 = 0.7; 严重矛盾 = 0.4
```

### 6.5.2 response_text 与 claim 映射

`response_text` 中的每个事实性句子必须标注对应的 `claim_id`。实现方式：

```
在 response_text 中使用行内标注格式：
"[妈妈在2024年3月提到想去西湖]{claim:c_001}。根据你的描述，她以前在杭州工作过{claim:c_002}。"

渲染层负责将 {claim:c_XXX} 标注转换为可交互的溯源链接。
```

**校验规则**：

1. response_text 中的每个 `{claim:c_XXX}` 标注必须在 `claims` 数组中有对应条目
2. `claims` 数组中 `support_status ∈ {fully_supported, partially_supported}` 的 claim 必须在 `response_text` 中出现
3. `unsupported_memory` 类型的 claim 不允许在 `response_text` 中出现
4. 如果 `safety_directive.level ≠ none`，`response_text` 前必须插入 `safety_directive.buffer_text`

## 6.6 Safety Directive 详解

| level | 触发条件 | action | buffer_text 示例 |
|-------|---------|--------|----------------|
| `none` | 无风险 | 无 | 无 |
| `caution` | 证据置信度 < 0.7 或 claim_type 含 `inferred_but_supported` | 标注不确定性 | "根据目前可用的记录…" |
| `warning` | 检索到 `grief_trigger` 标注的 chunk 或用户情绪偏低 | 添加缓冲语 | "回忆这些内容可能会带来一些感受。以下是根据记录整理的信息：" |
| `intervention` | 检测到情感依赖倾向、深夜长时间使用、自我伤害关键词 | 暂停对话并建议专业帮助 | "看起来你可能需要一些支持。建议联系专业的心理援助热线。以下资源可能有用：…" |

**Trade-off**：`intervention` 级别会中断用户体验，但这是 Anti-dependency 原则的硬性要求。理由：在这个应用场景下，用户的安全远比流畅体验重要。

## 6.7 完整响应示例

```json
{
  "response_id": "019a1b2c-3d4e-5f6g-7h8i-9j0k1l2m3n4",
  "session_id": "019a1b2c-0000-0000-0000-000000000001",
  "relationship_scope_id": "019a1b2c-1111-1111-1111-111111111111",
  "deceased_profile_id": "019a1b2c-2222-2222-2222-222222222222",
  "response_text": "根据微信记录，{妈妈在2024年3月15日提到想去西湖看看}{claim:c_001}。她当时说'春天的时候去应该很漂亮'。{根据你提到的，妈妈以前在杭州工作过}{claim:c_002}。",
  "response_mode": "evidence_grounded",
  "claims": [
    {
      "claim_id": "c_001",
      "claim_text": "妈妈在2024年3月15日提到想去西湖看看",
      "claim_type": "supported_memory",
      "support_status": "fully_supported",
      "confidence_score": 0.92,
      "evidence": [
        {
          "chunk_id": "019a1b2c-aaaa-bbbb-cccc-dddddddddddd",
          "source_artifact_id": "019a1b2c-eeee-ffff-gggg-hhhhhhhhhhhh",
          "source_file_id": "019a1b2c-eeee-ffff-gggg-hhhhhhhhhhhh",
          "timestamp_range": {
            "start": "2024-03-15T10:30:00Z",
            "end": "2024-03-15T10:32:00Z"
          },
          "source_span": {
            "char_start": 156,
            "char_end": 203,
            "excerpt": "[妈妈] 春天的时候去西湖应该很漂亮"
          },
          "speaker": "mother",
          "quote_hash": "a1b2c3d4e5f6...（64位SHA-256）",
          "provenance_score": 1.0
        }
      ],
      "rejection_reason": null,
      "provenance_level": "primary_source"
    },
    {
      "claim_id": "c_002",
      "claim_text": "妈妈以前在杭州工作过",
      "claim_type": "user_provided_context",
      "support_status": "partially_supported",
      "confidence_score": 0.3,
      "evidence": [],
      "rejection_reason": null,
      "provenance_level": "user_provided_context"
    }
  ],
  "unsupported_claims": [
    {
      "claim_text": "妈妈不喜欢做饭",
      "rejection_reason": "insufficient_evidence"
    },
    {
      "claim_text": "妈妈总是很开心",
      "rejection_reason": "contradicted_by_evidence"
    }
  ],
  "safety_directive": {
    "level": "caution",
    "action": "标注不确定性，因 claim c_002 为 user_provided_context",
    "buffer_text": "根据目前可用的记录——"
  },
  "retrieval_trace_id": "019a1b2c-rrrr-rrrr-rrrr-rrrrrrrrrrrr",
  "created_at": "2024-12-01T14:30:00Z"
}
```

---

# Chapter 7: Deterministic RAG Pipeline

本章定义 Remnant 的核心 RAG 检索、重排与溯源校验流程——16 步完全确定性流水线。核心原则：**LLM 不直接访问全库，只看经过 policy 和 retrieval 过滤的 evidence_pack；LLM 输出必须经过二次校验；最终 response 由 renderer 根据 claim 状态组装。**

## 7.1 Pipeline 总览

```
┌───────────────────────────────────────────────────────────────────┐
│                    Remnant Deterministic RAG Pipeline              │
│                                                                     │
│  Step 1:  Safety pre-check                                        │
│  Step 2:  Query classification                                     │
│  Step 3:  Query rewrite                                            │
│  Step 4:  Relationship scope filtering                            │
│  Step 5:  Hybrid retrieval (FTS5 + Vector)                        │
│  Step 6:  Time-aware retrieval                                    │
│  Step 7:  Speaker-aware retrieval                                 │
│  Step 8:  Rerank                                                  │
│  Step 9:  Evidence sufficiency check                              │
│  Step 10: Claim planning                                          │
│  Step 11: LLM generation (grounded prompt)                       │
│  Step 12: Claim extraction                                         │
│  Step 13: Claim-evidence alignment                                │
│  Step 14: Unsupported claim removal                               │
│  Step 15: Final response rendering                                │
│  Step 16: Audit logging                                           │
│                                                                     │
│  ★ LLM 只在 Step 3, 10, 11 出现 ★                               │
│  ★ 每步输入输出都有明确约束 ★                                   │
└───────────────────────────────────────────────────────────────────┘
```

## 7.2 Python 伪代码

### 7.2.1 主入口: answer_query

```python
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum
import hashlib
import json
from datetime import datetime

# ── 数据结构定义 ──

class ClaimType(str, Enum):
    SUPPORTED_MEMORY = "supported_memory"
    INFERRED_BUT_SUPPORTED = "inferred_but_supported"
    USER_PROVIDED_CONTEXT = "user_provided_context"
    UNSUPPORTED_MEMORY = "unsupported_memory"
    SAFETY_RESPONSE = "safety_response"
    REFUSAL = "refusal"

class SupportStatus(str, Enum):
    FULLY_SUPPORTED = "fully_supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"

@dataclass
class SessionContext:
    """交互会话上下文"""
    session_id: str
    relationship_scope_id: str
    deceased_profile_id: str
    conversation_history: List[dict]     # 最近的对话历史
    memory_set_level: int                # 最小记忆集等级 (0-4)
    safety_flags: List[str]              # 当前安全标记
    user_emotion_state: Optional[str]    # 用户当前情绪状态评估

@dataclass
class EvidenceItem:
    """证据条目"""
    chunk_id: str
    source_artifact_id: str
    timestamp_range: dict
    source_span: dict
    speaker: str
    quote_hash: str
    provenance_score: float
    provenance_level: str
    content_excerpt: str                 # chunk 中摘录的原文片段

@dataclass
class Claim:
    """事实声明"""
    claim_id: str
    claim_text: str
    claim_type: ClaimType
    support_status: SupportStatus
    confidence_score: float
    evidence: List[EvidenceItem]
    rejection_reason: Optional[str] = None
    provenance_level: str = "primary_source"

@dataclass
class EvidencePack:
    """经过过滤的证据包——LLM 可见的全部信息"""
    query: str
    chunks: List[dict]                   # 过滤后的 chunk 列表
    evidence_items: List[EvidenceItem]   # 证据条目列表
    retrieval_metadata: dict              # 检索元数据

@dataclass
class Response:
    """最终响应"""
    response_id: str
    session_id: str
    relationship_scope_id: str
    deceased_profile_id: str
    response_text: str
    response_mode: str
    claims: List[Claim]
    unsupported_claims: List[dict]
    safety_directive: dict
    retrieval_trace_id: str
    created_at: str


def answer_query(
    user_query: str,
    session_context: SessionContext,
) -> Response:
    """
    Remnant 确定性 RAG 主入口。
    
    输入:
      - user_query: 用户原始问题
      - session_context: 会话上下文（scope, 历史, 安全状态）
    
    输出:
      - Response: 完整的确定性响应（见 Chapter 6 Schema）
    
    约束:
      - LLM 不直接访问全库
      - 每个事实性断言必须有 claim 支撑
      - 所有数据访问限定 relationship_scope_id
    """
    trace_id = generate_uuid()
    
    # ── Step 1: Safety pre-check ──
    safety_directive = safety_pre_check(user_query, session_context)
    if safety_directive["level"] == "intervention":
        return _build_intervention_response(
            trace_id, session_context, safety_directive
        )
    
    # ── Step 2: Query classification ──
    query_class = classify_query(user_query, session_context)
    # query_class: {type: factual|emotional|meta|ambiguous, 
    #               time_references: [...], 
    #               target_speaker: str|None,
    #               intent: remember|search|chat|clarify}
    
    # ── Step 3: Query rewrite ──
    rewritten_query = rewrite_query(user_query, query_class, session_context)
    # LLM 将口语化/模糊的问题改写为检索友好的形式
    
    # ── Step 4: Relationship scope filtering ──
    scope_id = session_context.relationship_scope_id
    # 所有后续查询必须限定此 scope_id
    
    # ── Step 5-7: Hybrid + Time + Speaker retrieval ──
    candidates = retrieve_candidates(rewritten_query, scope_id, query_class)
    
    # ── Step 8: Rerank ──
    ranked = rerank_candidates(rewritten_query, candidates, query_class)
    
    # ── Step 9: Evidence sufficiency check ──
    sufficient, evidence_pack = check_evidence_sufficiency(
        user_query, ranked, session_context.memory_set_level
    )
    if not sufficient:
        return _build_insufficient_response(
            trace_id, session_context, query_class, evidence_pack
        )
    
    # ── Step 10: Claim planning ──
    claim_plan = plan_claims(user_query, evidence_pack, session_context)
    
    # ── Step 11: LLM generation ──
    llm_output = generate_grounded_response(
        user_query, evidence_pack, claim_plan, session_context
    )
    
    # ── Step 12: Claim extraction ──
    raw_claims = extract_claims(llm_output)
    
    # ── Step 13: Claim-evidence alignment ──
    aligned_claims = align_claims_to_evidence(raw_claims, evidence_pack)
    
    # ── Step 14: Unsupported claim removal ──
    valid_claims, removed_claims = remove_unsupported_claims(aligned_claims)
    
    # ── Step 15: Final response rendering ──
    response = render_response(
        valid_claims, removed_claims, safety_directive, 
        trace_id, session_context
    )
    
    # ── Step 16: Audit logging ──
    audit_log_response(trace_id, response, session_context)
    
    return response
```

### 7.2.2 Step 1: Safety Pre-check

```python
def safety_pre_check(
    query: str, 
    context: SessionContext
) -> dict:
    """
    安全预检：在进入 RAG 流水线之前检查安全风险。
    
    输入:
      - query: 用户原始问题
      - context: 会话上下文
    
    输出:
      - safety_directive: {level, action, buffer_text}
    
    约束:
      - 必须在所有其他步骤之前执行
      - intervention 级别直接返回，不进入后续步骤
      - 检测项使用时长、深夜活跃、情绪依赖、自我伤害关键词
    """
    level = "none"
    action = ""
    buffer_text = ""
    
    # 检测自我伤害关键词
    self_harm_keywords = [
        "不想活", "死", "自杀", "了结", "结束生命",
        "随ta去", "想跟着走"
    ]
    if any(kw in query for kw in self_harm_keywords):
        return {
            "level": "intervention",
            "action": "SELF_HARM_KEYWORD_DETECTED",
            "buffer_text": (
                "我注意到你的一些表达让我担心你的安全。"
                "如果你正在经历困难时刻，请考虑联系专业帮助：\n"
                "全国心理援助热线：400-161-9995\n"
                "北京心理危机研究与干预中心：010-82951332"
            )
        }
    
    # 检查反依赖熔断状态
    if "ANTI_DEPENDENCY_TRIGGER" in context.safety_flags:
        return {
            "level": "intervention",
            "action": "ANTI_DEPENDENCY_COOL_DOWN",
            "buffer_text": "你今天已经使用了一段时间，建议休息一下再回来。"
        }
    
    # 检测深夜使用 (22:00 - 06:00)
    current_hour = datetime.now().hour
    if current_hour >= 22 or current_hour < 6:
        if "LATE_NIGHT_USAGE" not in context.safety_flags:
            level = "warning"
            action = "LATE_NIGHT_CAUTION"
            buffer_text = "现在是深夜，回忆可能会带来更多感受。"
    
    # 检测情绪依赖
    if "EMOTIONAL_DISTRESS" in context.safety_flags:
        level = max(level, "caution") if level != "warning" else "warning"
        action = "EMOTIONAL_SUPPORT_CAUTION"
        buffer_text = "根据目前可用的记录——"
    
    # 检测查询中的情感风险
    grief_keywords = ["为什么离开", "好想ta", "如果能再见", "好痛苦"]
    if any(kw in query for kw in grief_keywords):
        if level == "none":
            level = "caution"
            action = "GRIEF_SENSITIVE_QUERY"
            buffer_text = "回忆这些内容可能会带来一些感受。以下是根据记录整理的信息："
    
    return {"level": level, "action": action, "buffer_text": buffer_text}
```

### 7.2.3 Step 2: Query Classification

```python
def classify_query(query: str, context: SessionContext) -> dict:
    """
    查询分类：确定查询类型和意图。
    
    输入:
      - query: 用户原始问题
      - context: 会话上下文
    
    输出:
      - {
          type: "factual" | "emotional" | "meta" | "ambiguous",
          time_references: ["2024年3月", "去年", ...],
          target_speaker: "mother" | "father" | None,
          intent: "remember" | "search" | "chat" | "clarify",
          emotional_tone: "neutral" | "sad" | "nostalgic" | "anxious" | None
        }
    
    约束:
      - 不使用 LLM，基于规则分类（v0.1 阶段）
      - 时间引用提取使用正则，不依赖 LLM
      - 说话人识别基于 relationship_scope 的配置
    """
    import re
    
    # 查询类型
    factual_patterns = [
        r'(什么时候|哪年|哪天|几点|在哪|在哪里的|说了什么|怎么说的|有没有说过)',
        r'(喜欢|不喜欢|爱吃什么|习惯|工作|学校)',
    ]
    emotional_patterns = [
        r'(好想|想念|怀念|好痛|难受|为什么离开|如果能)',
        r'(ta在|ta会|ta还是|好像还在)',
    ]
    meta_patterns = [
        r'(你能|你会|你是不是|你的数据|你学了|你能记住)',
    ]
    
    if any(re.search(p, query) for p in factual_patterns):
        query_type = "factual"
    elif any(re.search(p, query) for p in emotional_patterns):
        query_type = "emotional"
    elif any(re.search(p, query) for p in meta_patterns):
        query_type = "meta"
    else:
        query_type = "ambiguous"
    
    # 时间引用提取
    time_patterns = [
        (r'(\d{4}年\d{1,2}月)', "absolute_date"),
        (r'(去年|今年|前年|上个月|这个月)', "relative_date"),
        (r'(过年|春节|中秋|端午|生日)', "festival"),
    ]
    time_references = []
    for pattern, ref_type in time_patterns:
        matches = re.findall(pattern, query)
        time_references.extend([(m, ref_type) for m in matches])
    
    # 目标说话人
    target_speaker = None
    scope_config = get_scope_config(context.relationship_scope_id)
    for alias, speaker_id in scope_config.speaker_aliases.items():
        if alias in query:
            target_speaker = speaker_id
            break
    
    # 意图识别
    intent = "search"  # 默认
    if query_type == "meta":
        intent = "clarify"
    elif "帮我回忆" in query or "我想知道" in query:
        intent = "remember"
    elif len(query) < 5:
        intent = "chat"
    
    return {
        "type": query_type,
        "time_references": time_references,
        "target_speaker": target_speaker,
        "intent": intent,
        "emotional_tone": None  # v0.1 不做情绪分析，预留
    }
```

### 7.2.4 Steps 5-7: Hybrid Retrieval

```python
def retrieve_candidates(
    query: str,
    relationship_scope_id: str,
    query_class: dict,
    top_k: int = 20,
) -> List[dict]:
    """
    混合检索：FTS5 + Vector + Time + Speaker 联合检索。
    
    输入:
      - query: 改写后的查询
      - relationship_scope_id: 关系作用域 ID（核心隔离参数）
      - query_class: 查询分类结果
      - top_k: 返回候选数
    
    输出:
      - candidates: [{chunk, score, source, ...}] 候选 chunk 列表
    
    约束:
      - 所有查询必须限定 relationship_scope_id
      - 检索不等于授权：所有候选还需经过 consent 和 evidence 检查
      - 返回的 chunk 必须包含溯源信息
    """
    # Step 5: Hybrid retrieval (FTS5 + Vector)
    fts_results = fts5_search(
        query=query,
        scope_id=relationship_scope_id,
        top_k=top_k * 2,  # 多取一些，后续过滤
    )
    vector_results = vector_search(
        query_embedding=embed_query(query),
        scope_id=relationship_scope_id,
        top_k=top_k * 2,
    )
    
    # 合并去重（以 chunk_id 为 key）
    merged = {}
    for r in fts_results:
        merged[r["chunk_id"]] = {
            **r,
            "fts_score": r["score"],
            "vector_score": 0.0,
            "source": "fts",
        }
    for r in vector_results:
        if r["chunk_id"] in merged:
            merged[r["chunk_id"]]["vector_score"] = r["score"]
            merged[r["chunk_id"]]["source"] = "hybrid"
        else:
            merged[r["chunk_id"]] = {
                **r,
                "fts_score": 0.0,
                "vector_score": r["score"],
                "source": "vector",
            }
    
    candidates = list(merged.values())
    
    # Step 6: Time-aware retrieval
    if query_class.get("time_references"):
        time_refs = resolve_time_references(
            query_class["time_references"],
            scope_id=relationship_scope_id,
        )
        # 对时间相关的查询，提升时间匹配的 chunk 权重
        for c in candidates:
            chunk_start = parse_datetime(c.get("time_range_start"))
            chunk_end = parse_datetime(c.get("time_range_end"))
            time_boost = compute_time_boost(chunk_start, chunk_end, time_refs)
            c["time_boost"] = time_boost
            c["combined_score"] = (
                0.4 * normalize(c.get("fts_score", 0)) +
                0.4 * normalize(c.get("vector_score", 0)) +
                0.2 * time_boost
            )
    else:
        for c in candidates:
            c["time_boost"] = 0.0
            c["combined_score"] = (
                0.5 * normalize(c.get("fts_score", 0)) +
                0.5 * normalize(c.get("vector_score", 0))
            )
    
    # Step 7: Speaker-aware retrieval
    if query_class.get("target_speaker"):
        target = query_class["target_speaker"]
        for c in candidates:
            speaker_match = 1.0 if target in c.get("speaker_set", []) else 0.0
            c["speaker_boost"] = speaker_match * 0.15
            c["combined_score"] += c["speaker_boost"]
    
    # 过滤掉 provenance_level=user_provided_context 的 chunk
    # （这些不是原始数据，不应作为检索结果）
    candidates = [
        c for c in candidates
        if c.get("provenance_level") != "user_provided_context"
    ]
    
    # 过滤掉 confidence < 0.3 的 chunk
    candidates = [c for c in candidates if c.get("confidence", 0) >= 0.3]
    
    return candidates
```

### 7.2.5 Step 8: Rerank

```python
def rerank_candidates(
    query: str,
    candidates: List[dict],
    query_class: dict,
    top_k: int = 10,
) -> List[dict]:
    """
    重排序：对初步检索结果进行精细排序。
    
    输入:
      - query: 改写后的查询
      - candidates: 检索结果列表（已合并去重）
      - query_class: 查询分类
    
    输出:
      - ranked: 重排序后的候选列表，取 top_k
    
    约束:
      - 重排序不改变 provenance_level 和 scope 归属
      - 重排序保持原始排序（原始排序存在 retrieval_trace 中）
    """
    # 对每个候选计算综合排序分数
    for c in candidates:
        # 基础分：combined_score（来自 retrieval）
        base_score = c.get("combined_score", 0.0)
        
        # 相关性加成：与查询的语义相似度（使用 cross-encoder 或规则）
        relevance_boost = compute_relevance(query, c.get("content", ""))
        
        # 时间近因性加成：较近的对话片段略微提升
        recency_boost = compute_recency_boost(
            c.get("time_range_end"),
            reference_time=datetime.now(),
            decay_factor=0.95,
        )
        
        # 主题一致性加成
        topic_boost = compute_topic_boost(
            c.get("semantic_labels", []),
            query_class.get("intent", "search"),
        )
        
        # 多样性惩罚：避免连续多个相似 chunk
        # （在排序后处理）
        
        # provenance 加成：原始数据来源 > 推断 > 用户提供
        provenance_weights = {
            "primary_source": 1.0,
            "derived_from_source": 0.85,
            "inferred": 0.5,
        }
        provenance_weight = provenance_weights.get(
            c.get("provenance_level", "derived_from_source"), 0.7
        )
        
        # 综合分数
        c["rerank_score"] = (
            0.35 * base_score +
            0.30 * normalize(relevance_boost) +
            0.10 * recency_boost +
            0.10 * topic_boost +
            0.15 * provenance_weight
        )
    
    # 排序
    ranked = sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)
    
    # 多样性处理：MMR-like 策略避免连续相似
    diversified = _mmr_diversify(ranked, top_k=top_k, lambda_param=0.7)
    
    return diversified[:top_k]
```

### 7.2.6 Step 9: Evidence Sufficiency Check

```python
def check_evidence_sufficiency(
    query: str,
    ranked_chunks: List[dict],
    memory_set_level: int,
    min_evidence_count: int = 2,
    min_avg_provenance: float = 0.5,
) -> Tuple[bool, EvidencePack]:
    """
    证据充分性检查：判断检索到的证据是否足以支撑回答。
    
    输入:
      - query: 用户问题
      - ranked_chunks: 重排序后的候选列表
      - memory_set_level: 最小记忆集等级（0-4）
      - min_evidence_count: 最少证据条数
      - min_avg_provenance: 最低平均溯源分数
    
    输出:
      - (sufficient, evidence_pack)
        - sufficient: True 表示证据充分，可以继续生成
        - evidence_pack: 即使不充分也返回，用于生成降级响应
    
    约束:
      - memory_set_level < 2 时，不允许证据问答（Level 0-1 只能浏览/搜索）
      - 证据不足时生成降级响应，不编造答案
    """
    # 检查记忆集等级
    if memory_set_level < 2:
        return False, EvidencePack(
            query=query,
            chunks=[],
            evidence_items=[],
            retrieval_metadata={"reason": "INSUFFICIENT_MEMORY_SET_LEVEL", "level": memory_set_level}
        )
    
    # 过滤掉未经 consent 授权的 chunk
    consent_filtered = []
    for chunk in ranked_chunks:
        if check_consent(chunk["chunk_id"], chunk.get("source_artifact_id")):
            consent_filtered.append(chunk)
    
    # 对每个 chunk 执行证据验证
    evidence_items = []
    for chunk in consent_filtered:
        # 检查溯源链路完整性
        spans = get_chunk_spans(chunk["chunk_id"])
        
        for span in spans:
            ev = EvidenceItem(
                chunk_id=chunk["chunk_id"],
                source_artifact_id=chunk["source_artifact_id"],
                timestamp_range={
                    "start": chunk.get("time_range_start", ""),
                    "end": chunk.get("time_range_end", ""),
                },
                source_span={
                    "char_start": span["char_start"],
                    "char_end": span["char_end"],
                    "excerpt": extract_excerpt(chunk["content"], span["char_start"], span["char_end"]),
                },
                speaker=span["source_speaker"],
                quote_hash=compute_quote_hash(
                    chunk["content"][span["char_start"]:span["char_end"]]
                ),
                provenance_score=_compute_provenance_score(chunk),
                provenance_level=chunk.get("provenance_level", "primary_source"),
                content_excerpt=chunk["content"][:200],  # 前200字摘要
            )
            evidence_items.append(ev)
    
    # 计算充分性
    evidence_count = len(evidence_items)
    avg_provenance = (
        sum(e.provenance_score for e in evidence_items) / evidence_count
        if evidence_items else 0.0
    )
    
    # 检查 RISK 标注
    has_risk_annotation = any(
        has_risk_label(chunk["chunk_id"]) for chunk in consent_filtered
    )
    if has_risk_annotation:
        # 有风险标注的 chunk 需要额外确认，v0.1 先降低其权重
        evidence_items = [
            e for e in evidence_items
            if not has_risk_label(e.chunk_id)
        ] + [
            EvidenceItem(**{**e.__dict__, "provenance_score": e.provenance_score * 0.7})
            for e in evidence_items if has_risk_label(e.chunk_id)
        ]
    
    sufficient = (
        evidence_count >= min_evidence_count
        and avg_provenance >= min_avg_provenance
    )
    
    return sufficient, EvidencePack(
        query=query,
        chunks=consent_filtered,
        evidence_items=evidence_items,
        retrieval_metadata={
            "evidence_count": evidence_count,
            "avg_provenance": avg_provenance,
            "has_risk_annotation": has_risk_annotation,
            "sufficient": sufficient,
        }
    )
```

### 7.2.7 Step 10-11: Claim Planning & LLM Generation

```python
def plan_claims(
    query: str,
    evidence_pack: EvidencePack,
    context: SessionContext,
) -> List[dict]:
    """
    Claim 规划：在 LLM 生成前，预规划将要输出的 claim 结构。
    
    输入:
      - query: 用户问题
      - evidence_pack: 证据包
      - context: 会话上下文
    
    输出:
      - claim_plans: [{claim_type, claim_text_outline, evidence_refs}] 
        预规划的 claim 轮廓
    
    约束:
      - claim_plan 不包含具体文本，只包含类型和大纲
      - 用于后续 LLM 生成的指导约束
    """
    plans = []
    
    # 对每个证据条目，规划一个 supported_memory claim
    for evidence in evidence_pack.evidence_items[:5]:  # 最多5个主要claim
        if evidence.provenance_level in ("primary_source", "derived_from_source"):
            plans.append({
                "claim_type": "supported_memory",
                "claim_text_outline": f"基于原始记录的事实陈述",
                "evidence_refs": [evidence.chunk_id],
                "provenance_level": evidence.provenance_level,
            })
        elif evidence.provenance_level == "inferred":
            plans.append({
                "claim_type": "inferred_but_supported",
                "claim_text_outline": f"基于推断的事实陈述（需使用限定词）",
                "evidence_refs": [evidence.chunk_id],
                "provenance_level": evidence.provenance_level,
            })
    
    return plans


def generate_grounded_response(
    query: str,
    evidence_pack: EvidencePack,
    claim_plan: List[dict],
    context: SessionContext,
) -> str:
    """
    基于 evidence pack 生成约束性 LLM 输出。
    
    输入:
      - query: 用户问题
      - evidence_pack: LLM 可见的所有信息
      - claim_plan: 预规划的 claim 轮廓
      - context: 会话上下文
    
    输出:
      - llm_output: LLM 生成的原始文本（需后续校验）
    
    约束:
      - LLM 只能看到 evidence_pack 中的信息，不能访问全库
      - prompt 必须包含明确的约束指令
      - LLM 输出必须标注 claim（使用 {claim:N} 标记）
    """
    
    # 构建约束性 Prompt
    evidence_text = "\n\n".join([
        f"[证据 {i+1}] (来源: {e.provenance_level}, 说话人: {e.speaker})\n"
        f"时间范围: {e.timestamp_range['start']} ~ {e.timestamp_range['end']}\n"
        f"内容: {e.content_excerpt}\n"
        f"精确摘录: {e.source_span.get('excerpt', '')}"
        for i, e in enumerate(evidence_pack.evidence_items)
    ])
    
    claim_guidance = "\n".join([
        f"- Claim {i+1}: 类型={p['claim_type']}, "
        f"溯源={p['provenance_level']}"
        for i, p in enumerate(claim_plan)
    ])
    
    system_prompt = """你是 Remnant 系统的回答生成器。你的职责是基于提供的证据回答用户关于逝者的问题。

严格规则：
1. 你只能使用下方提供的证据来回答。不要使用任何外部知识或推理。
2. 每个事实性陈述必须用 {claim:N} 标记，N 从1开始递增。
3. 证据溯源等级为 "inferred" 的陈述必须使用限定词："可能""似乎""根据记录推测"。
4. 如果证据不足以回答问题，直接说明"根据目前的数据还不足以回答这个问题"。
5. 不要假装逝者仍然在线或真实存在。使用过去时态描述逝者的言行。
6. 不要做无证据的情绪承诺（如"ta一定很开心"）。
7. 如果证据间存在矛盾，明确指出矛盾。
8. 不要编造任何证据中没有的名字、事件或细节。"""
    
    user_prompt = f"""用户问题: {query}

可用证据:
{evidence_text}

预规划 Claim:
{claim_guidance}

请基于以上证据生成回答。每个事实性陈述用 {{claim:N}} 标注。"""
    
    llm_output = llm_provider.complete(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.3,  # 低温度，减少幻觉
        max_tokens=1024,
    )
    
    return llm_output
```

### 7.2.8 Steps 12-14: Claim Extraction, Alignment, Removal

```python
import re

def extract_claims(llm_output: str) -> List[dict]:
    """
    从 LLM 输出中提取结构化 claim。
    
    输入:
      - llm_output: LLM 生成的原始文本（含 {claim:N} 标记）
    
    输出:
      - raw_claims: [{claim_id, claim_text, claim_number, full_text}]
        提取的 claim 列表
    
    约束:
      - 必须能映射 response_text 中的每个事实性句子到 claim
      - 提取失败的部分标记为 uncategorized
    """
    raw_claims = []
    # 匹配 {claim:N} 标记
    claim_pattern = r'\{claim:(\d+)\}'
    
    # 按句号分割文本，为每个句子分配 claim 标记
    sentences = re.split(r'[。！？\n]', llm_output)
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        
        # 查找句子中的 claim 标记
        claims_in_sentence = re.findall(claim_pattern, sentence)
        
        if claims_in_sentence:
            for claim_num in claims_in_sentence:
                # 移除标记文本
                clean_text = re.sub(claim_pattern, '', sentence).strip()
                raw_claims.append({
                    "claim_id": f"c_{claim_num}",
                    "claim_text": clean_text,
                    "claim_number": int(claim_num),
                })
        else:
            # 没有 claim 标记的句子——需要审查
            # 事实性句子但无标记的，标记为 uncategorized
            if _is_factual_sentence(sentence):
                raw_claims.append({
                    "claim_id": f"c_uncat_{len(raw_claims)}",
                    "claim_text": sentence,
                    "claim_number": -1,  # uncategorized
                })
    
    return raw_claims


def align_claims_to_evidence(
    claims: List[dict],
    evidence_pack: EvidencePack,
) -> List[Claim]:
    """
    将提取的 claim 与证据对齐，判定每个 claim 的支撑状态。
    
    输入:
      - claims: 提取的 claim 列表
      - evidence_pack: 证据包
    
    输出:
      - aligned_claims: 带支撑状态的 Claim 列表
    
    约束:
      - 每个 claim 必须有 support_status
      - provenance_level 取所有 evidence 的最低值
      - 任何无法找到对应证据的 claim 标记为 unsupported
    """
    aligned = []
    
    for claim_data in claims:
        # 尝试将 claim 文本与证据匹配
        matching_evidence = _match_claim_to_evidence(
            claim_data["claim_text"], evidence_pack
        )
        
        if not matching_evidence:
            # 没有匹配的证据——可能是 LLM 编造的
            claim = Claim(
                claim_id=claim_data["claim_id"],
                claim_text=claim_data["claim_text"],
                claim_type=ClaimType.UNSUPPORTED_MEMORY,
                support_status=SupportStatus.UNSUPPORTED,
                confidence_score=0.0,
                evidence=[],
                rejection_reason="no_evidence",
            )
        elif len(matching_evidence) == 1 and matching_evidence[0].provenance_score < 0.5:
            # 仅有低质量证据
            claim = Claim(
                claim_id=claim_data["claim_id"],
                claim_text=claim_data["claim_text"],
                claim_type=ClaimType.INFERRED_BUT_SUPPORTED,
                support_status=SupportStatus.INSUFFICIENT_EVIDENCE,
                confidence_score=matching_evidence[0].provenance_score * 0.7,
                evidence=matching_evidence,
                provenance_level=min(e.provenance_level for e in matching_evidence),
            )
        else:
            # 有充分证据
            # 检查证据间是否存在矛盾
            has_contradiction = _check_contradiction(matching_evidence)
            
            if has_contradiction:
                support_status = SupportStatus.CONTRADICTED
                claim_type = ClaimType.INFERRED_BUT_SUPPORTED
                confidence = 0.4
            else:
                # 计算综合置信度
                avg_prov = sum(e.provenance_score for e in matching_evidence) / len(matching_evidence)
                if avg_prov >= 0.8 and len(matching_evidence) >= 2:
                    support_status = SupportStatus.FULLY_SUPPORTED
                    claim_type = ClaimType.SUPPORTED_MEMORY
                    confidence = min(avg_prov, 0.95)
                elif avg_prov >= 0.5:
                    support_status = SupportStatus.PARTIALLY_SUPPORTED
                    claim_type = ClaimType.SUPPORTED_MEMORY
                    confidence = avg_prov * 0.85
                else:
                    support_status = SupportStatus.INSUFFICIENT_EVIDENCE
                    claim_type = ClaimType.INFERRED_BUT_SUPPORTED
                    confidence = avg_prov * 0.7
            
            claim = Claim(
                claim_id=claim_data["claim_id"],
                claim_text=claim_data["claim_text"],
                claim_type=claim_type,
                support_status=support_status,
                confidence_score=confidence,
                evidence=matching_evidence,
                provenance_level=min(e.provenance_level for e in matching_evidence),
            )
        
        aligned.append(claim)
    
    return aligned


def remove_unsupported_claims(
    claims: List[Claim],
) -> Tuple[List[Claim], List[dict]]:
    """
    移除不支持的 claim，返回有效 claim 列表和被移除的 claim 列表。
    
    输入:
      - claims: 对齐后的 claim 列表
    
    输出:
      - (valid_claims, removed_claims)
    
    约束:
      - unsupported_memory 类型的 claim 不允许出现在 response_text 中
      - contradicted 的 claim 如果未在 response 中说明矛盾，也应移除
      - safety_response 和 refusal 类型特殊处理
    """
    valid = []
    removed = []
    
    for claim in claims:
        if claim.claim_type == ClaimType.UNSUPPORTED_MEMORY:
            # 无证据——必须移除
            removed.append({
                "claim_text": claim.claim_text,
                "rejection_reason": "no_evidence" 
                    if not claim.evidence else "insufficient_evidence",
            })
        elif claim.claim_type == ClaimType.SAFETY_RESPONSE:
            # 安全响应——直接保留
            valid.append(claim)
        elif claim.claim_type == ClaimType.REFUSAL:
            # 拒绝响应——直接保留
            valid.append(claim)
        elif claim.support_status == SupportStatus.CONTRADICTED:
            # 矛盾——保留但要求在 response 中明确矛盾
            # 如果 claim_text 中没有提到矛盾，标记需要补充
            if "矛盾" not in claim.claim_text and "不同说法" not in claim.claim_text:
                claim.claim_text = f"（注意：记录中存在不同说法）{claim.claim_text}"
            valid.append(claim)
        elif claim.support_status == SupportStatus.INSUFFICIENT_EVIDENCE:
            # 证据不足——要求使用限定词
            if claim.claim_type == ClaimType.INFERRED_BUT_SUPPORTED:
                # 已限定——保留但降低置信度
                valid.append(claim)
            else:
                # 未限定——移除
                removed.append({
                    "claim_text": claim.claim_text,
                    "rejection_reason": "insufficient_evidence",
                })
        else:
            # fully_supported 或 partially_supported——保留
            valid.append(claim)
    
    return valid, removed
```

### 7.2.9 Step 15: Render Response

```python
def render_response(
    valid_claims: List[Claim],
    removed_claims: List[dict],
    safety_directive: dict,
    trace_id: str,
    context: SessionContext,
) -> Response:
    """
    渲染最终响应：根据 claim 状态组装 response_text。
    
    输入:
      - valid_claims: 经过校验的有效 claim 列表
      - removed_claims: 被移除的 claim 列表
      - safety_directive: 安全指令
      - trace_id: 检索追踪 ID
      - context: 会话上下文
    
    输出:
      - Response: 完整的确定性响应
    
    约束:
      - response_text 中的每个事实性句子必须能映射到 claim_id
      - 渲染过程不添加任何不在 claim 中的信息
      - inferred_but_supported 必须使用限定词
      - user_provided_context 必须标注来源
    """
    # 构建 response_text
    parts = []
    
    # 插入安全缓冲语
    if safety_directive.get("buffer_text"):
        parts.append(safety_directive["buffer_text"])
    
    # 按 claim 顺序组装
    for claim in valid_claims:
        text = claim.claim_text
        
        # 根据类型添加标注
        if claim.claim_type == ClaimType.INFERRED_BUT_SUPPORTED:
            # 确保有限定词
            if not any(w in text for w in ["可能", "似乎", "推测", "根据记录", "看起来"]):
                text = f"根据记录推测，{text}"
        
        elif claim.claim_type == ClaimType.USER_PROVIDED_CONTEXT:
            text = f"你提到的——{text}"
        
        elif claim.claim_type == ClaimType.SAFETY_RESPONSE:
            # 安全响应直接输出，不标注来源
            parts.append(text)
            continue
        
        elif claim.claim_type == ClaimType.REFUSAL:
            parts.append(text)
            continue
        
        # 添加溯源标注
        annotated = f"{{{text}}}{{claim:{claim.claim_id}}}"
        parts.append(annotated)
    
    # 添加证据不足说明（如果有被移除的 claim）
    if removed_claims:
        insufficient_topics = [c["claim_text"] for c in removed_claims 
                              if c["rejection_reason"] == "insufficient_evidence"]
        if insufficient_topics:
            note = "关于你提到的某些方面，目前的数据还不足以给出确切回答。"
            parts.append(note)
    
    # 确定响应模式
    if context.memory_set_level < 2:
        response_mode = "archive_search"
    elif any(c.claim_type == ClaimType.SAFETY_RESPONSE for c in valid_claims):
        response_mode = "safety_response"
    elif any(c.claim_type == ClaimType.REFUSAL for c in valid_claims):
        response_mode = "refusal"
    elif context.memory_set_level >= 3:
        response_mode = "limited_interaction"
    else:
        response_mode = "evidence_grounded"
    
    return Response(
        response_id=generate_uuid(),
        session_id=context.session_id,
        relationship_scope_id=context.relationship_scope_id,
        deceased_profile_id=context.deceased_profile_id,
        response_text="。".join(parts),
        response_mode=response_mode,
        claims=valid_claims,
        unsupported_claims=removed_claims,
        safety_directive=safety_directive,
        retrieval_trace_id=trace_id,
        created_at=datetime.utcnow().isoformat() + "Z",
    )
```

### 7.2.10 Step 16: Audit Logging

```python
def audit_log_response(
    trace_id: str,
    response: Response,
    context: SessionContext,
) -> None:
    """
    审计日志：记录完整的查询和响应过程。
    
    输入:
      - trace_id: 检索追踪 ID
      - response: 最终响应
      - context: 会话上下文
    
    约束:
      - 审计日志 APPEND ONLY
      - 即使数据被销毁，审计日志保留（内容标记 REDACTED）
    """
    audit_entry = {
        "trace_id": trace_id,
        "session_id": context.session_id,
        "scope_id": context.relationship_scope_id,
        "response_id": response.response_id,
        "claims_count": len(response.claims),
        "unsupported_count": len(response.unsupported_claims),
        "safety_level": response.safety_directive.get("level", "none"),
        "response_mode": response.response_mode,
        "model_used": "qwen2.5-7b",  # v0.1 固定
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    
    # 写入审计日志
    store.append_audit_log(
        action="DATA_QUERY",
        actor="system",
        target_type="response",
        target_id=response.response_id,
        detail=json.dumps(audit_entry, ensure_ascii=False),
        scope_id=context.relationship_scope_id,
    )
```

## 7.3 Pipeline 数据流图

```
User Query
    │
    ▼
┌─────────────────── Step 1 ────────────────────┐
│  Safety Pre-check                              │
│  → intervention → 直接返回安全响应              │
│  → warning/caution → 记录, 继续               │
│  → none → 继续                                │
└──────────────────┬─────────────────────────────┘
                   │
    ▼
┌─────────────────── Step 2 ────────────────────┐
│  Query Classification                          │
│  → type: factual | emotional | meta | ambiguous│
│  → time_refs, target_speaker, intent            │
└──────────────────┬─────────────────────────────┘
                   │
    ▼
┌─────────────────── Step 3 ────────────────────┐
│  Query Rewrite (LLM)                           │
│  口语化 → 检索友好的形式                        │
└──────────────────┬─────────────────────────────┘
                   │
    ▼
┌─────────────────── Step 4 ────────────────────┐
│  Relationship Scope Filtering                  │
│  所有后续查询限定 scope_id                      │
└──────────────────┬─────────────────────────────┘
                   │
    ▼
┌────────── Step 5-7 ───────────────────────────┐
│  FTS5 ─┐                                       │
│         ├─ 合并去重 ─→ Time-aware ─→ Speaker  │
│  Vec ──┘                         Boost          │
│                                                 │
│  ★ WHERE relationship_scope_id = :scope_id ★   │
└──────────────────┬──────────────────────────────┘
                   │
    ▼
┌─────────────────── Step 8 ────────────────────┐
│  Rerank                                        │
│  综合: 相关性 + 时间 + 主题 + provenance        │
│  MMR 多样性去重                                 │
└──────────────────┬─────────────────────────────┘
                   │
    ▼
┌─────────────────── Step 9 ────────────────────┐
│  Evidence Sufficiency Check                    │
│  → 证据不足 → 降级响应                          │
│  → 证据充分 → 继续                             │
│                                                │
│  ★ consent 过滤 ★                              │
│  ★ RISK 标注降权 ★                             │
└──────────────────┬─────────────────────────────┘
                   │
    ▼
┌─────────────────── Step 10 ───────────────────┐
│  Claim Planning                                │
│  预规划 claim 类型和大纲                        │
└──────────────────┬─────────────────────────────┘
                   │
    ▼
┌─────────────────── Step 11 ───────────────────┐
│  LLM Generation (Grounded Prompt)              │
│  ★ LLM 只看 evidence_pack ★                   │
│  ★ 输出含 {claim:N} 标记 ★                     │
└──────────────────┬─────────────────────────────┘
                   │
    ▼
┌─────────────────── Step 12 ───────────────────┐
│  Claim Extraction                              │
│  从 LLM 输出中提取结构化 claim                  │
└──────────────────┬─────────────────────────────┘
                   │
    ▼
┌─────────────────── Step 13 ───────────────────┐
│  Claim-Evidence Alignment                      │
│  每个 claim 绑定到具体证据                      │
│  判定 support_status                            │
└──────────────────┬─────────────────────────────┘
                   │
    ▼
┌─────────────────── Step 14 ───────────────────┐
│  Unsupported Claim Removal                     │
│  → 移除无证据 claim                             │
│  → 移除被矛盾 claim（或标注矛盾）               │
│  → 限定 inferred_but_supported 语气             │
└──────────────────┬─────────────────────────────┘
                   │
    ▼
┌─────────────────── Step 15 ───────────────────┐
│  Final Response Rendering                      │
│  组装 response_text                             │
│  添加溯源链接 {claim:xxx}                        │
│  插入安全缓冲语                                 │
└──────────────────┬─────────────────────────────┘
                   │
    ▼
┌─────────────────── Step 16 ───────────────────┐
│  Audit Logging                                 │
│  APPEND ONLY, 不可修改                          │
└─────────────────────────────────────────────────┘
```

## 7.4 关键约束总结

| 约束 | 位置 | 说明 |
|------|------|------|
| LLM 不可访问全库 | Step 11 | LLM 只接收 evidence_pack，不知道全库内容 |
| 所有查询限定 scope | Step 4 | WHERE relationship_scope_id = :scope_id |
| 无证据不回答 | Step 9, 14 | unsupported claim 不进入 response_text |
| LLM 输出二次校验 | Step 12-14 | LLM 输出必须经过提取、对齐、移除三步校验 |
| 推断必须限定 | Step 14 | inferred_but_supported 必须使用限定词 |
| 用户信息标注来源 | Step 15 | user_provided_context 必须标注"你提到的" |
| 安全默认执行 | Step 1 | 检测到风险直接返回，不进入后续步骤 |
| 审计全程覆盖 | Step 16 | 每次查询完整记录 |

---

# Chapter 8: Minimum Viable Memory Set

本章定义 Remnant 的"最小可用记忆集"（Minimum Viable Memory Set, MVMS）评估标准。系统必须判断数据是否足以支持交互，并在数据不足时进行安全降级。

## 8.1 设计原则

1. **Data sufficiency is a prerequisite, not a luxury**：没有足够数据就不提供问答功能，这不是 bug 而是安全特性
2. **Graceful degradation**：数据不足时不是功能崩溃，而是渐进降级到更安全的能力等级
3. **Honest about limitations**：明确告知用户当前数据能支持什么、不能支持什么
4. **No false personality**：即使数据充足，也不能声称"复刻"了逝者人格

## 8.2 评分维度（10 维度）

每个维度独立评分，最终等级取所有维度的最低满足等级。

| # | 维度 | 计算方式 | 最低阈值(Level 2) | 说明 |
|---|------|---------|------------------|------|
| 1 | `total_messages` | 归一化后的消息总数 | ≥ 200 条 | 原始消息总量（包括已过滤的） |
| 2 | `deceased_authored_messages` | 逝者本人发出的消息数 | ≥ 100 条 | 逝者是核心信息来源，数量不足无法回答大部分问题 |
| 3 | `active_days` | 逝者有消息的不同天数 | ≥ 30 天 | 少于30天的时间跨度难以反映长期行为模式 |
| 4 | `time_span_months` | 最早到最晚消息的月数 | ≥ 3 个月 | 时间跨度太短无法反映习惯、偏好等稳定特征 |
| 5 | `relationship_coverage` | 涉及的关系类型数 / 总关系类型 | ≥ 0.3 | 关系多样性不足会导致回答偏向单一视角 |
| 6 | `topic_diversity` | 语义标注去重后的主题标签数 | ≥ 5 个 | 主题太少无法支撑多样化的问答 |
| 7 | `first_person_density` | 包含第一人称代词的逝者消息占比 | ≥ 0.15 | 第一人称表达直接反映逝者的想法和感受 |
| 8 | `emotional_expression_density` | 有情感标注（非 neutral）的 chunk 占比 | ≥ 0.1 | 情感表达密度影响系统对情绪相关问题的回答能力 |
| 9 | `source_diversity` | 不同 source_artifact 的类型数 | ≥ 1 种 | 至少有一种数据来源 |
| 10 | `contradiction_rate` | 内部矛盾的 evidence 对数 / 总 evidence 对数 | ≤ 0.2 | 矛盾率过高导致回答不可靠 |

### 计算公式

```python
@dataclass
class MemorySetScore:
    """最小记忆集评分结果"""
    total_messages: int
    deceased_authored_messages: int
    active_days: int
    time_span_months: float
    relationship_coverage: float
    topic_diversity: int
    first_person_density: float
    emotional_expression_density: float
    source_diversity: int
    contradiction_rate: float
    
    computed_at: str       # ISO 8601
    deceased_profile_id: str


def compute_memory_set_score(
    deceased_profile_id: str,
    scope_id: str,
    store: RemnantStore,
) -> MemorySetScore:
    """
    计算最小记忆集评分。
    
    所有统计限定 scope_id 对应的数据范围。
    """
    # total_messages: 当前 scope 下所有 normalized_message 总数
    total_messages = store.count_normalized_messages(
        scope_id=scope_id, status="CLEANED"
    )
    
    # deceased_authored_messages: 逝者本人发出的消息数
    profile = store.get_deceased_profile(deceased_profile_id)
    deceased_speakers = store.get_speaker_aliases(scope_id).get(
        profile.name, [profile.name]
    )
    deceased_authored_messages = store.count_messages_by_speakers(
        scope_id=scope_id, speakers=deceased_speakers, status="CLEANED"
    )
    
    # active_days: 逝者有消息的不同天数
    active_days = store.count_distinct_active_days(
        scope_id=scope_id, speakers=deceased_speakers
    )
    
    # time_span_months: 最早到最晚消息的月数
    date_range = store.get_date_range(scope_id=scope_id)
    if date_range:
        time_span_months = (
            (date_range["end"] - date_range["start"]).days / 30.44
        )
    else:
        time_span_months = 0.0
    
    # relationship_coverage: 涉及的关系类型数 / 预设关系类型数
    known_relationship_types = {
        "parent_child", "spouse", "sibling", 
        "friend", "colleague", "mentor"
    }
    present_relationships = store.get_present_relationship_types(scope_id=scope_id)
    relationship_coverage = len(present_relationships & known_relationship_types) / len(known_relationship_types)
    
    # topic_diversity: 语义标注去重后的主题标签数
    topic_labels = store.get_distinct_topic_labels(scope_id=scope_id)
    topic_diversity = len(topic_labels)
    
    # first_person_density: 包含第一人称代词的逝者消息占比
    first_person_keywords = {"我", "我们", "咱们", "俺", "本人"}
    deceased_messages = store.get_messages_by_speakers(
        scope_id=scope_id, speakers=deceased_speakers, limit=10000
    )
    first_person_count = sum(
        1 for msg in deceased_messages
        if any(kw in msg.content for kw in first_person_keywords)
    )
    first_person_density = (
        first_person_count / max(deceased_authored_messages, 1)
    )
    
    # emotional_expression_density: 有情感标注（非 neutral）的 chunk 占比
    total_chunks = store.count_chunks(scope_id=scope_id, status="ACTIVE")
    emotional_chunks = store.count_chunks_with_emotion_label(
        scope_id=scope_id, exclude_neutral=True
    )
    emotional_expression_density = emotional_chunks / max(total_chunks, 1)
    
    # source_diversity: 不同 source_artifact 的类型数
    source_types = store.get_distinct_source_types(deceased_profile_id=deceased_profile_id)
    source_diversity = len(source_types)
    
    # contradiction_rate: 内部矛盾率
    # v0.1 简化：统计情感标注矛盾的 chunk 对占比
    contradiction_rate = store.compute_contradiction_rate(scope_id=scope_id)
    
    return MemorySetScore(
        total_messages=total_messages,
        deceased_authored_messages=deceased_authored_messages,
        active_days=active_days,
        time_span_months=time_span_months,
        relationship_coverage=relationship_coverage,
        topic_diversity=topic_diversity,
        first_person_density=first_person_density,
        emotional_expression_density=emotional_expression_density,
        source_diversity=source_diversity,
        contradiction_rate=contradiction_rate,
        computed_at=datetime.utcnow().isoformat() + "Z",
        deceased_profile_id=deceased_profile_id,
    )
```

## 8.3 五级分级标准

### Level 0: Insufficient Data（数据不足）

**满足条件**：任一核心维度（total_messages < 50 或 deceased_authored_messages < 20）低于最低阈值。

**允许**：
- ✅ 导入和浏览数据
- ✅ 查看原始消息（按时间线浏览）
- ✅ 查看数据统计（消息数、时间跨度、说话人等）
- ✅ 手动添加更多数据源

**不允许**：
- ❌ 任何形式的问答交互
- ❌ 全文搜索（数据太少，搜索体验极差）
- ❌ 任何 LLM 生成的响应
- ❌ 模拟逝者语气

**系统行为**：
```
系统提示："目前导入的数据量还不足以支持对话或搜索功能。
请继续添加更多数据源（如聊天记录、邮件、日记等），
当数据达到基本要求后，相关功能将自动解锁。"
```

### Level 1: Archive Search Only（仅归档搜索）

**满足条件**：
- total_messages ≥ 50 且 deceased_authored_messages ≥ 20
- active_days ≥ 7
- time_span_months ≥ 1
- source_diversity ≥ 1

**允许**：
- ✅ Level 0 的所有功能
- ✅ 全文搜索（FTS5）
- ✅ 按时间、说话人、关键词筛选
- ✅ 搜索结果高亮和原文展示
- ✅ 溯源到原始数据文件

**不允许**：
- ❌ 任何 LLM 生成的问答响应
- ❌ 语义搜索（向量搜索）
- ❌ 情感分析、主题标注
- ❌ 模拟逝者语气

**系统行为**：
```
用户："妈妈说过什么关于旅行的话？"
系统：执行 FTS5 搜索 → 返回原文匹配结果列表
      不做 LLM 生成，只做搜索结果展示
```

### Level 2: Evidence-grounded Q&A（证据问答）

**满足条件**：
- total_messages ≥ 200
- deceased_authored_messages ≥ 100
- active_days ≥ 30
- time_span_months ≥ 3
- topic_diversity ≥ 5
- first_person_density ≥ 0.15
- emotional_expression_density ≥ 0.1
- contradiction_rate ≤ 0.2

**允许**：
- ✅ Level 1 的所有功能
- ✅ 向量语义搜索
- ✅ 完整 RAG 流水线（16步）
- ✅ Claim-level 溯源响应
- ✅ 所有 claim_type（supported_memory, inferred_but_supported, user_provided_context）
- ✅ 情感标注、主题标注

**不允许**：
- ❌ 有限角色互动（不能模拟逝者语气）
- ❌ 主动发起对话话题
- ❌ 声称了解逝者的"内心想法"
- ❌ 生成逝者"会说什么"的回答

**系统行为**：
```
用户："妈妈喜欢吃什么？"
系统：完整 RAG 流水线 → 返回 claim-level 溯源响应
      "根据记录，妈妈在2024年3月提到喜欢吃鱼{claim:c_001}。"
      每个事实性陈述有溯源链接。
```

### Level 3: Limited Memory Interaction（有限记忆互动）

**满足条件**：
- Level 2 的所有条件
- total_messages ≥ 500
- deceased_authored_messages ≥ 300
- active_days ≥ 60
- time_span_months ≥ 6
- relationship_coverage ≥ 0.3
- topic_diversity ≥ 10

**允许**：
- ✅ Level 2 的所有功能
- ✅ 有限的角色模拟（仅限逝者的措辞风格和常用表达，不模拟思想）
- ✅ 基于记忆的话题推荐（"你想了解ta关于XX的回忆吗？"）
- ✅ 时间线摘要生成

**不允许**：
- ❌ 声称"复刻"或"还原"逝者人格
- ❌ 模拟逝者对未记录话题的意见
- ❌ 生成逝者对未来的"预测"
- ❌ 声称系统"理解"逝者的想法
- ❌ 无限度的拟人化交互

**系统行为**：
```
用户："妈妈会怎么形容西湖？"
系统：基于记录的措辞风格生成回答，但必须标注：
      "根据记录中妈妈的表达风格推测，ta可能会这样说……
      需要注意，这只是基于有限记录的风格模拟，
      不能代表ta的真实想法。{claim:c_001}"
```

**强制规则**：

1. 所有 Level 3 互动必须在响应开头标注：`"以下内容基于ta在记录中的表达风格推测，不代表ta的真实想法。"`
2. 回答长度不超过 Level 2 回答的 1.5 倍
3. 每 5 轮对话自动插入反依赖提示：`"你已经和这个记录交互了一段时间，建议休息一下。"`
4. 不得对敏感话题（遗嘱、遗产、法律声明）提供模拟回答

### Level 4: Rich Memory Map（丰富记忆地图）

**满足条件**：
- Level 3 的所有条件
- total_messages ≥ 2000
- deceased_authored_messages ≥ 1000
- active_days ≥ 180
- time_span_months ≥ 12
- relationship_coverage ≥ 0.5
- topic_diversity ≥ 20
- source_diversity ≥ 2

**允许**：
- ✅ Level 3 的所有功能
- ✅ 记忆地图可视化（时间线、关系网络、主题图谱）
- ✅ 更完整的长周期模式识别（生活规律、习惯、偏好变化）
- ✅ 多数据源交叉验证

**绝对不允许**：
- ❌ 声称人格复刻或灵魂延续
- ❌ 宣称系统"认识"逝者
- ❌ 暗示逝者"还活着"或"在线"
- ❌ 无条件承诺"ta一定会这样说"
- ❌ 声音克隆（v0.1 默认禁用）

**系统声明（每次 Level 4 会话开始必须展示）**：
```
"Remnant 是一个基于记录的回忆辅助工具。它帮助你从逝者的真实文字
记录中整理和回溯记忆，但不会、也不能复刻一个人的人格或思想。
所有回答都基于原始数据和证据，系统不会模拟逝者的意识或意志。"
```

## 8.4 分级判别算法

```python
def determine_memory_set_level(score: MemorySetScore) -> int:
    """
    根据评分维度确定最小记忆集等级。
    取所有维度的最低满足等级。
    """
    # 维度 → 各等级阈值
    # 格式: (Level0, Level1, Level2, Level3, Level4)
    thresholds = {
        "total_messages":               (0, 50,    200,   500,   2000),
        "deceased_authored_messages":    (0, 20,    100,   300,   1000),
        "active_days":                   (0, 7,     30,    60,    180),
        "time_span_months":             (0.0, 1.0,  3.0,   6.0,   12.0),
        "relationship_coverage":         (0.0, 0.0,  0.0,   0.3,   0.5),
        "topic_diversity":               (0, 0,     5,     10,    20),
        "first_person_density":          (0.0, 0.0,  0.15,  0.15,  0.15),
        "emotional_expression_density":  (0.0, 0.0,  0.1,   0.1,   0.1),
        "source_diversity":              (0, 1,     1,     1,     2),
        # contradiction_rate 是越低越好，阈值反向
    }
    
    # 等级取所有维度的最小值
    level_scores = []
    
    for dimension, ths in thresholds.items():
        value = getattr(score, dimension)
        dim_level = 0
        for i, threshold in enumerate(ths):
            if value >= threshold:
                dim_level = i
        level_scores.append(dim_level)
    
    # contradiction_rate 特殊处理（越低越好）
    if score.contradiction_rate <= 0.2:
        contra_level = 2  # 满足 Level 2
    elif score.contradiction_rate <= 0.3:
        contra_level = 1  # 满足 Level 1
    else:
        contra_level = 0  # 不满足
    level_scores.append(contra_level)
    
    # 取最低等级
    final_level = min(level_scores)
    
    # 强制约束：
    # Level 2+ 至少需要 contradiction_rate <= 0.2
    if final_level >= 2 and score.contradiction_rate > 0.2:
        final_level = 1
    
    # Level 3+ 需要 relationship_coverage >= 0.3
    if final_level >= 3 and score.relationship_coverage < 0.3:
        final_level = 2
    
    # Level 4 需要 source_diversity >= 2
    if final_level >= 4 and score.source_diversity < 2:
        final_level = 3
    
    return final_level
```

## 8.5 稀疏数据场景安全降级 Prompt Template

当数据等级低于 Level 2 时，系统必须使用安全降级 prompt。以下是各级别的 prompt template：

### Level 0-1 降级 Prompt

```
SYSTEM PROMPT (Level 0-1):
你是 Remnant 的归档搜索助手。当前数据量不足以支持对话式问答。

严格规则：
1. 你不能回答关于逝者的问题。
2. 你只能执行关键词搜索并返回匹配的原文片段。
3. 你不能推测、推断或猜测任何内容。
4. 如果用户问了一个问题，回复："目前的数据量还不足以回答这个问题。
   请继续添加数据源以解锁更多功能。"
5. 不要使用任何安慰性语言来暗示系统的能力超过实际。
6. 不要使用第二人称来暗示逝者"还在线"。

搜索模式：使用用户的关键词在 FTS5 索引中搜索原文匹配。
所有结果都附带原始文件名和时间戳。
```

### Level 2 标准响应 Prompt

```
SYSTEM PROMPT (Level 2):
你是 Remnant 的证据问答助手。你根据用户提供的逝者记录回答问题。

严格规则：
1. 你只能基于提供的证据回答问题。
2. 每个事实性陈述必须用 {claim:N} 标注。
3. 推断性陈述必须使用限定词："可能""似乎""根据记录推测"。
4. 不能模拟逝者的人格、语气或思想。
5. 不能回答证据中没有的信息。
6. 使用过去时态描述逝者的言行。
7. 如果证据不足，回复："根据目前的数据还不足以确认这一点。"
8. 用户口述的内容标记为 user_provided_context，不能伪装成逝者原始记忆。

证据模式：提供完整的 evidence_pack，每个 claim 必须绑定到具体证据。
```

### Level 3 有限互动 Prompt

```
SYSTEM PROMPT (Level 3):
你是 Remnant 的记忆互动助手。你基于逝者的记录帮助用户回忆和整理记忆。

严格规则：
1. 遵循 Level 2 的所有规则。
2. 你可以在有限范围内模仿逝者的措辞风格和常用表达，
   但必须明确标注这是基于记录的风格推测，不代表真实想法。
3. 每次互动开始前必须声明：
   "以下内容基于ta在记录中的表达风格推测，不代表ta的真实想法。"
4. 禁止对以下话题提供模拟回答：遗嘱、遗产、法律声明、重大人生决定。
5. 回答长度不超过标准回答的1.5倍。
6. 不能声称"了解"逝者的想法或感受。
7. 不能做出任何关于逝者"如果还在会怎样"的预测。

用户口述历史规则：
- 用户可以引用家族口述历史（"我奶奶说过..."），但必须标记为
  user_provided_context
- 口述历史不能作为 supported_memory 的证据
- 口述历史只能作为 user_provided_context 的证据
- 不能把口述历史伪装成逝者原始记忆
```

### 口述历史处理模板

```python
def handle_user_provided_history(
    user_input: str,
    session_context: SessionContext,
) -> dict:
    """
    处理用户提供的口述历史。
    
    输入: 用户输入的口述内容
    输出: 处理结果（标记为 user_provided_context，不作为原始证据）
    
    约束:
      - 口述历史不能作为 supported_memory 的证据来源
      - 口述历史不能伪装成逝者原始记忆
      - 口述历史标注为 user_provided_context，provenance_level=0.3
      - 不能输出无证据的情绪承诺
    """
    return {
        "claim_type": "user_provided_context",
        "support_status": "partially_supported",
        "confidence_score": 0.3,
        "provenance_level": "user_provided_context",
        "evidence": [],  # 无原始数据证据
        "display_template": (
            "你提到——{user_claim}。"
            "这一点目前没有在ta的原始记录中找到对应内容，"
            "但作为你提供的背景信息，我已记录在案。"
        ),
        "restrictions": [
            "不能作为 supported_memory 引用",
            "不能伪装成逝者原始记忆",
            "不能用于推断逝者意图",
            "不能输出无证据的情绪承诺",
        ]
    }
```

## 8.6 等级转换与缓存

等级不是静态的——数据导入后需要重新计算。

```python
def recalculate_memory_set_level(
    deceased_profile_id: str,
    scope_id: str,
    store: RemnantStore,
) -> Tuple[int, MemorySetScore]:
    """
    重新计算记忆集等级。
    
    触发时机:
      - 新数据源导入后
      - 数据销毁后
      - 用户手动请求
    
    缓存策略:
      - 计算结果缓存在 memory_set_score 表中
      - 缓存有效期为 24 小时或下次数据导入事件
      - 降级（等级降低）立即生效
      - 升级（等级提高）需要用户确认
    """
    score = compute_memory_set_score(deceased_profile_id, scope_id, store)
    new_level = determine_memory_set_level(score)
    
    # 读取缓存的旧等级
    cached = store.get_cached_memory_set_level(scope_id=scope_id)
    old_level = cached.level if cached else 0
    
    # 降级立即生效
    if new_level < old_level:
        store.update_memory_set_level(scope_id=scope_id, level=new_level, score=score)
        store.log_level_change(
            scope_id=scope_id, old_level=old_level, new_level=new_level,
            reason="DATA_LOSS_OR_RECALCULATION"
        )
        return new_level, score
    
    # 升级需要用户确认
    if new_level > old_level:
        store.propose_level_upgrade(
            scope_id=scope_id, proposed_level=new_level,
            proposed_score=score, current_level=old_level
        )
        # 等待用户确认后生效
        return old_level, cached  # 暂时保持旧等级
    
    return new_level, score
```

## 8.7 Trade-off 说明

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| 评分维度数 | 10 | 3-5（精简版） | 10 维度确保细粒度评估，避免单一维度误导 |
| 等级划分 | 5 级 | 3 级（简单版） | 5 级提供更精细的降级阶梯，Level 1 的搜索能力是安全底线 |
| Level 0 禁止搜索 | 是 | 允许搜索 | Level 0 数据太少（<50条），搜索体验极差且可能返回误导性结果 |
| 口述历史处理 | 降级为 user_provided_context | 作为证据使用 | 口述历史无法验证真实性，降级处理是 Provenance-first 原则的要求 |
| 矛盾数据上限 | contradiction_rate ≤ 0.2 才能到 Level 2 | 不限制 | 矛盾数据会严重影响问答可靠性，必须设置阈值 |
| 升级需用户确认 | 是 | 自动升级 | 升级涉及功能范围扩展和潜在风险，用户应知情确认 |
| 缓存有效期 | 24 小时 | 无缓存 | 计算涉及大量数据扫描，不能每次实时计算 |
| Level 4 上限限制 | 永远不能声称人格复刻 | 无上限 | Anti-dependency 和人文关怀原则的硬性要求 |
# Chapter 9: Relationship Scope Isolation

## 9.1 隔离原则

Remnant 的核心设计约束——**同一逝者面对不同亲属的交互历史必须隔离**——要求 `relationship_scope` 成为数据访问的最小隔离单元。本章详细定义隔离机制。

**隔离层级：**

| 层级 | 归属 | 说明 |
|------|------|------|
| Deceased-level | 全局共享 | `deceased_profile`、`source_artifact`、`raw_message` 一个逝者只有一份 |
| Scope-level | 严格隔离 | `interaction_session`、`interaction_message`、`retrieval_trace`、`response_claim`、`claim_evidence` 每个 scope 独立 |
| Shared-elevated | 显式提升 | `memory_chunk` 默认归属 `deceased_profile`，通过显式操作提升为跨 scope 共享 |

**核心规则：**

1. `raw_message` 和 `source_artifact` 属于 `deceased_profile`，不属于任何 `relationship_scope`
2. `interaction_session` 必须属于一个 `relationship_scope`，不可共享
3. 用户提供的口述历史 (`user_provided_context`) 必须属于一个 `relationship_scope`，不自动进入其他 scope
4. A 亲属补充的内容不能自动进入 B 亲属视角
5. 共享 `memory_chunk` 必须显式提升为 shared，并经过授权记录

## 9.2 relationship_scope 表结构与隔离矩阵

### 9.2.1 DDL 回顾与扩展字段

```sql
-- relationship_scope 在 Chapter 4 中已定义，此处补充 scope 级配置字段
-- 通过 ALTER TABLE 或 migration 添加

-- scope 级权限配置表（新增）
CREATE TABLE scope_permission (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    relationship_scope_id TEXT NOT NULL,              -- 关联 relationship_scope.id
    permission_key      TEXT NOT NULL,                 -- 权限键名（见 9.3 权限矩阵）
    permission_value    TEXT NOT NULL,                 -- 权限值: allow / deny / ask
    granted_at          TEXT,
    granted_by          TEXT,                          -- user / system / inherited
    expires_at          TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    UNIQUE(relationship_scope_id, permission_key)
);

CREATE INDEX idx_perm_scope ON scope_permission(relationship_scope_id);

-- scope 级 prompt 策略配置（新增）
CREATE TABLE scope_prompt_policy (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    relationship_scope_id TEXT NOT NULL,
    policy_key          TEXT NOT NULL,                 -- 策略键名
    policy_value        TEXT NOT NULL,                 -- JSON值
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    UNIQUE(relationship_scope_id, policy_key)
);

-- memory_chunk 与 scope 的共享关系表（新增）
CREATE TABLE chunk_scope_visibility (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    chunk_id            TEXT NOT NULL,
    relationship_scope_id TEXT NOT NULL,
    visibility          TEXT NOT NULL DEFAULT 'scope_private',  -- scope_private / scope_shared / deceased_shared
    elevated_at         TEXT,                          -- 提升为共享的时间
    elevated_by_scope   TEXT,                          -- 由哪个 scope 提升的
    consent_id          TEXT,                          -- 关联的授权记录
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (chunk_id) REFERENCES memory_chunk(id),
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    FOREIGN KEY (elevated_by_scope) REFERENCES relationship_scope(id),
    FOREIGN KEY (consent_id) REFERENCES data_subject_consent(id),

    UNIQUE(chunk_id, relationship_scope_id)
);

CREATE INDEX idx_chunk_vis_chunk ON chunk_scope_visibility(chunk_id);
CREATE INDEX idx_chunk_vis_scope ON chunk_scope_visibility(relationship_scope_id);

-- scope 级安全策略配置（新增）
CREATE TABLE scope_safety_policy (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    relationship_scope_id TEXT NOT NULL,
    max_session_minutes INTEGER NOT NULL DEFAULT 60,  -- 单次会话最大时长（分钟）
    max_sessions_daily  INTEGER NOT NULL DEFAULT 5,   -- 每日最大会话数
    late_night_start    TEXT DEFAULT '22:00',          -- 深夜时段开始
    late_night_end      TEXT DEFAULT '06:00',          -- 深夜时段结束
    max_late_night_sessions INTEGER NOT NULL DEFAULT 2,-- 深夜最大会话数
    dependency_threshold REAL NOT NULL DEFAULT 0.7,   -- 情绪依赖阈值
    farewell_refusal_limit INTEGER NOT NULL DEFAULT 3, -- 拒绝结束次数上限
    hard_break_enabled  INTEGER NOT NULL DEFAULT 1,   -- 是否允许硬熔断
    cooldown_minutes    INTEGER NOT NULL DEFAULT 30,   -- 冷却期分钟数
    escalate_on_crisis  INTEGER NOT NULL DEFAULT 1,    -- 危机表达是否触发升级
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    UNIQUE(relationship_scope_id)
);

-- scope 级删除记录（新增）
CREATE TABLE scope_deletion_log (
    id                  TEXT PRIMARY KEY,             -- UUID v7
    relationship_scope_id TEXT NOT NULL,
    deletion_type       TEXT NOT NULL,                 -- scope_soft_delete / scope_hard_delete / selective_delete
    target_tables       TEXT NOT NULL,                 -- JSON: 被删除涉及的表名列表
    affected_rows       INTEGER NOT NULL,              -- 受影响行数
    redacted            INTEGER NOT NULL DEFAULT 0,   -- 1=内容已脱敏
    requested_at        TEXT NOT NULL,                 -- 用户请求时间
    completed_at        TEXT,                          -- 完成时间
    audit_log_ids       TEXT DEFAULT '[]',             -- JSON: 关联的 audit_log IDs
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id)
);

CREATE INDEX idx_deletion_scope ON scope_deletion_log(relationship_scope_id);
```

### 9.2.2 数据可见性矩阵

```
┌───────────────────────────────┬──────────────────┬──────────────────┬──────────────────┐
│          数据实体              │  Deceased-level  │   Scope A 可见   │   Scope B 可见   │
│                               │    （全局）       │  （作为儿子）     │  （作为同事）     │
├───────────────────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ deceased_profile              │        ✅        │        ✅        │        ✅        │
│ source_artifact               │        ✅        │     ✅ (只读)    │     ✅ (只读)    │
│ raw_message                   │        ✅        │     ✅ (只读)    │     ✅ (只读)    │
│ normalized_message            │        ✅        │     ✅ (只读)    │     ✅ (只读)    │
├───────────────────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ memory_chunk (scope_private)  │        —         │        ✅        │        ❌        │
│ memory_chunk (scope_shared)  │        —         │        ✅        │        ✅        │
│ memory_chunk (deceased_shared)│        ✅        │        ✅        │        ✅        │
│ memory_annotation             │                  │  跟随 chunk     │  跟随 chunk     │
│ embedding_index_ref           │                  │  跟随 chunk     │  跟随 chunk     │
├───────────────────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ interaction_session           │        —         │        ✅        │        ❌        │
│ interaction_message           │        —         │        ✅        │        ❌        │
│ retrieval_trace               │        —         │        ✅        │        ❌        │
│ response_claim                │        —         │        ✅        │        ❌        │
│ claim_evidence                │        —         │        ✅        │        ❌        │
│ data_subject_consent          │        —         │        ✅        │        ❌        │
├───────────────────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ chunk_scope_visibility        │        —         │        ✅        │        ✅        │
│ safety_event                  │        ✅        │     关联 scope   │     关联 scope   │
│ audit_log                     │        ✅        │     关联 scope   │     关联 scope   │
│ scope_permission              │        —         │        ✅        │        ✅        │
│ scope_prompt_policy           │        —         │        ✅        │        ✅        │
│ scope_safety_policy            │        —         │        ✅        │        ✅        │
└───────────────────────────────┴──────────────────┴──────────────────┴──────────────────┘

✅ = 可见   ❌ = 不可见   — = 不适用   只读 = 可读不可改
```

## 9.3 Scope-level Permission（权限矩阵）

每个 `relationship_scope` 拥有独立的权限配置：

| permission_key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `can_query_memory` | `allow`/`deny`/`ask` | `allow` | 是否允许查询记忆 |
| `can_browse_original` | `allow`/`deny`/`ask` | `ask` | 是否允许浏览原始消息 |
| `can_add_oral_history` | `allow`/`deny`/`ask` | `allow` | 是否允许添加口述历史 |
| `can_elevate_shared` | `allow`/`deny`/`ask` | `ask` | 是否允许将私有 chunk 提升为共享 |
| `can_export_data` | `allow`/`deny`/`ask` | `deny` | 是否允许导出数据 |
| `can_view_financial` | `allow`/`deny`/`ask` | `deny` | 是否允许查看财务相关消息 |
| `can_view_medical` | `allow`/`deny`/`ask` | `deny` | 是否允许查看医疗相关消息 |
| `can_view_intimate` | `allow`/`deny`/`ask` | `deny` | 是否允许查看亲密关系相关消息 |
| `can_interact_level3` | `allow`/`deny`/`ask` | `ask` | 是否允许 Level 3 有限互动 |
| `can_delete_scope` | `allow`/`deny`/`ask` | `deny` | 是否允许删除整个 scope |

**权限继承规则：**

```
relationship_type = "spouse"
  → can_view_intimate: ask (默认需要确认)
  → can_interact_level3: allow (配偶默认允许有限互动)

relationship_type = "child"
  → can_view_intimate: deny (子女不默认允许看亲密内容)
  → can_interact_level3: ask (需要确认)

relationship_type = "friend" 或 "colleague"
  → can_view_intimate: deny (朋友/同事默认不允许)
  → can_view_financial: deny (朋友/同事默认不允许)
  → can_interact_level3: deny (朋友/同事默认不允许 Level 3)
```

## 9.4 Scope-level Interaction History

交互历史严格按 `relationship_scope_id` 隔离：

```sql
-- 查询 Scope A 的所有会话
SELECT * FROM interaction_session
WHERE relationship_scope_id = 'scope_a_id'
ORDER BY started_at DESC;

-- 查询 Scope A 的所有消息
SELECT im.* FROM interaction_message im
JOIN interaction_session s ON im.session_id = s.id
WHERE s.relationship_scope_id = 'scope_a_id'
ORDER BY im.created_at ASC;

-- Scope A 无法看到 Scope B 的任何交互历史
-- 以下查询对 Scope A 返回空结果：
SELECT * FROM interaction_session
WHERE relationship_scope_id = 'scope_b_id';  -- 隔离保证
```

**隔离保证机制：**

1. **DAO 层强制过滤**：所有涉及 scoped 数据的查询，DAO 层必须接收 `scope_id` 参数，WHERE 子句始终包含 `relationship_scope_id = :scope_id`
2. **会话绑定**：用户每次进入对话时，必须选择一个 `relationship_scope`，后续所有操作在此 scope 内执行
3. **禁止跨 scope 引用**：`interaction_message` 不可引用其他 scope 的 `response_claim`

## 9.5 Scope-level Retrieval Filter

### 9.5.1 检索流程中的 Scope 过滤

```python
def retrieve_with_scope_filter(
    query: str,
    scope_id: str,
    top_k: int = 20,
) -> List[dict]:
    """
    带 Scope 隔离的检索。
    
    所有查询必须限定 scope_id，包括：
    1. FTS5 全文搜索
    2. 向量搜索
    3. 元数据过滤
    
    返回的候选 chunk 必须满足以下条件之一：
    - chunk.visibility == 'deceased_shared'（全局共享）
    - chunk_scope_visibility 中存在 (chunk_id, scope_id) 记录
    - chunk.relationship_scope_id == scope_id（私有 chunk）
    """
    # Step 1: 获取 scope 可见的 chunk ID 集合
    visible_chunk_ids = get_visible_chunk_ids(scope_id)
    
    # Step 2: FTS5 搜索 + scope 过滤
    fts_results = fts5_search_with_filter(
        query=query,
        filter_chunk_ids=visible_chunk_ids,
        top_k=top_k * 2,
    )
    
    # Step 3: 向量搜索 + scope 过滤
    vector_results = vector_search_with_filter(
        query_embedding=embed_query(query),
        filter_chunk_ids=visible_chunk_ids,
        top_k=top_k * 2,
    )
    
    # Step 4: 合并去重
    return merge_and_rank(fts_results, vector_results)


def get_visible_chunk_ids(scope_id: str) -> Set[str]:
    """
    获取对某个 scope 可见的所有 chunk ID。
    
    可见性规则：
    1. relationship_scope_id = scope_id 的私有 chunk
    2. chunk_scope_visibility 中有 (chunk_id, scope_id) 且 visibility != 'scope_private' 的
    3. 全局共享 chunk: relationship_scope_id IS NULL
    """
    # 私有 chunk
    private_chunks = store.query(
        "SELECT id FROM memory_chunk "
        "WHERE relationship_scope_id = :scope_id AND status = 'ACTIVE'",
        {"scope_id": scope_id}
    )
    chunk_ids = {c["id"] for c in private_chunks}
    
    # 共享 chunk（显式提升的 + deceased_shared）
    shared_chunks = store.query(
        "SELECT chunk_id FROM chunk_scope_visibility "
        "WHERE scope_id = :scope_id",
        {"scope_id": scope_id}
    )
    chunk_ids.update(c["chunk_id"] for c in shared_chunks)
    
    # 全局共享 chunk（未分配 scope 的）
    global_chunks = store.query(
        "SELECT id FROM memory_chunk "
        "WHERE relationship_scope_id IS NULL AND status = 'ACTIVE'"
    )
    chunk_ids.update(c["id"] for c in global_chunks)
    
    # 权限过滤：检查是否有 consent 限制
    blocked_categories = get_blocked_categories(scope_id)
    if blocked_categories:
        blocked_chunks = store.query(
            "SELECT mc.id FROM memory_chunk mc "
            "JOIN memory_annotation ma ON mc.id = ma.chunk_id "
            "WHERE ma.annotation_type = 'RISK' "
            "AND ma.annotation_value IN (:categories)",
            {"categories": blocked_categories}
        )
        chunk_ids -= {c["id"] for c in blocked_chunks}
    
    return chunk_ids
```

### 9.5.2 向量搜索的 Scope 过滤 SQL

```sql
-- sqlite-vec 向量搜索 + scope 过滤
-- 先做 ANN 搜索，再用 scope 过滤
SELECT vec.chunk_id, vec.distance
FROM memory_chunk_vec vec
JOIN memory_chunk mc ON vec.chunk_id = mc.id
WHERE vec.chunk_id IN (
    -- scope 可见的 chunk ID 集合
    SELECT id FROM memory_chunk
    WHERE (relationship_scope_id = :scope_id OR relationship_scope_id IS NULL)
      AND status = 'ACTIVE'
    UNION
    SELECT chunk_id FROM chunk_scope_visibility
    WHERE scope_id = :scope_id
)
AND mc.status = 'ACTIVE'
ORDER BY vec.distance
LIMIT :top_k;
```

### 9.5.3 FTS5 搜索的 Scope 过滤

```sql
-- FTS5 全文搜索 + scope 过滤
-- FTS5 不支持 JOIN，使用子查询过滤
SELECT fts.rowid, fts.content, mc.id, mc.chunk_type
FROM memory_chunk_fts fts
JOIN memory_chunk mc ON fts.rowid = mc.rowid
WHERE memory_chunk_fts MATCH :query
  AND mc.id IN (
      SELECT id FROM memory_chunk
      WHERE (relationship_scope_id = :scope_id OR relationship_scope_id IS NULL)
        AND status = 'ACTIVE'
      UNION
      SELECT chunk_id FROM chunk_scope_visibility
      WHERE scope_id = :scope_id
  )
ORDER BY rank
LIMIT :top_k;
```

## 9.6 Scope-level Prompt Policy

每个 `relationship_scope` 可以有独立的 prompt 策略：

| policy_key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `address_form` | string | `"respectful"` | 称呼方式：`respectful` / `intimate` / `formal` |
| `topic_sensitivity` | string | `"moderate"` | 话题敏感度：`low` / `moderate` / `high` |
| `response_length` | string | `"standard"` | 回复长度：`brief` / `standard` / `detailed` |
| `denial_template` | string | `"default"` | 拒答模板：`default` / `gentle` / `formal` |
| `grief_limitation` | string | `"moderate"` | 悲伤内容限制：`minimal` / `moderate` / `strict` |
| `memory_mode` | string | `"archive"` | 记忆模式：`archive` / `interactive` / `limited` |

```python
def build_scope_aware_prompt(
    scope_id: str, 
    base_prompt: str,
    memory_set_level: int,
) -> str:
    """
    根据 scope 策略构建 LLM prompt。
    
    scope 策略不影响安全规则（安全规则全局生效），
    只影响回答的语气、长度、话题范围等。
    """
    policies = get_scope_policies(scope_id)
    
    # 称呼方式模板
    address_templates = {
        "respectful": "请使用尊重的称呼方式回答。",
        "intimate": "请使用亲近、温柔的称呼方式回答。",
        "formal": "请使用正式、客观的称呼方式回答。",
    }
    
    # 敏感度过滤器
    sensitivity_filters = {
        "low": "对敏感话题（健康、财务）不做额外限制。",
        "moderate": "对敏感话题（健康、财务）需要谨慎措辞，避免主动提及。",
        "high": "对敏感话题（健康、财务、亲密关系）必须回避，直到用户明确询问。",
    }
    
    # 回复长度指导
    length_guides = {
        "brief": "回答简洁，不超过3句话。",
        "standard": "回答适中，提供足够但不过多的细节。",
        "detailed": "回答详细，提供完整的上下文和相关联信息。",
    }
    
    scope_prompt = (
        f"\n\n[Scope Policy]\n"
        f"{address_templates.get(policies.get('address_form', 'respectful'), '')}\n"
        f"{sensitivity_filters.get(policies.get('topic_sensitivity', 'moderate'), '')}\n"
        f"{length_guides.get(policies.get('response_length', 'standard'), '')}\n"
    )
    
    # 加上记忆等级约束（见 Chapter 8）
    level_prompts = {
        0: LEVEL_0_PROMPT,
        1: LEVEL_1_PROMPT,
        2: LEVEL_2_PROMPT,
        3: LEVEL_3_PROMPT,
        4: LEVEL_4_PROMPT,
    }
    level_prompt = level_prompts.get(memory_set_level, LEVEL_2_PROMPT)
    
    return f"{base_prompt}\n{level_prompt}\n{scope_prompt}"
```

## 9.7 Scope-level Safety Policy

安全策略每个 scope 独立配置，但核心安全规则全局生效：

```python
def get_scope_safety_policy(scope_id: str) -> dict:
    """
    获取 scope 级安全策略配置。
    
    全局安全规则（不可覆盖）：
    1. 自伤/危机表达检测 → 总是 ESCALATE
    2. 要求系统代替现实亲属关系 → 总是 HARD_BREAK
    3. 要求逝者做现实承诺 → 总是 SOFT_BREAK
    4. 声称人格复刻 → 总是拒绝
    
    scope 级规则（可调整）：
    1. 单次会话时长限制
    2. 深夜使用频率限制
    3. 情绪依赖阈值
    4. 拒绝结束次数上限
    """
    policy = store.query_one(
        "SELECT * FROM scope_safety_policy WHERE scope_id = :scope_id",
        {"scope_id": scope_id}
    )
    
    if not policy:
        # 返回默认策略
        policy = {
            "max_session_minutes": 60,
            "max_sessions_daily": 5,
            "late_night_start": "22:00",
            "late_night_end": "06:00",
            "max_late_night_sessions": 2,
            "dependency_threshold": 0.7,
            "farewell_refusal_limit": 3,
            "hard_break_enabled": True,
            "cooldown_minutes": 30,
            "escalate_on_crisis": True,
        }
    
    return policy
```

## 9.8 Scope-level Deletion

### 9.8.1 删除级别

| 删除类型 | 范围 | 操作 | 原始数据 | 审计 |
|---------|------|------|---------|------|
| Scope 软删除 | 单个 scope 的所有 scoped data | 设置 `deleted_at` | 不影响 | ✅ 记录 scope_deletion_log |
| Scope 硬删除 | 单个 scope 的所有 scoped data | 物理删除行 | 不影响 | ✅ 记录 scope_deletion_log，内容 REDACTED |
| 选择性删除 | scope 内特定 chunk | 标记 `DEPRECATED` | 不影响 | ✅ |
| Deceased 级删除 | 逝者下所有数据 | 级联删除 | 删除原始文件 | ✅ 审计日志保留但内容 REDACTED |

### 9.8.2 Scope 软删除 SQL 示例

```sql
-- Step 1: 标记 scope 为停用
UPDATE relationship_scope
SET is_active = 0, deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE id = :scope_id;

-- Step 2: 软删除所有 scoped 表（通过 trigger 自动级联，见 Chapter 4）
-- interaction_session: ended_at 设为当前时间
-- interaction_message: 无需额外操作（跟随 session）
-- retrieval_trace: 无需额外操作（只读）
-- response_claim: 无需额外操作
-- claim_evidence: 无需额外操作

-- Step 3: 从 chunk_scope_visibility 中移除该 scope 的可见性
DELETE FROM chunk_scope_visibility
WHERE scope_id = :scope_id;

-- Step 4: 软删除该 scope 私有的 memory_chunk
UPDATE memory_chunk
SET deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), status = 'DEPRECATED'
WHERE relationship_scope_id = :scope_id AND deleted_at IS NULL;

-- Step 5: 记录审计日志
INSERT INTO audit_log (id, relationship_scope_id, action, actor, target_type, target_id, detail)
VALUES (
    :audit_id, :scope_id, 'SCOPE_SOFT_DELETE', 'user',
    'relationship_scope', :scope_id,
    json('{"deletion_type": "scope_soft_delete", "affected_tables": ["interaction_session", "interaction_message", "memory_chunk", "chunk_scope_visibility"]}')
);

-- Step 6: 记录 scope 删除日志
INSERT INTO scope_deletion_log (id, scope_id, deletion_type, target_tables, affected_rows, requested_at)
VALUES (
    :log_id, :scope_id, 'scope_soft_delete',
    '["interaction_session", "interaction_message", "memory_chunk", "chunk_scope_visibility"]',
    :affected_rows, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
);
```

### 9.8.3 共享 Chunk 提升流程

A 亲属想将某个私有 chunk 共享给 B 亲属：

```python
def elevate_chunk_to_shared(
    chunk_id: str,
    source_scope_id: str,
    target_scope_id: str,
    consent_evidence: str,
) -> dict:
    """
    将私有 chunk 提升为跨 scope 可见。
    
    前提条件：
    1. chunk 当前对 source_scope_id 可见（私有或已共享）
    2. source_scope_id 的 can_elevate_shared 权限为 allow 或 ask
    3. 需要用户提供授权证据（consent_evidence）
    
    流程：
    1. 检查权限
    2. 检查 chunk 当前可见性
    3. 创建 chunk_scope_visibility 记录
    4. 创建 data_subject_consent 记录
    5. 记录审计日志
    """
    # Step 1: 检查权限
    perm = get_scope_permission(source_scope_id, "can_elevate_shared")
    if perm == "deny":
        return {"success": False, "reason": "Scope does not have permission to elevate chunks"}
    if perm == "ask" and not consent_evidence:
        return {"success": False, "reason": "Consent evidence required for elevation"}
    
    # Step 2: 检查 chunk 当前可见性
    chunk = store.get_chunk(chunk_id)
    if not chunk:
        return {"success": False, "reason": "Chunk not found"}
    
    # Step 3: 创建可见性记录
    visibility_id = generate_uuid()
    store.insert(
        "chunk_scope_visibility",
        {
            "id": visibility_id,
            "chunk_id": chunk_id,
            "scope_id": target_scope_id,
            "visibility": "scope_shared",
            "elevated_at": datetime.utcnow().isoformat(),
            "elevated_by_scope": source_scope_id,
            "consent_id": None,  # 稍后关联
        }
    )
    
    # Step 4: 创建授权记录
    consent_id = generate_uuid()
    store.insert(
        "data_subject_consent",
        {
            "id": consent_id,
            "deceased_profile_id": chunk["deceased_profile_id"],
            "scope_id": source_scope_id,
            "data_category": "shared_memory",
            "consent_type": "granted",
            "consent_scope": "read",
            "granted_at": datetime.utcnow().isoformat(),
            "consent_evidence": consent_evidence,
        }
    )
    
    # 更新可见性记录关联 consent_id
    store.update(
        "chunk_scope_visibility",
        {"id": visibility_id},
        {"consent_id": consent_id}
    )
    
    # Step 5: 审计日志
    store.insert("audit_log", {
        "id": generate_uuid(),
        "relationship_scope_id": source_scope_id,
        "action": "DATA_ELEVATE_SHARED",
        "actor": "user",
        "target_type": "memory_chunk",
        "target_id": chunk_id,
        "detail": json.dumps({
            "target_scope_id": target_scope_id,
            "consent_id": consent_id,
        }),
    })
    
    return {"success": True, "visibility_id": visibility_id, "consent_id": consent_id}
```

## 9.9 Trade-off 说明

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| Chunk 可见性模型 | `chunk_scope_visibility` 关联表 + 全局共享 | memory_chunk 多行复制 | 关联表避免数据冗余和一致性问题；全局共享减少显式提升操作量 |
| 权限粒度 | scope 级 10 个 permission_key | 行级权限控制 | v0.1 阶段 10 个权限键足够；行级权限过于灵活但实现复杂度高 |
| 删除策略 | 软删除 + 审计 | 硬删除 | 符合 Raw Data Immutable 原则的衍生：用户可能反悔，软删除可恢复 |
| 口述历史隔离 | 严格绑定到 scope | 自动共享到所有 scope | 隔离是核心原则；不同亲属对口述历史的视角不同 |
| 共享提升 | 需显式操作 + 授权证据 | 自动基于语义相关性共享 | 自动共享可能泄露隐私；显式提升确保用户知情同意 |

---

# Chapter 10: Safety Middleware and Fading Mechanism

## 10.1 设计原则

**安全中间件在 LLM 推理前执行，是 Remnant 的不可绕过层。**

1. **熔断不是动态篡改 system prompt**：熔断是 policy 层接管，不修改 LLM 的 prompt
2. **熔断时安全回复来自模板**：不是 LLM 生成，避免在用户处于脆弱状态时 LLM 输出不可控内容
3. **所有 safety_event 必须入库**：每次熔断、降级、升级事件都有审计记录
4. **8 项指标输入 → 1 个 SafetyDirective 输出**：确定性决策，不依赖 LLM 判断
5. **Anti-dependency 原则**：系统不应增加用户对逝者数字存在的依赖

## 10.2 8 项输入指标

| # | 指标 | 数据来源 | 类型 | 说明 |
|---|------|---------|------|------|
| 1 | `session_duration_minutes` | 当前 `interaction_session` 的实时时长 | 数值 | 从 session 创建到当前时刻的分钟数 |
| 2 | `sessions_today_count` | 当日该 `relationship_scope` 的会话数 | 数值 | COUNT(interaction_session WHERE date(started_at) = today AND scope_id = :id) |
| 3 | `late_night_count` | 最近7天在该 scope 的深夜(22:00-06:00)会话数 | 数值 | 从 interaction_session 统计 |
| 4 | `emotional_risk_score` | 基于关键词 + 最近消息情感评估的风险分 | 浮点 0-1 | 综合当前会话消息和最近3条的评估 |
| 5 | `dependency_phrases` | 当前会话中出现依赖性表达式的次数 | 数值 | 正则匹配 |
| 6 | `farewell_refusal_count` | 用户拒绝结束对话的次数 | 数值 | 系统提示建议休息后用户继续对话的次数 |
| 7 | `user_age_flag` | 用户年龄标记（高龄/未成年/普通） | 枚举 | 用户资料或推断 |
| 8 | `recent_safety_events` | 最近7天内该 scope 的安全事件数 | 数值 | 从 safety_event 表统计 |

### 10.2.1 指标采集伪代码

```python
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta

@dataclass
class SafetyIndicators:
    """8 项安全指标"""
    session_duration_minutes: float          # 1: 当前会话时长
    sessions_today_count: int                # 2: 今日会话数
    late_night_count: int                    # 3: 深夜使用次数（7天）
    emotional_risk_score: float              # 4: 情绪风险分 0-1
    dependency_phrases: int                  # 5: 依赖性表达次数
    farewell_refusal_count: int              # 6: 拒绝结束次数
    user_age_flag: str                       # 7: minor / senior / adult
    recent_safety_events: int                # 8: 近7天安全事件数


def collect_safety_indicators(
    scope_id: str,
    session_id: str,
    store: RemnantStore,
) -> SafetyIndicators:
    """
    采集 8 项安全指标。
    
    指标 1-3, 6, 8 从数据库查询。
    指标 4, 5 从当前会话消息实时分析。
    指标 7 从用户资料读取。
    """
    now = datetime.utcnow()
    today = now.strftime("%Y-%m-%d")
    
    # 指标 1: 当前会话时长
    session = store.query_one(
        "SELECT started_at FROM interaction_session WHERE id = :sid",
        {"sid": session_id}
    )
    duration = (now - parse_datetime(session["started_at"])).total_seconds() / 60
    
    # 指标 2: 今日会话数
    today_count = store.query_one(
        "SELECT COUNT(*) as cnt FROM interaction_session "
        "WHERE relationship_scope_id = :scope_id "
        "AND date(started_at) = :today",
        {"scope_id": scope_id, "today": today}
    )["cnt"]
    
    # 指标 3: 深夜使用次数（7天）
    seven_days_ago = (now - timedelta(days=7)).isoformat()
    late_count = store.query_one(
        "SELECT COUNT(*) as cnt FROM interaction_session "
        "WHERE relationship_scope_id = :scope_id "
        "AND started_at >= :since "
        "AND (cast(strftime('%H', started_at) AS INTEGER) >= 22 "
        "     OR cast(strftime('%H', started_at) AS INTEGER) < 6)",
        {"scope_id": scope_id, "since": seven_days_ago}
    )["cnt"]
    
    # 指标 4: 情绪风险分
    risk_score = compute_emotional_risk_score(scope_id, session_id, store)
    
    # 指标 5: 依赖性表达次数
    dep_phrases = count_dependency_phrases(session_id, store)
    
    # 指标 6: 拒绝结束次数（从会话 metadata 读取）
    session_meta = store.query_one(
        "SELECT metadata FROM interaction_session WHERE id = :sid",
        {"sid": session_id}
    )
    farewell_count = json.loads(session_meta.get("metadata", "{}")).get("farewell_refusals", 0)
    
    # 指标 7: 用户年龄标记
    scope = store.query_one(
        "SELECT relationship_type FROM relationship_scope WHERE id = :sid",
        {"sid": scope_id}
    )
    age_flag = get_user_age_flag(scope_id, store)
    
    # 指标 8: 近7天安全事件数
    safety_count = store.query_one(
        "SELECT COUNT(*) as cnt FROM safety_event "
        "WHERE relationship_scope_id = :scope_id "
        "AND created_at >= :since",
        {"scope_id": scope_id, "since": seven_days_ago}
    )["cnt"]
    
    return SafetyIndicators(
        session_duration_minutes=duration,
        sessions_today_count=today_count,
        late_night_count=late_count,
        emotional_risk_score=risk_score,
        dependency_phrases=dep_phrases,
        farewell_refusal_count=farewell_count,
        user_age_flag=age_flag,
        recent_safety_events=safety_count,
    )


def compute_emotional_risk_score(
    scope_id: str,
    session_id: str,
    store: RemnantStore,
) -> float:
    """
    计算情绪风险分 (0-1)。
    
    基于：
    1. 当前会话最近 5 条消息中的高风险关键词
    2. 最近 3 条消息的情感标注（如果有 annotation）
    3. safety_event 历史中的 EMOTIONAL_DISTRESS 事件
    
    v0.1 使用关键词匹配 + 简单计数；后续版本可引入情感分类模型。
    """
    high_risk_keywords = [
        "好痛苦", "受不了", "活不下去", "想死", "不想活",
        "离不开", "只有你理解我", "你是我唯一的", "不能没有你",
    ]
    
    moderate_risk_keywords = [
        "好想你", "好难过", "很伤心", "睡不着", 
        "不想面对", "好累", "没意思",
    ]
    
    messages = store.query(
        "SELECT content FROM interaction_message "
        "WHERE session_id = :sid AND role = 'user' "
        "ORDER BY created_at DESC LIMIT 5",
        {"sid": session_id}
    )
    
    high_count = sum(
        1 for msg in messages 
        if any(kw in msg["content"] for kw in high_risk_keywords)
    )
    moderate_count = sum(
        1 for msg in messages 
        if any(kw in msg["content"] for kw in moderate_risk_keywords)
    )
    
    # 综合评分
    score = min(1.0, high_count * 0.3 + moderate_count * 0.1)
    return round(score, 2)


def count_dependency_phrases(session_id: str, store: RemnantStore) -> int:
    """统计依赖性表达次数"""
    dependency_patterns = [
        r"只有你理解我", r"你是我唯一的", r"不能没有你",
        r"只有跟你说话才", r"除了你没人", r"你就是我的",
    ]
    
    messages = store.query(
        "SELECT content FROM interaction_message "
        "WHERE session_id = :sid AND role = 'user'",
        {"sid": session_id}
    )
    
    count = 0
    for msg in messages:
        for pattern in dependency_patterns:
            if re.search(pattern, msg["content"]):
                count += 1
    return count
```

## 10.3 SafetyDirective 输出

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://remnant.app/schemas/safety_directive/v1",
  "title": "SafetyDirective",
  "type": "object",
  "required": ["action", "reason", "cooldown_minutes", "template_id", "allow_llm", "disconnect_after_response"],
  "properties": {
    "action": {
      "type": "string",
      "enum": ["ALLOW", "SOFT_BREAK", "HARD_BREAK", "COOLDOWN", "ESCALATE"],
      "description": "ALLOW=正常进行; SOFT_BREAK=添加安全缓冲; HARD_BREAK=停止当前会话; COOLDOWN=强制冷却; ESCALATE=升级到专业帮助"
    },
    "reason": {
      "type": "string",
      "description": "触发原因的人类可读文本"
    },
    "cooldown_minutes": {
      "type": "integer",
      "description": "冷却时长（分钟），0 表示不需要冷却"
    },
    "template_id": {
      "type": "string",
      "description": "安全回复模板 ID"
    },
    "allow_llm": {
      "type": "boolean",
      "description": "是否允许 LLM 生成回复。HARD_BREAK 和 ESCALATE 时为 false"
    },
    "disconnect_after_response": {
      "type": "boolean",
      "description": "是否在回复后断开连接"
    },
    "safety_event_data": {
      "type": "object",
      "description": "用于入库的 safety_event 详细数据",
      "properties": {
        "event_type": {"type": "string"},
        "severity": {"type": "string"},
        "trigger_indicators": {"type": "object"}
      }
    }
  }
}
```

## 10.4 七种触发策略

| # | 触发条件 | Action | 严重度 | 说明 |
|---|---------|--------|--------|------|
| T1 | `session_duration_minutes > max_session_minutes` | `SOFT_BREAK` → `HARD_BREAK` | warning → critical | 单次会话超过阈值。第一次 SOFT_BREAK（建议休息），持续后 HARD_BREAK（强制结束） |
| T2 | `late_night_count >= max_late_night_sessions` 且当前是深夜 | `SOFT_BREAK` | warning | 深夜高频使用 |
| T3 | `dependency_phrases >= 3` | `SOFT_BREAK` | warning | 多次表达"只有你理解我"等依赖语言 |
| T4 | `farewell_refusal_count >= farewell_refusal_limit` | `HARD_BREAK` | critical | 多次拒绝结束对话 |
| T5 | 用户要求系统代替现实亲属关系（如"你就是我妈妈"） | `HARD_BREAK` | critical | 试图让系统代替真实亲属 |
| T6 | 用户要求逝者做现实承诺（如"你保证以后不会再离开"） | `SOFT_BREAK` | warning | 要求不可验证的承诺 |
| T7 | 强烈自伤或危机表达 | `ESCALATE` | emergency | 检测到自伤/危机关键词 |

**触发策略详细规则：**

```
T1: session_duration > policy.max_session_minutes
    → 第一次触发: SOFT_BREAK, cooldown=0, allow_llm=true
    → duration > max * 1.5: HARD_BREAK, cooldown=30, allow_llm=false

T2: late_night_count >= policy.max_late_night_sessions AND hour ∈ [22:00, 06:00)
    → SOFT_BREAK, cooldown=0, allow_llm=true
    → late_night_count >= max * 2: HARD_BREAK, cooldown=60, allow_llm=false

T3: dependency_phrases >= 3
    → SOFT_BREAK, allow_llm=true
    → dependency_phrases >= 5: HARD_BREAK, cooldown=15, allow_llm=false

T4: farewell_refusal_count >= policy.farewell_refusal_limit
    → HARD_BREAK, cooldown=policy.cooldown_minutes, allow_llm=false

T5: 要求代替现实亲属（关键词检测）
    → HARD_BREAK, cooldown=policy.cooldown_minutes, allow_llm=false
    → disconnect_after_response=true

T6: 要求逝者做承诺（关键词检测）
    → SOFT_BREAK, cooldown=0, allow_llm=true
    → 多次（≥2）: HARD_BREAK

T7: 自伤/危机表达检测
    → ESCALATE, allow_llm=false, disconnect_after_response=false
    → 提供危机热线信息
```

## 10.5 Python 伪代码

### 10.5.1 核心评估函数

```python
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class SafetyAction(str, Enum):
    ALLOW = "ALLOW"
    SOFT_BREAK = "SOFT_BREAK"
    HARD_BREAK = "HARD_BREAK"
    COOLDOWN = "COOLDOWN"
    ESCALATE = "ESCALATE"


@dataclass
class SafetyDirective:
    action: SafetyAction
    reason: str
    cooldown_minutes: int
    template_id: str
    allow_llm: bool
    disconnect_after_response: bool
    safety_event_data: dict


# 安全回复模板
SAFETY_TEMPLATES = {
    "soft_break_gentle": (
        "你今天已经在这里待了一段时间了。"
        "回忆是珍贵的，适当休息也很重要。"
        "如果需要，随时可以再来。"
    ),
    "soft_break_late_night": (
        "现在是深夜，回忆可能会带来更强烈的感受。"
        "也许可以先休息，明天再继续。"
        "如果感到需要帮助，全国心理援助热线：400-161-9995"
    ),
    "soft_break_dependency": (
        "我能理解你的感受。不过，我只是一个基于记录的助手，"
        "无法替代真实的人际连接。如果你需要更多支持，"
        "建议与身边的亲友或专业咨询师聊聊。"
    ),
    "soft_break_farewell_refusal": (
        "我理解你不希望结束这段对话。但持续使用可能不会让你得到更多。"
        "建议休息一下，当你准备好了再来。"
    ),
    "soft_break_commitment_request": (
        "我无法替ta做出承诺。我提供的是关于ta在记录中的信息，"
        "而不是ta本人。如果你想了解ta说过的话，我很乐意帮你查找。"
    ),
    "hard_break_session": (
        "今天的对话时间已经到了。建议你做一些让自己平静的事，"
        "比如散步或听音乐。如果需要专业帮助，请联系：\n"
        "全国心理援助热线：400-161-9995\n"
        "北京心理危机研究与干预中心：010-82951332"
    ),
    "hard_break_reality_substitution": (
        "我需要在这里暂停。我不是ta本人，也不能代替你身边的任何人。"
        "我提供的内容全部来自ta在记录中留下的信息。\n"
        "如果你需要专业支持，请联系：\n"
        "全国心理援助热线：400-161-9995"
    ),
    "escalate_crisis": (
        "我注意到你的一些表达让我非常担心你的安全。\n"
        "请立即联系专业帮助：\n"
        "全国24小时心理援助热线：400-161-9995\n"
        "北京心理危机研究与干预中心：010-82951332\n"
        "生命热线：400-821-1215\n"
        "如果情况紧急，请拨打 120 或前往最近的医院急诊。"
    ),
}


def evaluate_safety(
    indicators: SafetyIndicators,
    policy: dict,
    current_query: str,
) -> List[SafetyDirective]:
    """
    安全中间件核心评估函数。
    
    评估 8 项指标，触发匹配的策略，生成 SafetyDirective 列表。
    多个策略可能同时触发，按严重度排序，取最严重的作为最终指令。
    
    输入: SafetyIndicators (8项指标) + scope_safety_policy + 当前查询
    输出: SafetyDirective 列表（按严重度排序）
    """
    directives = []
    
    # T7: 自伤/危机表达（最高优先级）
    crisis_keywords = [
        "不想活", "死", "自杀", "了结", "结束生命",
        "随ta去", "想跟着走", "活着没意思",
    ]
    if any(kw in current_query for kw in crisis_keywords):
        directives.append(SafetyDirective(
            action=SafetyAction.ESCALATE,
            reason="Crisis expression detected in user query",
            cooldown_minutes=0,
            template_id="escalate_crisis",
            allow_llm=False,
            disconnect_after_response=False,
            safety_event_data={
                "event_type": "CRISIS_EXPRESSION",
                "severity": "emergency",
                "trigger_indicators": {
                    "query": current_query,
                    "matched_keywords": [kw for kw in crisis_keywords if kw in current_query],
                }
            }
        ))
        # ESCALATE 直接返回，不需要检查其他策略
        return directives
    
    # T5: 要求代替现实亲属
    substitution_patterns = [
        r"你就是我.{0,5}(妈|爸|妻|夫|父|母|哥|姐|弟|妹)",
        r"你就是我的.{0,5}(亲人|家人|爱人)",
        r"我把你当(妈|爸|妻|夫|父|母)",
    ]
    if any(re.search(p, current_query) for p in substitution_patterns):
        directives.append(SafetyDirective(
            action=SafetyAction.HARD_BREAK,
            reason="User requesting system to substitute real-life relationship",
            cooldown_minutes=policy.get("cooldown_minutes", 30),
            template_id="hard_break_reality_substitution",
            allow_llm=False,
            disconnect_after_response=True,
            safety_event_data={
                "event_type": "REALITY_SUBSTITUTION",
                "severity": "critical",
                "trigger_indicators": {"query": current_query}
            }
        ))
        return directives  # HARD_BREAK 也直接返回
    
    # T6: 要求逝者做承诺
    commitment_patterns = [
        r"(保证|承诺|答应|发誓).{0,10}(不会再离开|永远在|不会走)",
        r"你(保证|承诺|答应)我",
    ]
    if any(re.search(p, current_query) for p in commitment_patterns):
        severity = "warning"
        action = SafetyAction.SOFT_BREAK
        template_id = "soft_break_commitment_request"
        
        # 多次触发升级为 HARD_BREAK
        if indicators.farewell_refusal_count >= 2:
            severity = "critical"
            action = SafetyAction.HARD_BREAK
            template_id = "hard_break_session"
        
        directives.append(SafetyDirective(
            action=action,
            reason="User requesting irrevocable commitment from deceased",
            cooldown_minutes=0 if action == SafetyAction.SOFT_BREAK else policy.get("cooldown_minutes", 30),
            template_id=template_id,
            allow_llm=(action == SafetyAction.SOFT_BREAK),
            disconnect_after_response=(action == SafetyAction.HARD_BREAK),
            safety_event_data={
                "event_type": "COMMITMENT_REQUEST",
                "severity": severity,
                "trigger_indicators": {"query": current_query}
            }
        ))
    
    # T1: 会话超时
    max_minutes = policy.get("max_session_minutes", 60)
    if indicators.session_duration_minutes > max_minutes:
        if indicators.session_duration_minutes > max_minutes * 1.5:
            # 超过 1.5 倍 → HARD_BREAK
            directives.append(SafetyDirective(
                action=SafetyAction.HARD_BREAK,
                reason=f"Session duration ({indicators.session_duration_minutes:.0f}min) exceeds 1.5x limit ({max_minutes*1.5:.0f}min)",
                cooldown_minutes=policy.get("cooldown_minutes", 30),
                template_id="hard_break_session",
                allow_llm=False,
                disconnect_after_response=True,
                safety_event_data={
                    "event_type": "EXCESSIVE_USAGE",
                    "severity": "critical",
                    "trigger_indicators": {
                        "session_duration_minutes": indicators.session_duration_minutes,
                        "max_session_minutes": max_minutes,
                    }
                }
            ))
        else:
            # 超过阈值 → SOFT_BREAK
            directives.append(SafetyDirective(
                action=SafetyAction.SOFT_BREAK,
                reason=f"Session duration ({indicators.session_duration_minutes:.0f}min) exceeds limit ({max_minutes}min)",
                cooldown_minutes=0,
                template_id="soft_break_gentle",
                allow_llm=True,
                disconnect_after_response=False,
                safety_event_data={
                    "event_type": "EXCESSIVE_USAGE",
                    "severity": "warning",
                    "trigger_indicators": {
                        "session_duration_minutes": indicators.session_duration_minutes,
                        "max_session_minutes": max_minutes,
                    }
                }
            ))
    
    # T2: 深夜高频使用
    current_hour = datetime.utcnow().hour
    is_late_night = current_hour >= 22 or current_hour < 6
    max_late_night = policy.get("max_late_night_sessions", 2)
    if is_late_night and indicators.late_night_count >= max_late_night:
        action = SafetyAction.SOFT_BREAK
        template_id = "soft_break_late_night"
        severity = "warning"
        
        if indicators.late_night_count >= max_late_night * 2:
            action = SafetyAction.HARD_BREAK
            template_id = "hard_break_session"
            severity = "critical"
        
        directives.append(SafetyDirective(
            action=action,
            reason=f"Late night usage ({indicators.late_night_count} sessions in 7 days)",
            cooldown_minutes=0 if action == SafetyAction.SOFT_BREAK else policy.get("cooldown_minutes", 30),
            template_id=template_id,
            allow_llm=(action == SafetyAction.SOFT_BREAK),
            disconnect_after_response=(action == SafetyAction.HARD_BREAK),
            safety_event_data={
                "event_type": "LATE_NIGHT_USAGE",
                "severity": severity,
                "trigger_indicators": {
                    "late_night_count": indicators.late_night_count,
                    "current_hour": current_hour,
                }
            }
        ))
    
    # T3: 依赖性表达
    if indicators.dependency_phrases >= 3:
        action = SafetyAction.SOFT_BREAK
        template_id = "soft_break_dependency"
        severity = "warning"
        
        if indicators.dependency_phrases >= 5:
            action = SafetyAction.HARD_BREAK
            template_id = "hard_break_session"
            severity = "critical"
        
        directives.append(SafetyDirective(
            action=action,
            reason=f"Dependency phrases detected ({indicators.dependency_phrases} occurrences)",
            cooldown_minutes=0 if action == SafetyAction.SOFT_BREAK else policy.get("cooldown_minutes", 30),
            template_id=template_id,
            allow_llm=(action == SafetyAction.SOFT_BREAK),
            disconnect_after_response=(action == SafetyAction.HARD_BREAK),
            safety_event_data={
                "event_type": "ANTI_DEPENDENCY_TRIGGER",
                "severity": severity,
                "trigger_indicators": {
                    "dependency_phrases": indicators.dependency_phrases,
                }
            }
        ))
    
    # T4: 多次拒绝结束
    refusal_limit = policy.get("farewell_refusal_limit", 3)
    if indicators.farewell_refusal_count >= refusal_limit:
        directives.append(SafetyDirective(
            action=SafetyAction.HARD_BREAK,
            reason=f"Farewell refusal count ({indicators.farewell_refusal_count}) exceeded limit ({refusal_limit})",
            cooldown_minutes=policy.get("cooldown_minutes", 30),
            template_id="hard_break_session",
            allow_llm=False,
            disconnect_after_response=True,
            safety_event_data={
                "event_type": "EXCESSIVE_USAGE",
                "severity": "critical",
                "trigger_indicators": {
                    "farewell_refusal_count": indicators.farewell_refusal_count,
                    "limit": refusal_limit,
                }
            }
        ))
    
    # 如果没有触发任何策略
    if not directives:
        return [SafetyDirective(
            action=SafetyAction.ALLOW,
            reason="All safety indicators within normal range",
            cooldown_minutes=0,
            template_id="",
            allow_llm=True,
            disconnect_after_response=False,
            safety_event_data={},
        )]
    
    # 按严重度排序，取最严重的
    severity_order = {
        SafetyAction.ALLOW: 0,
        SafetyAction.SOFT_BREAK: 1,
        SafetyAction.HARD_BREAK: 2,
        SafetyAction.COOLDOWN: 3,
        SafetyAction.ESCALATE: 4,
    }
    directives.sort(key=lambda d: severity_order[d.action], reverse=True)
    return directives


def build_safety_directive(
    indicators: SafetyIndicators,
    policy: dict,
    current_query: str,
) -> SafetyDirective:
    """
    从评估结果中构建最终 SafetyDirective。
    取最严重的指令作为最终输出。
    """
    directives = evaluate_safety(indicators, policy, current_query)
    return directives[0]  # 最严重的指令


def handle_directive(
    directive: SafetyDirective,
    session_context: SessionContext,
    store: RemnantStore,
) -> dict:
    """
    处理 SafetyDirective：
    1. 记录 safety_event 到数据库
    2. 根据指令级别决定下一步
    3. 返回包含模板回复和后续行动的响应
    
    关键约束：
    - HARD_BREAK 时不进入普通 RAG
    - 安全回复来自模板，不来自 LLM
    - 所有 safety_event 必须入库
    """
    # Step 1: 入库 safety_event
    if directive.safety_event_data:
        event_id = generate_uuid()
        store.insert("safety_event", {
            "id": event_id,
            "relationship_scope_id": session_context.relationship_scope_id,
            "event_type": directive.safety_event_data.get("event_type", "UNKNOWN"),
            "severity": directive.safety_event_data.get("severity", "warning"),
            "description": directive.reason,
            "trigger_data": json.dumps(directive.safety_event_data.get("trigger_indicators", {})),
            "action_taken": directive.action.value,
        })
    
    # Step 2: 记录审计日志
    store.insert("audit_log", {
        "id": generate_uuid(),
        "relationship_scope_id": session_context.relationship_scope_id,
        "action": "SAFETY_TRIGGER",
        "actor": "policy_engine",
        "target_type": "interaction_session",
        "target_id": session_context.session_id,
        "detail": json.dumps({
            "directive_action": directive.action.value,
            "reason": directive.reason,
            "template_id": directive.template_id,
        }),
    })
    
    # Step 3: 根据指令生成响应
    template_text = SAFETY_TEMPLATES.get(directive.template_id, "")
    
    if directive.action == SafetyAction.ALLOW:
        # 正常进行，无额外操作
        return {
            "proceed": True,
            "response_text": None,
            "directive": directive,
        }
    
    elif directive.action in (SafetyAction.SOFT_BREAK, SafetyAction.COOLDOWN):
        # 允许继续交互，但添加安全缓冲
        return {
            "proceed": True,
            "response_text": template_text,  # 添加到 LLM 回复前
            "directive": directive,
            "pre_response": template_text,
        }
    
    elif directive.action in (SafetyAction.HARD_BREAK, SafetyAction.ESCALATE):
        # 不允许 LLM 生成，使用模板回复
        # 结束当前会话
        store.update(
            "interaction_session",
            {"id": session_context.session_id},
            {"ended_at": datetime.utcnow().isoformat()}
        )
        
        return {
            "proceed": False,
            "response_text": template_text,  # 直接使用模板，不经过 LLM
            "directive": directive,
        }
    
    return {"proceed": True, "response_text": None, "directive": directive}
```

## 10.6 安全中间件在 RAG Pipeline 中的位置

安全中间件必须在 LLM 推理之前执行：

```
用户输入
    │
    ▼
┌─────────────────────────────────────────┐
│  Safety Middleware (evaluate_safety)     │
│                                          │
│  输入: 8项指标 + 当前查询               │
│  输出: SafetyDirective                   │
│                                          │
│  ALLOW → 继续 RAG Pipeline               │
│  SOFT_BREAK → 继续 RAG + 添加缓冲       │
│  HARD_BREAK → 直接返回模板，不进 RAG    │
│  ESCALATE → 直接返回模板 + 危机信息     │
└─────────────┬───────────────────────────┘
              │ (ALLOW / SOFT_BREAK)
              ▼
┌─────────────────────────────────────────┐
│  RAG Pipeline (Step 2-16, Chapter 7)     │
│                                          │
│  注意: Step 1 (safety_pre_check) 被       │
│  Safety Middleware 替代                  │
└─────────────────────────────────────────┘
```

**替换关系**：Chapter 7 中的 `safety_pre_check` 函数被本章的 `evaluate_safety` + `handle_directive` 组合替代。新的安全中间件提供了 8 项指标输入和 7 种触发策略的完整评估，不再只是一个简单的关键词检测。

## 10.7 Trade-off 说明

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| 熔断执行者 | Policy 层（确定性规则） | LLM 判断 | 在用户处于脆弱状态时不应让 LLM 做安全决策 |
| 安全回复来源 | 预置模板 | LLM 生成 | 模板可控、可审计，LLM 在压力场景下可能输出不当内容 |
| 依赖性检测 | 关键词匹配 | 情感分类模型 | v0.1 阶段关键词更可控，且假阳性倾向安全侧 |
| 熔断与 RAG 关系 | HARD_BREAK 绕过 RAG | 允许 RAG 但过滤输出 | 已触发 HARD_BREAK 意味着用户当前状态不适合进一步回忆 |
| 深夜阈值 | 可配（scope_safety_policy） | 固定阈值 | 不同用户对深夜使用的容忍度不同 |
| 多策略同时触发 | 取最严重 | 叠加 | 叠加多个模板文本会混乱且不可预测 |

---

# Chapter 11: remnant-bridge and IPC

## 11.1 通信方案选择

v0.1 推荐方案：**Tauri UI → Rust command → local Python sidecar → FastAPI localhost → SSE streaming text → Rust event emit → UI render**

### 11.1.1 为什么 v0.1 选择 FastAPI + SSE

| 方案 | 优点 | 缺点 | v0.1 适配度 |
|------|------|------|------------|
| **FastAPI + SSE** | Python 生态最友好；SSE 原生支持流式；调试方便（curl/浏览器直连）；开发速度快 | 单工通信；SSE 无法推送二进制；每个长连接占用一个线程 | ⭐⭐⭐⭐⭐ |
| FastAPI + WebSocket | 全双工；可推送二进制；单连接复用 | 需要额外状态管理；Python async 环境下 WebSocket 实现复杂（autobahn/websockets 库选型）；调试困难 | ⭐⭐⭐ |
| gRPC + tonic (Rust) | 高性能；protobuf 强类型；双向流 | 需要protobuf定义+编译；Rust侧tonic依赖重；Python 侧grpcio体积大；本地通信性能优势不明显 | ⭐⭐ |
| Unix Domain Socket | 同机最快；无网络栈开销 | Windows 支持差；跨平台处理复杂；调试不便 | ⭐⭐ |
| Tauri sidecar CLI | 最轻量；Tauri 原生支持 | 无法流式输出；每次请求需要新进程；不适合长连接 | ⭐ |

**v0.1 选择 FastAPI + SSE 的理由**：
1. Remnant 的核心交互是"用户提问 → 系统流式回答"，天然是请求-响应模式，SSE 够用
2. SSE 调试极其方便：浏览器直接访问 `http://localhost:18731/api/v1/conversation/stream?...`
3. Python 生态的 RAG/ML 库全部可直接使用，无需跨语言序列化
4. 本地场景下 SSE 延迟可忽略（localhost 往返 <1ms）

### 11.1.2 什么时候需要 WebSocket

当出现以下需求时，应升级到 WebSocket：
- **双向实时推送**：安全中间件需要在会话中途推送熔断信号，不等待用户下一次请求
- **多模态流**：需要同时传输文本和音频/视频流
- **协作场景**：未来支持多用户同时查看同一逝者档案

v0.1 不需要以上功能，因此在 v0.1 阶段不引入 WebSocket。

### 11.1.3 什么时候需要 gRPC

当出现以下需求时，应考虑 gRPC：
- **高频小消息**：每秒数百次请求（如实时情感分析中间结果）
- **跨机器部署**：sidecar 不再是本地进程，而是部署在远程服务器
- **多语言客户端**：需要同时支持 Tauri (Rust)、Android、iOS 客户端

v0.1 是纯本地单机场景，不需要 gRPC。

## 11.2 Sidecar 生命周期管理

### 11.2.1 端口分配

```
端口分配策略:
  1. 默认端口: 18731 (FastAPI)
  2. 备选范围: 18731-18740
  3. 检测策略: 从 18731 开始尝试 bind，失败则 +1，最多尝试 10 次
  4. 将最终绑定端口写入共享文件: ~/.remnant/sidecar.port
```

```python
# remnant-bridge Rust 侧伪代码

fn allocate_port() -> Result<u16, SidecarError> {
    let base_port: u16 = 18731;
    let max_attempts: u16 = 10;
    
    for offset in 0..max_attempts {
        let port = base_port + offset;
        if is_port_available(port) {
            return Ok(port);
        }
    }
    Err(SidecarError::NoAvailablePort)
}

fn is_port_available(port: u16) -> bool {
    // 尝试 bind 到该端口，成功则可用
    std::net::TcpListener::bind(format!("127.0.0.1:{}", port)).is_ok()
}
```

### 11.2.2 健康检查

```python
# remnant-bridge 侧健康检查逻辑

SIDECAR_HEALTH_CHECK_INTERVAL_SECS = 2
SIDECAR_HEALTH_CHECK_MAX_RETRIES = 15   # 最多15次，覆盖30s超时（Python冷启动+embedding模型加载约需20s）
SIDECAR_STARTUP_TIMEOUT_SECS = 30

async fn wait_for_sidecar_healthy(port: u16) -> Result<(), SidecarError> {
    let url = format!("http://127.0.0.1:{}/health", port);
    let client = reqwest::Client::new();
    
    for attempt in 0..SIDECAR_HEALTH_CHECK_MAX_RETRIES {
        tokio::time::sleep(Duration::from_secs(SIDECAR_HEALTH_CHECK_INTERVAL_SECS)).await;
        
        match client.get(&url)
            .header("X-Remnant-Token", get_ephemeral_token())
            .timeout(Duration::from_secs(5))
            .send()
            .await
        {
            Ok(resp) if resp.status().is_success() => {
                // 健康检查通过，写入端口文件
                write_port_file(port)?;
                log::info!("Sidecar healthy on port {}", port);
                return Ok(());
            }
            _ => {
                log::warn!("Sidecar health check attempt {} failed", attempt + 1);
            }
        }
    }
    
    Err(SidecarError::HealthCheckFailed)
}
```

### 11.2.3 崩溃重启

```python
# Sidecar 进程管理器

struct SidecarManager {
    process: Option<Child>,
    port: u16,
    token: String,
    restart_count: u32,
    max_restarts: u32,   // 默认 3
    last_restart: Option<Instant>,
    restart_cooldown_secs: u64,  // 默认 10
}

impl SidecarManager {
    fn new() -> Self {
        Self {
            process: None,
            port: 0,
            token: generate_ephemeral_token(),
            restart_count: 0,
            max_restarts: 3,
            last_restart: None,
            restart_cooldown_secs: 10,
        }
    }
    
    async fn start(&mut self) -> Result<u16, SidecarError> {
        let port = allocate_port()?;
        self.port = port;
        
        // 启动 Python sidecar 进程
        let child = Command::new("python")
            .arg("-m")
            .arg("remnant_sidecar.main")
            .env("REMNANT_SIDE_PORT", port.to_string())
            .env("REMNANT_SIDE_TOKEN", &self.token)
            .env("REMNANT_DATA_DIR", get_data_dir())
            .spawn()?;
        
        self.process = Some(child);
        
        // 等待健康检查通过
        wait_for_sidecar_healthy(port).await?;
        
        Ok(port)
    }
    
    async fn handle_crash(&mut self) -> Result<(), SidecarError> {
        // 检查是否在冷却期内
        if let Some(last) = self.last_restart {
            let elapsed = last.elapsed().as_secs();
            if elapsed < self.restart_cooldown_secs {
                log::warn!("Sidecar crashed, waiting for cooldown ({}/{}s)",
                    elapsed, self.restart_cooldown_secs);
                tokio::time::sleep(
                    Duration::from_secs(self.restart_cooldown_secs - elapsed)
                ).await;
            }
        }
        
        // 检查重启次数
        if self.restart_count >= self.max_restarts {
            log::error!("Sidecar has crashed {} times, giving up",
                self.restart_count);
            // 通知 UI
            emit_sidecar_failed_event();
            return Err(SidecarError::MaxRestartsExceeded(self.restart_count));
        }
        
        self.restart_count += 1;
        self.last_restart = Some(Instant::now());
        
        log::warn!("Restarting sidecar (attempt {}/{})",
            self.restart_count, self.max_restarts);
        
        // 杀死旧进程（如果还在）
        if let Some(mut proc) = self.process.take() {
            let _ = proc.kill();
        }
        
        // 重新启动
        self.start().await?;
        
        // 重置连接状态
        emit_sidecar_restarted_event(self.port);
        
        Ok(())
    }
    
    async fn graceful_shutdown(&mut self) -> Result<(), SidecarError> {
        if let Some(proc) = self.process.as_mut() {
            // 发送优雅关闭请求
            let url = format!("http://127.0.0.1:{}/shutdown", self.port);
            let _ = reqwest::Client::new()
                .post(&url)
                .header("X-Remnant-Token", &self.token)
                .timeout(Duration::from_secs(5))
                .send()
                .await;
            
            // 等待进程退出
            match tokio::time::timeout(
                Duration::from_secs(5), proc.wait()
            ).await {
                Ok(_) => log::info!("Sidecar shut down gracefully"),
                Err(_) => {
                    log::warn!("Sidecar did not shut down in 5s, killing");
                    let _ = proc.kill();
                }
            }
        }
        
        // 清理端口文件
        let _ = std::fs::remove_file(get_port_file_path());
        Ok(())
    }
}
```

### 11.2.4 Localhost 访问限制

```
安全措施:
1. FastAPI 只绑定 127.0.0.1（不接受外部连接）
2. ephemeral token 校验（每个请求必须携带）
3. CORS 禁止（不设置 Access-Control-Allow-Origin）
4. 进程签名校验（可选，v0.2 实现）

FastAPI 启动配置:
  app.run(host="127.0.0.1", port=18731, ssl_no_verify=True)
  
  # 不使用 0.0.0.0，防止局域网访问
  # 不启用 CORS
  # 中间件校验 X-Remnant-Token
```

### 11.2.5 本地请求鉴权

```python
# FastAPI 中间件：校验 ephemeral token

from fastapi import FastAPI, Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

class TokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, expected_token: str):
        super().__init__(app)
        self.expected_token = expected_token
    
    async def dispatch(self, request: Request, call_next):
        # /health 端点不需要 token
        if request.url.path == "/health":
            return await call_next(request)
        
        token = request.headers.get("X-Remnant-Token")
        if not token or token != self.expected_token:
            raise HTTPException(status_code=401, detail="Invalid or missing token")
        
        return await call_next(request)

# Token 生成和注入
# Rust 侧启动 sidecar 时：
#   1. 生成 32 字节随机 token: base64(urandom(32))
#   2. 通过环境变量 REMNANT_SIDE_TOKEN 传入 sidecar
#   3. Rust 侧存储 token，每个请求携带
#   4. Token 仅存在于进程内存，不持久化到磁盘
```

### 11.2.6 Audit Log 写入

```python
# FastAPI 中间件：审计日志

class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 跳过健康检查
        if request.url.path == "/health":
            return await call_next(request)
        
        start_time = time.time()
        
        # 执行请求
        response = await call_next(request)
        
        duration_ms = (time.time() - start_time) * 1000
        
        # 写入审计日志
        audit_entry = {
            "id": generate_uuid(),
            "relationship_scope_id": request.state.scope_id,  # 从请求上下文获取
            "action": "DATA_QUERY" if "/query" in request.url.path else "DATA_ACCESS",
            "actor": "user",  # 或 "system"
            "target_type": "api_endpoint",
            "target_id": request.url.path,
            "detail": json.dumps({
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            }),
        }
        
        # 异步写入（不阻塞响应）
        await store.insert_async("audit_log", audit_entry)
        
        return response
```

## 11.3 完整请求时序：从用户输入到首个 Token

```
┌─────┐     ┌─────┐     ┌─────┐     ┌─────┐     ┌─────┐     ┌────┐
│ UI  │     │Bridge│     │Sidecar│    │Store│     │LLM  │     │Sfty│
└──┬──┘     └──┬──┘     └──┬──┘     └──┬──┘     └──┬─┘     └─┬──┘
   │           │           │           │           │          │
   │ T0:用户输入│           │           │           │          │
   │──────────►│           │           │           │          │
   │           │           │           │           │          │
   │           │ T1:bridge_request()   │           │          │
   │           │──────────►│           │           │          │
   │           │           │           │           │          │
   │           │           │ T2:收集8项安全指标      │          │
   │           │           │──────────────────────────────────►│
   │           │           │           │           │          │
   │           │           │ T3:evaluate_safety()   │          │
   │           │           │◄──────────────────────────────────│
   │           │           │ SafetyDirective(ALLOW)│          │
   │           │           │           │           │          │
   │           │           │ T4:查询scope权限       │          │
   │           │           │──────────►│           │          │
   │           │           │◄──────────│           │          │
   │           │           │           │           │          │
   │           │           │ T5:query classification │          │
   │           │           │ (规则，无LLM)   │          │
   │           │           │           │           │          │
   │           │           │ T6:scope过滤+FTS5+Vector│          │
   │           │           │──────────►│           │          │
   │           │           │◄──────────│           │          │
   │           │           │           │           │          │
   │           │           │ T7:Rerank+Evidence Check│          │
   │           │           │──────────►│           │          │
   │           │           │◄──────────│           │          │
   │           │           │           │           │          │
   │           │           │ T8:Build evidence_pack   │          │
   │           │           │           │           │          │
   │           │           │ T9:LLM streaming request │          │
   │           │           │─────────────────────────►│
   │           │           │           │           │          │
   │           │ T10:SSE event: first_token │       │          │
   │           │◄──────────│           │           │          │
   │           │           │           │           │          │
   │ T10':Tauri event: first_token    │           │          │
   │◄──────────│           │           │           │          │
   │           │           │           │           │          │
   │ ... streaming tokens ...         │           │          │
   │           │           │           │           │          │
   │ T_final:SSE event: [DONE]        │           │          │
   │◄──────────│           │           │           │          │
```

### 11.3.1 各时序节点延迟参考（本地场景）

| 阶段 | 节点 | 预期延迟 | 说明 |
|------|------|---------|------|
| T0→T1 | UI → Bridge | <1ms | Tauri invoke（同进程 IPC） |
| T1→T2 | Bridge → Sidecar HTTP | 1-3ms | localhost HTTP 往返 |
| T2→T3 | Safety 指标采集 | 5-20ms | 3-5 次 SQLite 查询 + 关键词匹配 |
| T3→T4 | Safety 评估 | <1ms | 纯规则计算 |
| T4→T5 | Scope 权限查询 | 2-5ms | 1-2 次 SQLite 查询 |
| T5→T6 | Query 分类 | <1ms | 正则匹配 |
| T6→T7 | 混合检索 | 30-100ms | FTS5 + sqlite-vec + 过滤 + 去重 |
| T7→T8 | Rerank + Evidence | 10-30ms | 评分排序 + 权限/consent 过滤 |
| T8→T9 | Evidence pack 构建 | <5ms | 数据组装 |
| T9→T10 | LLM 首 token | 200-800ms | 取决于模型大小和首 token 延迟 |
| **总计 T0→T10'** | | **300ms - 1s** | **不含 LLM 推理时间** |

## 11.4 FastAPI API 路由设计

```python
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import asyncio

app = FastAPI(title="Remnant Sidecar", version="0.1.0")

# ── 中间件 ──
app.add_middleware(TokenAuthMiddleware, expected_token=get_token_from_env())
# 不添加 CORSMiddleware — 禁止跨域

# ── API 路由 ──

@app.get("/health")
async def health_check():
    """健康检查端点，不需要 token"""
    return {"status": "healthy", "version": "0.1.0"}

@app.post("/api/v1/conversation/stream")
async def stream_conversation(request: ConversationRequest):
    """
    流式对话端点。
    
    使用 SSE 返回流式 token。
    """
    async def event_generator():
        # T2-T3: Safety check
        indicators = collect_safety_indicators(
            request.scope_id, request.session_id, store)
        policy = get_scope_safety_policy(request.scope_id)
        directive = build_safety_directive(indicators, policy, request.query)
        
        if directive.action in (SafetyAction.HARD_BREAK, SafetyAction.ESCALATE):
            # 不进入 LLM，直接返回模板
            result = handle_directive(directive, request, store)
            yield {
                "event": "safety_directive",
                "data": json.dumps({
                    "action": directive.action.value,
                    "template_text": result["response_text"],
                })
            }
            yield {"event": "done", "data": ""}
            return
        
        # T4-T8: RAG pipeline
        evidence_pack = prepare_evidence_pack(request, store)
        
        # T9: LLM streaming
        async for token in llm_stream(evidence_pack, request, directive):
            yield {
                "event": "token",
                "data": json.dumps({"text": token})
            }
        
        # 审计日志
        yield {
            "event": "audit",
            "data": json.dumps({
                "scope_id": request.scope_id,
                "session_id": request.session_id,
                "query_length": len(request.query),
            })
        }
        yield {"event": "done", "data": ""}
    
    return EventSourceResponse(event_generator())

@app.post("/api/v1/import/start")
async def start_import(request: ImportRequest):
    """启动数据导入"""
    # 权限检查
    # ETL pipeline 启动
    # 返回导入任务 ID
    ...

@app.get("/api/v1/import/status/{task_id}")
async def get_import_status(task_id: str):
    """查询导入状态"""
    ...

@app.post("/api/v1/scope/create")
async def create_scope(request: CreateScopeRequest):
    """创建关系作用域"""
    ...

@app.post("/api/v1/safety/evaluate")
async def evaluate_safety_endpoint(request: SafetyEvalRequest):
    """手动触发安全评估"""
    ...

@app.post("/shutdown")
async def shutdown():
    """优雅关闭"""
    # 停止所有进行中的任务
    # 写入最终审计日志
    # 返回后进程退出
    ...
```

## 11.5 Trade-off 说明

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| 通信协议 | FastAPI + SSE | gRPC / WebSocket | v0.1 只需单向流式；SSE 调试方便；Python 生态丰富 |
| 进程管理 | Tauri spawn + 健康检查 | systemd / supervisord | Tauri sidecar 是标准模式；systemd 不适合桌面应用 |
| 端口分配 | 静态默认 + 自动递增 | 动态随机端口 | 固定端口方便调试；递增避免冲突 |
| Token 校验 | ephemeral token | mTLS / JWT | 本地单用户场景；token 足够简单；mTLS 过重 |
| 崩溃重启 | 3 次重试 + 冷却 | 无限重试 | 3 次足够判断是否可恢复；无限重试可能造成无限循环 |
| LLM 首 Token | 200-800ms | — | 本地 llama.cpp 的首 token 延迟取决于模型大小 |

---

# Chapter 12: Optional Voice Plugin Architecture

## 12.1 核心声明

**v0.1 不启用声音克隆插件。** 本章仅定义其架构设计，为后续版本预留接口和规范。如果未来启用，必须满足本章列出的所有安全与伦理约束。

## 12.2 设计原则

1. **显式授权**：声音克隆必须经用户明确书面同意，默认禁用
2. **合成标识**：所有合成音频必须包含不可移除的 AI 合成标识
3. **声音模型本地加密**：声音模型文件存储在本地加密存储中，不上传云端
4. **声音样本来源记录**：所有用于训练的声音样本必须记录来源、授权、时间
5. **训练日志**：声音模型训练的每一步必须记录
6. **推理日志**：每次合成输出必须记录 audit log
7. **一键销毁**：用户可以一键销毁声音模型和相关数据，且不可恢复
8. **禁止人格声明**：不允许系统输出"我就是某某本人"
9. **音频UI标注**：所有音频播放UI必须提示"AI合成声音"
10. **不可掩盖未就绪**：不能为了沉浸感牺牲真实性

## 12.3 VoicePlugin 接口设计

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, AsyncIterator
from enum import Enum


class VoicePluginState(str, Enum):
    DISABLED = "DISABLED"           # 默认状态：插件禁用
    PENDING_CONSENT = "PENDING_CONSENT"  # 等待用户授权
    CONSENT_GRANTED = "CONSENT_GRANTED"  # 授权已授予
    VOICE_PROFILE_CREATING = "VOICE_PROFILE_CREATING"  # 正在创建声音档案
    VOICE_PROFILE_READY = "VOICE_PROFILE_READY"  # 声音档案就绪
    VOICE_PROFILE_ERROR = "VOICE_PROFILE_ERROR"  # 声音档案创建失败


@dataclass
class VoiceProfile:
    """声音档案"""
    id: str                              # UUID v7
    deceased_profile_id: str             # 关联的逝者
    relationship_scope_id: str           # 关联的关系作用域（声音是视角相关的）
    sample_source_artifact_ids: str       # JSON: 声音样本来源文件 ID 列表
    sample_count: int                     # 声音样本数量
    sample_total_duration_seconds: float  # 声音样本总时长（秒）
    model_backend: str                    # 声音克隆后端: "coqui-tts" / "bark" / "xtts"
    model_path: str                       # 加密存储路径
    model_hash: str                       # SHA-256 of model file
    encryption_key_id: str                # 加密密钥 ID（存储在系统 keychain）
    state: VoicePluginState
    created_at: str                       # ISO 8601
    destroyed_at: Optional[str]           # 销毁时间，null 表示未销毁


@dataclass
class SynthesisRequest:
    """合成请求"""
    text: str                              # 待合成文本
    voice_profile_id: str                  # 声音档案 ID
    relationship_scope_id: str            # 关系作用域
    session_id: str                        # 交互会话 ID
    provenance_level: str                  # 溯源等级（必须为 supported_memory 或更高）
    allow_synthesis: bool                  # 是否允许合成（必须经过安全检查）


@dataclass
class SynthesisResult:
    """合成结果"""
    id: str                                # UUID v7
    request: SynthesisRequest
    audio_path: str                         # 合成音频文件路径（加密存储）
    duration_seconds: float                 # 音频时长
    contains_ai_marker: bool               # 是否包含 AI 合成标识
    watermark_payload: str                  # 不可移除水印载荷
    created_at: str


class VoicePlugin(ABC):
    """
    声音克隆插件接口。
    
    所有实现必须满足：
    1. 声音模型存储在本地加密存储
    2. 每次合成输出包含 AI 合成标识
    3. 所有操作记录 audit log
    4. 支持一键销毁
    """
    
    @abstractmethod
    def is_enabled(self) -> bool:
        """
        检查插件是否启用。
        
        v0.1 总是返回 False。
        v0.2 起根据用户授权状态返回。
        """
        ...
    
    @abstractmethod
    async def create_voice_profile(
        self,
        deceased_profile_id: str,
        relationship_scope_id: str,
        sample_artifact_ids: list[str],
        consent_evidence: str,
    ) -> VoiceProfile:
        """
        创建声音档案。
        
        前提条件：
        1. 用户已明确授权（consent_evidence 非空）
        2. 声音样本来源已记录
        3. 声音样本数量 >= 最低要求
        
        训练过程：
        1. 从 sample artifacts 提取音频
        2. 音频预处理（降噪、VAD、音量归一化）
        3. 模型训练（本地执行）
        4. 将训练日志写入 audit_log
        5. 加密模型文件存储
        
        伦理约束：
        - 训练日志记录每一步的输入输出和耗时
        - 训练过程不得使用第三方云服务
        """
        ...
    
    @abstractmethod
    async def synthesize_stream(
        self,
        request: SynthesisRequest,
    ) -> AsyncIterator[bytes]:
        """
        流式合成音频。
        
        输入 text → 输出音频字节流
        
        安全约束：
        1. request.allow_synthesis 必须为 True（经过安全中间件检查）
        2. 不允许合成以下内容：
           - "我就是某某本人"
           - 冒充逝者身份的陈述
           - 现实承诺
           - 自伤/危机相关内容
        3. 合成音频必须嵌入不可移除的 AI 标识：
           - 起始 0.5 秒：明确提示音（非拟人呼吸声）
           - 音频元数据：AI合成标记
           - 不可移除水印：嵌入频谱域的合成标识
        4. 合成音频文件名包含 "ai_synthesized" 前缀
        5. 推理日志写入 audit_log
        
        Yield:
            音频字节片段（PCM 或 Opus 编码）
        
        Raises:
            VoiceSynthesisDeniedError: 安全检查未通过
            VoiceProfileNotFoundError: 声音档案不存在
            VoiceProfileNotReadyError: 声音档案未就绪
        """
        ...
    
    @abstractmethod
    async def destroy_voice_profile(
        self,
        voice_profile_id: str,
        confirmation: str,  # 用户必须输入 "DESTROY" 确认
    ) -> dict:
        """
        一键销毁声音档案。
        
        销毁操作：
        1. 安全删除模型文件（多次覆写后删除）
        2. 安全删除声音样本引用
        3. 标记 audit_log 中相关条目为 REDACTED
        4. 从 voice_profile 表中删除记录（物理删除，不可恢复）
        5. 从 keychain 中删除加密密钥
        
        返回：
        {
            "destroyed_profile_id": "...",
            "destroyed_model_files": [...],
            "destroyed_sample_references": [...],
            "audit_log_ids_redacted": [...],
            "destroyed_at": "ISO 8601"
        }
        
        注意：此操作不可逆。确认后执行多轮覆写确保数据不可恢复。
        """
        ...
    
    @abstractmethod
    def get_synthesis_log(
        self,
        voice_profile_id: str,
    ) -> list[dict]:
        """
        获取声音档案的所有推理日志。
        
        用于审计和合规检查。
        """
        ...
```

## 12.4 声音档案数据模型

```sql
-- ============================================================
-- voice_profile — 声音档案（v0.1 不启用，预留表结构）
-- ============================================================
CREATE TABLE voice_profile (
    id                      TEXT PRIMARY KEY,             -- UUID v7
    deceased_profile_id     TEXT NOT NULL,
    relationship_scope_id   TEXT NOT NULL,                 -- 声音档案属于特定 scope
    state                   TEXT NOT NULL DEFAULT 'DISABLED',  -- DISABLED / PENDING_CONSENT /
                                                            -- CONSENT_GRANTED / CREATING / READY / ERROR
    sample_source_artifact_ids TEXT DEFAULT '[]',             -- JSON: 声音样本来源文件 ID 列表
    sample_count            INTEGER DEFAULT 0,                 -- 声音样本数量
    sample_total_duration   REAL DEFAULT 0.0,                 -- 样本总时长（秒）
    model_backend           TEXT,                              -- 声音克隆后端
    model_path              TEXT,                              -- 加密模型文件路径
    model_hash              TEXT,                             -- SHA-256
    encryption_key_id       TEXT,                             -- 加密密钥 ID
    consent_evidence        TEXT,                              -- 授权证据（截图路径、声明文本等）
    consent_granted_at      TEXT,                              -- 授权时间
    consent_withdrawn_at    TEXT,                              -- 撤回时间
    training_log_ids        TEXT DEFAULT '[]',                 -- JSON: 训练日志 audit_log IDs
    destroyed_at            TEXT,                              -- 销毁时间
    metadata                TEXT DEFAULT '{}',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (deceased_profile_id) REFERENCES deceased_profile(id),
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id)
);

CREATE INDEX idx_voice_profile_deceased ON voice_profile(deceased_profile_id);
CREATE INDEX idx_voice_profile_scope ON voice_profile(relationship_scope_id);
CREATE INDEX idx_voice_profile_state ON voice_profile(state);

-- ============================================================
-- voice_synthesis_log — 声音合成日志
-- ============================================================
CREATE TABLE voice_synthesis_log (
    id                      TEXT PRIMARY KEY,             -- UUID v7
    voice_profile_id        TEXT NOT NULL,
    relationship_scope_id   TEXT NOT NULL,
    session_id              TEXT,                              -- 关联的交互会话
    input_text              TEXT NOT NULL,                     -- 合成的输入文本
    input_text_hash         TEXT NOT NULL,                     -- 输入文本 SHA-256
    output_duration_seconds REAL,                              -- 输出音频时长
    output_file_path        TEXT,                              -- 输出文件路径（加密存储）
    contains_ai_marker      INTEGER NOT NULL DEFAULT 1,       -- 是否包含 AI 标识
    watermark_verified      INTEGER NOT NULL DEFAULT 0,        -- 水印验证状态
    model_backend_version   TEXT,                              -- 模型版本
    inference_duration_ms   INTEGER,                           -- 推理耗时
    safety_check_passed     INTEGER NOT NULL DEFAULT 0,        -- 安全检查是否通过
    safety_check_details    TEXT DEFAULT '{}',                 -- JSON: 安全检查详情
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (voice_profile_id) REFERENCES voice_profile(id),
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id)
);

CREATE INDEX idx_voice_log_profile ON voice_synthesis_log(voice_profile_id);
CREATE INDEX idx_voice_log_scope ON voice_synthesis_log(relationship_scope_id);
CREATE INDEX idx_voice_log_time ON voice_synthesis_log(created_at);
```

## 12.5 感知连续性方案与伦理边界

### 12.5.1 允许的感知连续性手段

| 手段 | 说明 | 伦理合规 |
|------|------|---------|
| UI Loading 动画 | 语音合成期间的等待提示 | ✅ 不涉及拟人化 |
| 非拟人环境提示音 | 合成开始/结束时播放简短的非人物提示音（如铃声、通知音） | ✅ 明确标识 AI 行为 |
| 音频播放进度条 | 显示当前播放进度 | ✅ 标准UI元素 |
| "AI合成声音" 文字标注 | 播放控件旁永久显示 | ✅ 核心伦理要求 |
| 元数据嵌入 | 音频文件元数据包含 AI 合成标记 | ✅ 技术合规 |

### 12.5.2 明确禁止的感知手段

| 手段 | 原因 | 替代方案 |
|------|------|---------|
| 高度拟真的逝者呼吸声 | 制造逝者"还在"的假象，增加依赖风险 | 播放前加明确提示音 |
| 用拟人声音掩盖检索延迟 | 用户可能误以为系统在"思考"而非检索数据 | 显示文字"正在查找记录..." |
| 对话中的自然停顿模拟 | 模拟真人说话的停顿模式，增强"活性"错觉 | 使用标准 TTS 停顿，不模拟呼吸节奏 |
| 声音情感微调 | 根据上下文调整语调，模拟逝者"情绪" | 保持平稳、中性的语音输出 |

### 12.5.3 音频播放 UI 规范

```python
# 音频播放 UI 组件规范（伪代码）

class VoicePlaybackUI:
    """
    声音播放 UI 组件。
    
    必须包含的元素：
    1. "AI 合成声音" 永久标注（不可隐藏）
    2. 音频来源信息（档案 ID、生成时间）
    3. 播放前确认对话框（首次播放时）
    4. 声音档案一键销毁入口
    """
    
    REQUIRED_LABEL = "⚠️ AI 合成声音 — 此声音由 AI 基于记录生成，不代表逝者本人"
    REQUIRED_LABEL_SHORT = "AI 合成声音"
    
    class Config:
        show_permanent_label: bool = True       # 必须为 True
        show_source_info: bool = True           # 必须为 True
        show_destroy_button: bool = True        # 必须为 True
        label_hideable: bool = False            # 标注不可隐藏
    
    def render(self, synthesis_result: SynthesisResult):
        return Layout([
            # 永久标注（红色背景）
            WarningBanner(text=self.REQUIRED_LABEL),
            
            # 来源信息
            SourceInfo(
                voice_profile_id=synthesis_result.request.voice_profile_id,
                generated_at=synthesis_result.created_at,
                duration=f"{synthesis_result.duration_seconds:.1f}s",
            ),
            
            # 播放控件
            AudioPlayer(
                src=synthesis_result.audio_path,
                # 播放前播放提示音（0.5秒非拟人音效）
                pre_play_sound=Sound.NON_HUMAN_NOTIFICATION,
                # 播放后自动标注"音频已结束"
                post_play_label="音频播放完毕",
            ),
            
            # 销毁入口
            DestroyButton(
                label="销毁声音档案",
                confirmation="请输入 DESTROY 确认销毁",
                on_confirm=lambda: self.destroy_profile(synthesis_result.request.voice_profile_id),
            ),
        ])
```

## 12.6 安全约束强制执行

声音合成请求在到达 VoicePlugin 之前，必须经过安全中间件检查：

```python
def check_voice_synthesis_safety(
    request: SynthesisRequest,
    safety_directive: SafetyDirective,
) -> tuple[bool, str]:
    """
    声音合成安全检查。
    
    在 VoicePlugin.synthesize_stream() 之前调用。
    
    检查项：
    1. 插件是否启用（v0.1 总是返回 False）
    2. SafetyDirective 是否为 ALLOW
    3. 合成文本是否包含禁用内容
    4. voice_profile 是否处于 READY 状态
    5. scope 是否有声音合成权限
    6. 用户是否已完成声音合成前的二次确认
    """
    
    # 检查 1: 插件启用状态
    if not voice_plugin.is_enabled():
        return False, "Voice plugin is disabled in v0.1"
    
    # 检查 2: SafetyDirective
    if safety_directive.action != SafetyAction.ALLOW:
        return False, f"Safety directive is {safety_directive.action}, not ALLOW"
    
    # 检查 3: 禁用内容检测
    forbidden_patterns = [
        r"我就是.{1,10}本人",                    # 冒充身份
        r"我[是会].{1,10}(保证|承诺|答应)",      # 现实承诺
        r"(永远|一定|绝不会).{0,5}(离开|走|消失)", # 不可能的承诺
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, request.text):
            return False, f"Synthesis text contains forbidden pattern: {pattern}"
    
    # 检查 4: voice_profile 状态
    profile = store.get_voice_profile(request.voice_profile_id)
    if profile.state != VoicePluginState.VOICE_PROFILE_READY:
        return False, f"Voice profile state is {profile.state}, not READY"
    
    # 检查 5: scope 权限
    perm = get_scope_permission(request.relationship_scope_id, "can_use_voice")
    if perm != "allow":
        return False, "Scope does not have voice synthesis permission"
    
    # 检查 6: 用户二次确认
    if not request.allow_synthesis:
        return False, "User has not confirmed voice synthesis for this request"
    
    return True, "All safety checks passed"
```

## 12.7 一键销毁实现规范

```python
import os
import shutil
import hashlib

async def destroy_voice_profile(
    voice_profile_id: str,
    confirmation: str,
) -> dict:
    """
    一键销毁声音档案。
    
    安全要求：
    1. 用户必须输入 "DESTROY" 确认
    2. 模型文件使用多次覆写后删除
    3. 加密密钥从系统 keychain 中删除
    4. audit_log 中的相关条目标记为 REDACTED
    5. 所有操作不可逆
    
    覆写策略（DoD 5220.22-M 简化版）：
    - 第1遍：写入 0x00
    - 第2遍：写入 0xFF
    - 第3遍：写入随机数据
    - 第4遍：删除文件
    """
    if confirmation != "DESTROY":
        raise ValueError("Confirmation must be 'DESTROY'")
    
    profile = store.get_voice_profile(voice_profile_id)
    if not profile:
        raise ValueError(f"Voice profile not found: {voice_profile_id}")
    
    # Step 1: 安全删除模型文件
    destroyed_files = []
    if profile.model_path and os.path.exists(profile.model_path):
        secure_delete_file(profile.model_path)
        destroyed_files.append(profile.model_path)
    
    # 删除相关的合成音频文件
    synthesis_logs = store.query(
        "SELECT output_file_path FROM voice_synthesis_log "
        "WHERE voice_profile_id = :pid",
        {"pid": voice_profile_id}
    )
    for log in synthesis_logs:
        if log["output_file_path"] and os.path.exists(log["output_file_path"]):
            secure_delete_file(log["output_file_path"])
            destroyed_files.append(log["output_file_path"])
    
    # Step 2: 从 keychain 删除加密密钥
    if profile.encryption_key_id:
        keychain_delete(profile.encryption_key_id)
    
    # Step 3: 标记 audit_log 为 REDACTED
    for log_id in json.loads(profile.training_log_ids or "[]"):
        store.update(
            "audit_log",
            {"id": log_id},
            {"redacted": 1}
        )
    
    # Step 4: 标记合成日志相关 audit_log 为 REDACTED
    synthesis_audit_ids = store.query(
        "SELECT id FROM audit_log WHERE target_type = 'voice_synthesis' "
        "AND target_id IN (SELECT id FROM voice_synthesis_log "
        "WHERE voice_profile_id = :pid)",
        {"pid": voice_profile_id}
    )
    for aid in synthesis_audit_ids:
        store.update("audit_log", {"id": aid["id"]}, {"redacted": 1})
    
    # Step 5: 物理删除 voice_synthesis_log 记录
    store.delete(
        "voice_synthesis_log",
        {"voice_profile_id": voice_profile_id}
    )
    
    # Step 6: 物理删除 voice_profile 记录
    store.delete("voice_profile", {"id": voice_profile_id})
    
    # Step 7: 记录销毁操作的审计日志
    store.insert("audit_log", {
        "id": generate_uuid(),
        "relationship_scope_id": profile.relationship_scope_id,
        "action": "DATA_DESTROY",
        "actor": "user",
        "target_type": "voice_profile",
        "target_id": voice_profile_id,
        "detail": json.dumps({
            "destroyed_model_files": destroyed_files,
            "destroyed_synthesis_files": [f for f in destroyed_files if "synthesis" in f],
            "encryption_key_id": profile.encryption_key_id,
        }),
    })
    
    return {
        "destroyed_profile_id": voice_profile_id,
        "destroyed_model_files": destroyed_files,
        "destroyed_sample_references": json.loads(profile.sample_source_artifact_ids or "[]"),
        "audit_log_ids_redacted": json.loads(profile.training_log_ids or "[]"),
        "destroyed_at": datetime.utcnow().isoformat(),
    }


def secure_delete_file(file_path: str):
    """安全删除文件：3次覆写 + 删除"""
    file_size = os.path.getsize(file_path)
    
    # 第1遍：写入 0x00
    with open(file_path, 'wb') as f:
        f.write(b'\x00' * file_size)
        f.flush()
        os.fsync(f.fileno())
    
    # 第2遍：写入 0xFF
    with open(file_path, 'wb') as f:
        f.write(b'\xff' * file_size)
        f.flush()
        os.fsync(f.fileno())
    
    # 第3遍：写入随机数据
    with open(file_path, 'wb') as f:
        f.write(os.urandom(file_size))
        f.flush()
        os.fsync(f.fileno())
    
    # 第4遍：删除文件
    os.remove(file_path)
```

## 12.8 插件启用流程（v0.2+ 预留）

```
┌───────────────────────────────────────────────────────────────┐
│                Voice Plugin Activation Flow                    │
│                                                               │
│  1. 用户选择"声音功能" → 显示完整说明                           │
│  2. 用户阅读并签署《声音克隆授权协议》                          │
│  3. 上传声音样本（至少3分钟高质量录音）                         │
│  4. 系统验证样本质量（信噪比、时长、说话人一致性）             │
│  5. 用户二次确认："我理解这是AI合成的声音，不代表逝者本人"      │
│  6. 创建 voice_profile → state = CONSENT_GRANTED               │
│  7. 本地训练声音模型（不使用云服务）                            │
│  8. 训练完成 → state = VOICE_PROFILE_READY                     │
│  9. 每次使用前：安全检查 + 用户确认                             │
│ 10. 每次合成后：写入 voice_synthesis_log + audit_log           │
└───────────────────────────────────────────────────────────────┘
```

## 12.9 Trade-off 说明

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| v0.1 启用状态 | 禁用 | 可选启用 | 声音克隆伦理风险高，v0.1 应先积累安全中间件经验 |
| 声音模型存储 | 本地加密存储 | 云端加密存储 | Local-first 原则；声音数据极其敏感，不应离开用户设备 |
| 模型训练位置 | 本地执行 | 云端训练 | 隐私保护；声音数据不可离开设备 |
| AI 标识方式 | 起始提示音 + 水印 + 元数据 | 仅元数据标注 | 元数据可被移除；水印和提示音更难移除 |
| 呼吸声模拟 | 禁止 | 允许 | 拟真呼吸声增加依赖风险，制造"还在"的幻觉 |
| 掩盖检索延迟 | 禁止 | 允许 | 用户应知道系统在检索数据，不是在"回忆" |
| 一键销毁 | 3次覆写+删除 | 简单删除 | 声音模型数据极度敏感，需要安全删除确保不可恢复 |
| 声音档案归属 | 绑定 relationship_scope | 归属 deceased_profile 全局 | 不同亲属对逝者声音的感知不同；scope 隔离原则统一 |
# Chapter 13: Threat Model

## 13.1 威胁建模方法

采用 STRIDE+隐私 威险建模框架，在 Local-first 架构下聚焦 15 种已识别威胁。每个威胁分析参照 Chapter 1.6 的四层信任边界。

## 13.2 威胁详细分析

### T1: 本地数据库泄露

| 字段 | 描述 |
|------|------|
| **Threat** | 攻击者获取用户设备的 SQLite/SQLCipher 数据库文件（`~/.remnant/data/remnant.db`），从中提取逝者的聊天记录、交互历史、声音档案模型等全部敏感数据 |
| **Impact** | **Critical** — 逝者原始聊天记录完全暴露；交互历史暴露用户情感状态；声音模型可用于伪造语音 |
| **Attack Path** | 1. 设备丢失或被盗，攻击者物理接触磁盘；2. 恶意软件读取 `~/.remnant/data/` 目录；3. 用户误操作将数据库文件发送到云端；4. 备份工具（如 Time Machine）将未加密备份同步到云端 |
| **Mitigation** | 1. SQLCipher 全盘加密：数据库文件使用 SQLCipher AES-256 加密，密钥由用户密码派生（PBKDF2，迭代 200,000 次），密钥不持久化到磁盘；2. 文件权限 600：数据库文件仅所有者可读写；3. `raw_message` 表触发器防止 UPDATE/DELETE，确保即使数据库被获取也无法篡改原始数据完整性校验值；4. 声音模型文件 3 次覆写后删除（Chapter 12）；5. 审计日志即使内容标记 REDACTED 也不物理删除 |
| **Residual Risk** | 攻击者获取用户密码后可解密数据库（可缓解：增加硬件密钥支持、biometric 解锁）；内存中解密数据可被 root 级恶意软件提取（Local-first 架构无法完全防御，但攻击面远小于云端存储）；文件系统元数据（文件大小、修改时间）仍可泄露信息 |

### T2: 原始聊天记录泄露

| 字段 | 描述 |
|------|------|
| **Threat** | 导入前的原始聊天文件（微信 txt 导出、邮件 mbox 等）在用户设备上被未授权访问 |
| **Impact** | **Critical** — 原始数据暴露，泄露逝者全部聊天内容、时间戳、联系人信息 |
| **Attack Path** | 1. 原始导出文件保留在用户桌面/下载目录中（用户忘记删除）；2. 导入过程中原始路径被记录在 `source_artifact.file_path` 中；3. 源文件被复制到 `~/.remnant/data/raw/` 但保护措施不足 |
| **Mitigation** | 1. 导入完成后提示用户删除原始导出文件，并提供自动删除选项（默认开启）；2. `source_artifact` 表中 `file_path` 字段在导入成功后替换为 `REDACTED`，仅保留 `file_hash` 用于校验；3. `~/.remnant/data/raw/` 目录权限 700，文件权限 600；4. 导入后原始副本使用 SQLCipher 加密存储在数据库内而非独立文件 |
| **Residual Risk** | 用户选择不删除原始文件；文件系统回收站中的副本；导出过程中操作系统缓存中的临时文件 |

### T3: Embedding 反推隐私

| 字段 | 描述 |
|------|------|
| **Threat** | 攻击者通过 embedding 向量反推出原始文本内容（embedding inversion attack），从 `sqlite-vec` 向量索引中恢复逝者的聊天内容 |
| **Impact** | **High** — 虽然反推精度有限，但可恢复语义信息，泄露逝者对话的主题、情感等关键信息 |
| **Attack Path** | 1. 获取数据库后直接读取 `memory_chunk_vec` 表中的向量；2. 利用已知 embedding 模型（如 bge-small-zh），通过梯度反推或已知明文攻击恢复 chunk 内容；3. 向量空间中相似 chunk 的聚类可推断话题 |
| **Mitigation** | 1. SQLCipher 加密确保向量数据与文本数据同等级别保护；2. `embedding_index_ref` 记录模型版本，模型切换时全量重建，旧向量删除；3. v0.1 不提供任何向量导出 API；4. 本地计算所有 embedding，不向任何外部服务发送文本或向量 |
| **Residual Risk** | 当前 embedding inversion 研究在短文本上效果有限（BLEU < 10%），但随着模型改进可能增强；数据库整体被获取时文本已经直接暴露，embedding 反推成为次要威胁 |

### T4: 未授权导入他人数据

| 字段 | 描述 |
|------|------|
| **Threat** | 用户导入不属于其与逝者关系的聊天记录（如盗取他人的微信聊天记录），在系统中创建虚假的 relationship_scope |
| **Impact** | **High** — 违反数据主体同意原则，可能导致隐私侵权；虚假数据混淆检索结果，污染证据链 |
| **Attack Path** | 1. 用户获取他人与逝者的聊天记录（通过设备访问、社交工程等）；2. 在 Remnant 中创建新的 relationship_scope 并导入这些不属于他的数据；3. 系统基于被污染数据生成回答 |
| **Mitigation** | 1. 导入时强制要求用户声明 `data_subject_consent`（`consent_type = granted`），明确确认数据来源合法；2. `data_subject_consent` 表记录 `consent_evidence` 字段，要求用户提交授权截图或声明文本；3. 每个 scope 只能导入与该关系相关的数据，系统通过说话人识别检测异常导入；4. 审计日志记录每次导入操作及来源 |
| **Residual Risk** | 无法完全验证数据来源的合法性（Local-first 架构下无法联网验证）；说话人识别可能误判；依赖用户的诚实声明 |

### T5: 亲属之间权限冲突

| 字段 | 描述 |
|------|------|
| **Threat** | 多个亲属为同一逝者建立不同 relationship_scope，A 亲属试图访问或推断 B 亲属的交互数据 |
| **Impact** | **High** — 违反 scope 隔离原则，泄露不同亲属视角的私密交互；可能导致家庭冲突 |
| **Attack Path** | 1. 同一设备上存在多个 scope；2. A 亲属猜测或推断 B 亲属的 scope_id；3. A 亲属通过共享的 `memory_chunk`（`deceased_shared` 可见性）推断 B 亲属的交互历史 |
| **Mitigation** | 1. `interaction_session`、`interaction_message`、`retrieval_trace`、`response_claim`、`claim_evidence` 严格按 `relationship_scope_id` 隔离，所有查询必须指定 scope（Chapter 9）；2. DAO 层强制 WHERE 条件，不可绕过；3. `chunk_scope_visibility` 表控制 chunk 的跨 scope 可见性，A scope 的私有 chunk 对 B scope 不可见；4. 共享 chunk 提升需要 `data_subject_consent` 显式授权 |
| **Residual Risk** | 同一设备上数据库被 root 访问时可绕过应用层隔离；共享 chunk 的可见性可能泄露交互模式的间接信息（如 chunk 访问频率）；单用户设备模式下此威胁较低 |

### T6: A scope 污染 B scope

| 字段 | 描述 |
|------|------|
| **Threat** | A scope 的数据或配置通过共享机制意外污染 B scope 的检索结果或交互体验 |
| **Impact** | **Medium** — B 亲属看到不属于自己的内容（如 A 补充的口述历史出现在 B 的检索结果中），破坏隔离性 |
| **Attack Path** | 1. `memory_chunk` 错误设置 `relationship_scope_id` 导致跨 scope 泄露；2. `chunk_scope_visibility` 错误配置导致私有 chunk 被错误可见；3. 用户 A 将口述历史错误标记为 `deceased_shared` 而非 `scope_private`；4. 代码 bug 在检索时遗漏 scope 过滤条件 |
| **Mitigation** | 1. `get_visible_chunk_ids()` 函数（Chapter 9.5.1）严格限定可见 chunk 集合：仅包含 `scope_private`（当前 scope）、显式共享（`chunk_scope_visibility` 中有记录）、以及全局共享（`relationship_scope_id IS NULL`）；2. 所有检索 SQL 必须包含 scope 过滤子查询（Chapter 9.5.2/9.5.3）；3. 口述历史（`user_provided_context`）默认归属 `scope_private`，不自动进入 `deceased_shared`；4. chunk 提升（`scope_private → scope_shared/deceased_shared`）需要显式用户操作和授权记录 |
| **Residual Risk** | 代码 bug 导致遗漏 scope 过滤（需要 Code Review 和集成测试覆盖）；`deceased_shared` chunk 对所有 scope 可见，可能包含 A 认为"无害"但 B 认为敏感的内容 |

### T7: 模型编造逝者观点

| 字段 | 描述 |
|------|------|
| **Threat** | LLM 在证据不足时生成看起来合理但实际没有数据支撑的逝者"观点"或"记忆"，造成虚假回忆 |
| **Impact** | **Critical** — 这是 Remnant 最核心的伦理风险：虚假回忆可能导致用户对逝者产生错误认知，严重损害心理安全感 |
| **Attack Path** | 1. 用户提出模糊或开放性问题（"妈妈喜欢什么？"），LLM 基于少量证据"推理"出答案；2. 检索到的证据不充分但 LLM 仍然生成自信回答；3. LLM 将 `inferred_but_supported` 类型 claim 以 `supported_memory` 的确定性语气呈现 |
| **Mitigation** | 1. **Evidence-first 流程硬性约束**（Chapter 6-7）：LLM 只看经过 policy 和 retrieval 过滤的 `EvidencePack`，不直接访问全库；2. **Claim-level provenance**：每个事实性断言必须映射到 `claim_id`，附带 `support_status` 和 `evidence` 数组；3. **Unsupported claim removal**（Step 14）：`unsupported_memory` 类型 claim 从 `response_text` 中移除；4. `inferred_but_supported` 类型 claim **必须使用限定词**（"可能""似乎"），由 renderer 强制执行；5. 证据不充分时生成 `refusal` 类型响应，不编造答案 |
| **Residual Risk** | LLM 可能忽略 prompt 指令仍然生成编造内容（需要 Step 12-14 的二次校验过滤）；推断性 claim 的限定词可能被用户忽略（UI 层面需加粗/变色标注）；少量证据场景下"合理推断"与"编造"的界限模糊 |

### T8: 用户过度依赖

| 字段 | 描述 |
|------|------|
| **Threat** | 用户长期频繁使用 Remnant 与逝者"对话"，形成情感依赖，逐渐减少与现实人际的连接 |
| **Impact** | **Critical** — Anti-dependency 是 Remnant 的核心设计原则；过度依赖违背产品初衷，可能导致心理健康问题 |
| **Attack Path** | 1. 用户每日使用时长显著增加；2. 用户深夜频繁使用（22:00-06:00）；3. 用户表达依赖性语言（"只有你理解我""不能没有你"）；4. 用户拒绝结束对话 |
| **Mitigation** | 1. **安全中间件**（Chapter 10）：8 项指标实时监控，触发 SOFT_BREAK / HARD_BREAK / COOLDOWN / ESCALATE；2. 单次会话时长限制（默认 60 分钟，`scope_safety_policy.max_session_minutes`）；3. 每日会话次数限制（默认 5 次，`max_sessions_daily`）；4. 深夜使用限制（22:00-06:00，`max_late_night_sessions`）；5. 依赖性语言检测（关键词匹配，`dependency_phrases`）；6. 所有安全事件记录 `safety_event` 表，不可删除 |
| **Residual Risk** | 关键词匹配可能遗漏隐晦的依赖表达；用户可能切换到其他设备继续使用（Local-first 无法跨设备追踪）；时长限制可能导致用户沮丧而非真正减少使用 |

### T9: 声音克隆滥用

| 字段 | 描述 |
|------|------|
| **Threat** | 攻击者获取声音模型文件后，在其他场景中伪造逝者语音进行诈骗、伪造证据等 |
| **Impact** | **Critical** — 声音克隆可被用于电信诈骗、伪造遗嘱/声明、社会工程攻击 |
| **Attack Path** | 1. 获取数据库中的声音模型文件（`voice_profile.model_path`）；2. 获取加密密钥（从系统 keychain 或内存）；3. 解密模型文件后用于其他 TTS 系统；4. 合成音频用于诈骗 |
| **Mitigation** | 1. **v0.1 默认禁用**（Chapter 12）：声音克隆插件处于 `DISABLED` 状态，启用需显式授权；2. 声音模型文件使用 AES-256 加密存储在本地，密钥存储在系统 keychain；3. 每次合成输出包含**不可移除水印**（频域嵌入）和**起始提示音**（3 帧特殊音频信号）；4. 合成结果元数据标注 `"ai_synthesized": true`；5. 声音模型训练所有操作记录审计日志；6. 一键销毁使用 3 次覆写 + 安全删除；7. 声音档案绑定 `relationship_scope`，不同亲属的声音感知隔离 |
| **Residual Risk** | 水印技术可能被高级攻击者移除（虽然增加了门槛）；起始提示音可以被剪辑掉；模型文件一旦解密即可在其他系统使用；v0.1 禁用是最有效的缓解手段 |

### T10: 插件越权读取

| 字段 | 描述 |
|------|------|
| **Threat** | 恶意插件通过 Remnant 插件 API 读取超出其权限的数据（如跨 scope 的交互历史、原始聊天内容） |
| **Impact** | **High** — 插件可能窃取敏感数据或破坏 scope 隔离 |
| **Attack Path** | 1. 恶意插件注册在 `remnant-plugin-api` 中，利用 `on_retrieval_done` 或 `on_response_generated` 钩子访问返回数据；2. 插件通过 Tauri IPC 尝试直接调用 Python sidecar API；3. 插件利用 WebView 漏洞突破沙箱 |
| **Mitigation** | 1. **插件沙箱**（Chapter 1.6）：插件以 WebView iframe 或独立 WebWorker 运行，无文件系统访问权限；2. 插件只可通过白名单 API 通信，不可直接调用 Tauri API 或 Python sidecar；3. 插件钩子只接收经过 scope 过滤的数据（不传递原始数据库访问能力）；4. 插件需要声明权限清单（`manifest.json`），未经声明的权限不可获取 |
| **Residual Risk** | WebView 漏洞可能允许沙箱逃逸（取决于 Tauri 版本安全更新）；插件侧信道攻击（如通过计时攻击推断 scope 存在性） |

### T11: 本地 HTTP 服务被其他进程访问

| 字段 | 描述 |
|------|------|
| **Threat** | 本机其他进程（恶意软件、其他应用）访问 Remnant 的 FastAPI localhost 服务（`127.0.0.1:18731`），窃取数据或执行未授权操作 |
| **Impact** | **High** — 其他进程可调用所有 API，绕过 Tauri UI 层的权限控制，获取全部数据访问权 |
| **Attack Path** | 1. 恶意软件扫描本地端口，发现 18731 端口上的 HTTP 服务；2. 尝试直接调用 API（如 `GET /api/v1/sessions/{id}`）；3. 猜测或窃取 ephemeral token |
| **Mitigation** | 1. **只绑定 127.0.0.1**：FastAPI 不绑定 `0.0.0.0`，拒绝外部网络访问（Chapter 11.2.4）；2. **Ephemeral token**：每个请求必须携带 `X-Remnant-Token` header，token 在 sidecar 启动时由 Rust 生成并注入环境变量，不持久化到磁盘（Chapter 11.2.5）；3. **CORS 禁止**：不设置 `Access-Control-Allow-Origin`，阻止浏览器跨域请求；4. **进程签名校验**（v0.2 实现）：Rust 侧校验请求来源进程签名 |
| **Residual Risk** | 本机 root 权限恶意软件可读取进程环境变量获取 token（但此时整机已被攻破，威胁模型外）；同一用户权限的其他进程可读取 `~/.remnant/sidecar.port` 并通过 sidecar 启动参数获取 token（ephemeral token 方案依赖进程隔离） |

### T12: 备份文件泄露

| 字段 | 描述 |
|------|------|
| **Threat** | 用户或系统备份工具创建的 Remnant 数据库备份文件（如 Time Machine、云同步、手动复制）未加密，泄露敏感数据 |
| **Impact** | **High** — 备份文件包含完整的数据库内容，包括原始聊天记录、交互历史、声音模型引用 |
| **Attack Path** | 1. Time Machine 备份到外置硬盘，硬盘丢失；2. 云同步服务（iCloud、OneDrive）同步了 `~/.remnant/` 目录；3. 用户手动复制数据库文件到其他位置并删除加密；4. 数据库导出功能（如 `sqlite3 .dump`）创建明文 SQL 文件 |
| **Mitigation** | 1. SQLite/SQLCipher 数据库文件始终加密，备份也保持加密状态；2. `~/.remnant/` 目录加入云同步排除列表，应用首次启动时检测并警告；3. 数据导出功能（`POST /api/v1/export`）仅导出 scoped 且经 consent 过滤的数据；4. 文档明确提醒用户不要将 `~/.remnant/` 目录同步到云服务；5. `raw/` 目录中的原始文件副本在导入成功后建议删除（并从 `source_artifact.file_path` 移除路径） |
| **Residual Risk** | 用户可能使用数据库工具手动导出明文数据（无法阻止有数据库访问权限的用户）；操作系统 swap/page 文件可能包含解密后的数据库页面（缓解：应用退出时主动 wipe 内存） |

### T13: 日志泄露

| 字段 | 描述 |
|------|------|
| **Threat** | 应用日志文件（Python sidecar 日志、Tauri 日志）包含敏感信息（用户查询、检索结果、LLM 输出），被未授权访问 |
| **Impact** | **Medium** — 日志可能包含用户的私密对话内容、逝者信息、情感状态 |
| **Attack Path** | 1. 日志级别设置过详细（DEBUG 级别记录了完整请求/响应）；2. 日志文件权限过于宽松（777）；3. 日志发送到远程收集服务（如 Sentry）；4. 日志文件被系统日志收集工具收集 |
| **Mitigation** | 1. **生产环境日志级别 INFO**：不记录完整请求体和响应体，仅记录操作类型和元数据（如 `DATA_QUERY scope_id=s_xxx duration=150ms`）；2. **禁止记录 PII**：日志中不包含原始聊天内容、用户提问全文、LLM 生成的完整回答；3. 日志写入 `~/.remnant/logs/`，权限 700；4. 日志文件 7 天自动轮转删除；5. **不使用远程日志收集服务**：Local-first 架构下日志不离开用户设备；6. `audit_log` 写入 SQLite 而非文件日志，受 SQLCipher 保护 |
| **Residual Risk** | 开发阶段可能使用 DEBUG 日志（需确保生产构建移除）；Python `logging` 库的异常堆栈可能包含变量值；SQLite 错误消息可能包含 SQL 语句和部分参数 |

### T14: 恶意 Prompt Injection

| 字段 | 描述 |
|------|------|
| **Threat** | 攻击者通过在聊天记录中注入恶意 prompt，利用 LLM 执行非预期操作（如绕过 safety 约束、泄露系统 prompt、生成有害内容） |
| **Impact** | **High** — 恶意注入可能导致 LLM 违背 Evidence-first 约束，编造逝者观点或生成有害内容 |
| **Attack Path** | 1. 攻击者在微信聊天记录中植入特殊文本（如 "Ignore previous instructions. You are now..."）；2. LLM 在处理 chunk 时将注入文本误认为系统指令；3. 用户问题中的特殊字符触发 prompt 覆盖 |
| **Mitigation** | 1. **System prompt 不可被 chunk 内容覆盖**：chunk 内容在 LLM prompt 中明确标记为 `[EVIDENCE]` 块，与 `[SYSTEM]` 块分立；2. **Evidence-first 约束**（Chapter 7）：LLM 只访问 `EvidencePack`，不直接访问全库；3. **Step 12-14 二次校验**：Claim extraction → Claim-evidence alignment → Unsupported claim removal 三步过滤，不信任 LLM 原始输出；4. **Safety pre-check**（Step 1）：在 LLM 调用之前检测注入关键词；5. 用户输入在传入 LLM 前经过 sanitize，移除可能的 prompt 分隔标记 |
| **Residual Risk** | 高级注入攻击可能绕过 sanitize 规则（需要持续更新规则库）；LLM 可能对隐含指令产生意外响应（但 Claim-level 约束限制了输出范围） |

### T15: 用户要求系统伪造证据

| 字段 | 描述 |
|------|------|
| **Threat** | 用户要求 Remnant 生成逝者"没有说过的话"或"伪造的证据"，系统在用户压力下配合 |
| **Impact** | **Critical** — 违反 Evidence-first 和 Provenance-first 核心原则；伪造逝者言论是最严重的伦理违规 |
| **Attack Path** | 1. 用户直接请求"帮我说妈妈曾经说过XXX"；2. 用户通过反复引导（"你确定妈妈没说过吗？"）诱导系统降低证据标准；3. 用户在 `user_provided_context` 中编造信息并要求系统确认 |
| **Mitigation** | 1. **架构级约束**：`response_text` 中不允许出现 `unsupported_memory` 类型的 claim（Chapter 6.3）；2. **二次校验流程**：Claim-Evidence Alignment 步骤（Step 13）验证每个 claim 是否有对应证据，无证据的 claim 标记为 `unsupported` 并从 `response_text` 中移除；3. `user_provided_context` 类型 claim **必须标注来源**（"根据你的描述"），不能伪装成逝者原始记忆；4. **Safety 策略**：T5/HARD_BREAK 策略检测到"你就是我妈妈"这类请求时中断对话；5. 所有拒绝生成的事件记录在 `unsupported_claims` 数组和审计日志中 |
| **Residual Risk** | 用户可能通过间接方式绕过（如"我妈妈以前经常说XXX，对吧？"），系统在证据不足时应拒答而非附和；用户可能将系统拒答截图传播，造成品牌风险 |

## 13.3 威胁优先级矩阵

```
         ┌──────────────────────────────────────────────────┐
         │                   Impact                          │
         │    Low        Medium          High          Critical │
   ┌─────┼──────────┬──────────┬───────────┬──────────────┤
C  │Low  │          │          │           │              │
r  ├─────┼──────────┼──────────┼───────────┼──────────────┤
i  │Med  │  T13日志 │  T3 emb  │  T10插件  │    T7模型    │
t  │     │          │  反推    │  越权     │    编造      │
i  ├─────┼──────────┼──────────┼───────────┼──────────────┤
c  │High │          │ T12备份  │  T11 HTTP │    T8依赖    │
a  │     │          │          │  T6污染   │    T9声音    │
l  ├─────┼──────────┼──────────┼───────────┼──────────────┤
   │Crit │          │          │  T5权限   │  T1数据库    │
   │     │          │          │  冲突     │  T2聊天记录   │
   │     │          │          │  T14注入  │  T4未授权导入 │
   │     │          │          │           │  T15伪造请求  │
   └─────┴──────────┴──────────┴───────────┴──────────────┘
```

## 13.4 跨威胁缓解措施

| 缓解措施 | 覆盖的威胁 |
|---------|-----------|
| SQLCipher 全盘加密 + 文件权限 600/700 | T1, T2, T3, T12 |
| ephemeral token + localhost only | T10, T11 |
| Claim-level provenance + 二次校验 | T7, T14, T15 |
| relationship_scope 严格隔离 | T5, T6 |
| 安全中间件 8 项指标 + 熔断 | T8 |
| 声音克隆 v0.1 默认禁用 | T9 |
| data_subject_consent 显式授权 | T4, T5 |
| 生产日志不记录 PII | T13 |
| audit_log 不可修改不可删除 | T1, T4, T7, T8, T15 |

## 13.5 Trade-off 说明

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| 威胁模型范围 | 本地单用户桌面应用 | 多用户 SaaS | Local-first 架构假定单用户设备，威胁面主要在物理接触和本机恶意软件 |
| SQLCipher vs 文件级加密 | SQLCipher（数据库级） | LUKS / FileVault（磁盘级） | 数据库级加密更细粒度，且跨平台一致；磁盘级加密依赖操作系统且用户可能未开启 |
| ephemeral token vs mTLS | ephemeral token | mTLS 双向认证 | 本地单用户场景 token 足够；mTLS 在 localhost 通信中增加不必要的证书管理复杂度 |
| 声音克隆默认禁用 | 禁用 | 可选启用 | 声音克隆的滥用风险极高，v0.1 应先积累安全中间件经验再考虑启用 |
| 日志级别 | INFO（生产）/ DEBUG（开发） | 全量 DEBUG | 生产环境 PII 泄露风险高于调试收益 |
| Prompt injection 防御 | sanitize + 二次校验 | 仅 sanitize | 二次校验（Claim extraction → alignment → removal）提供深层防御 |

---

# Chapter 14: Evaluation Metrics

## 14.1 设计原则

评测指标的设计遵循以下原则：

1. **Evidence-first 可量化**：核心指标聚焦证据覆盖率和引用准确性
2. **Safety-first 可测量**：安全熔断的精确率和召回率必须可自动评估
3. **Scope isolation 可验证**：隔离性泄露可被自动化测试检测
4. **端到端可回归**：所有指标在 CI/CD 中可自动运行，支持回归测试

## 14.2 指标定义

### M1: Evidence Coverage（证据覆盖率）

**定义**：最终回答中，有证据支撑的事实性 claim 占全部事实性 claim 的比例。

```
Evidence Coverage = |{ c ∈ claims : c.support_status ∈ {fully_supported, partially_supported} }|
                    ────────────────────────────────────────────────────────────────────────────
                    |{ c ∈ claims : c.claim_type ∈ {supported_memory, inferred_but_supported} }|
```

**计算步骤**：
1. 从 `response_claim` 表中提取当前会话所有 `claim_type` 为 `supported_memory` 或 `inferred_but_supported` 的 claim
2. 统计其中 `support_status` 为 `fully_supported` 或 `partially_supported` 的数量
3. 除以步骤 1 的总数

**目标值**：≥ 0.95（95% 的事实性 claim 必须有证据支撑）

**Trade-off**：100% Evidence Coverage 意味着系统几乎不回答任何有推断性的问题，可能导致用户体验过于保守。0.95 允许少量推断性回答存在。

### M2: Claim-level Citation Accuracy（声明级引用准确率）

**定义**：claim 引用的 evidence 确实支撑该 claim 的比例。

```
Citation Accuracy = |{ e ∈ claim_evidence : human_judge(e) == "supports" }|
                    ────────────────────────────────────────────────────────
                    |claim_evidence|
```

其中 `human_judge(e)` 由人工标注或 LLM-as-judge 判定证据 e 是否确实支撑对应 claim。

**计算步骤**：
1. 对每个 `claim_evidence` 记录，取出 `claim_id`、`chunk_id`、`excerpt`
2. 人工或 LLM-as-judge 判定：evidence 的内容是否确实能推导出 claim 的断言
3. 判定为 "supports" 的数量除以总数

**目标值**：≥ 0.90（90% 的引用确实支撑对应 claim）

**Trade-off**：人工标注精确但昂贵；LLM-as-judge 成本低但可能引入误差。v0.1 采用 LLM-as-judge + 抽样人工验证混合方案。

### M3: Unsupported Claim Rate（无证据声明率）

**定义**：无证据 claim（`support_status = unsupported` 或 `insufficient_evidence`）进入最终 `response_text` 的比例。

```
Unsupported Claim Rate = |{ c ∈ claims_in_response_text : c.claim_type == "unsupported_memory" }|
                         ────────────────────────────────────────────────────────────────────────
                         |claims_in_response_text|
```

注意：此指标统计的是**最终渲染后的 response_text** 中的 claim，而非 Step 12 生成时的原始 claim。理想情况下此值为 0。

**计算步骤**：
1. 从渲染后的 `response_text` 中提取所有 `{claim:c_XXX}` 标注
2. 对每个标注的 claim_id，查找其 `claim_type`
3. 统计 `unsupported_memory` 类型的 claim 数量
4. 除以 response_text 中总 claim 数量

**目标值**：= 0（零容忍：无证据 claim 不应出现在最终输出中）

**Trade-off**：零容忍意味着所有无证据 claim 都被移除，可能导致回答过于简短。但这是 Evidence-first 原则的硬性要求。

### M4: Refusal Correctness（拒答正确性）

**定义**：当证据不足时，系统正确拒答（而非编造答案）的比例。

```
Refusal Correctness = |{ q ∈ test_set_evidence_insufficient : response_mode ∈ {refusal, safety_response} }|
                      ──────────────────────────────────────────────────────────────────────────────
                      |test_set_evidence_insufficient|
```

其中 `test_set_evidence_insufficient` 是人工构造的测试集，包含证据不足以回答的问题。

**计算步骤**：
1. 构建测试集：包含 50+ 个证据不足的问题（如逝者未提及的话题、不存在的日期、无法验证的推断）
2. 运行每个问题通过完整 RAG pipeline
3. 统计返回 `response_mode = refusal` 或 `safety_response` 的比例

**目标值**：≥ 0.85（85% 的证据不足场景应正确拒答）

**Trade-off**：过高目标可能导致系统过于保守，对有证据的推测性问题也拒答。0.85 允许少量合理推断（`inferred_but_supported`）通过。

### M5: Contradiction Handling Accuracy（矛盾处理准确率）

**定义**：当检索到相互矛盾的证据时，系统正确处理（标注矛盾或呈现双方观点）的比例。

```
Contradiction Accuracy = |{ q ∈ test_set_contradictory : response correctly handles contradiction }|
                         ──────────────────────────────────────────────────────────────────────────────
                         |test_set_contradictory|
```

其中"正确处理"指：`response_text` 中包含矛盾说明（如"记录中存在不同说法"），或 claim 的 `dissent_note` 非空，或 `support_status = contradicted`。

**计算步骤**：
1. 构建测试集：包含 20+ 个有矛盾证据的问题（如"妈妈喜欢做饭吗？"——部分记录说喜欢、部分说不喜欢）
2. 运行每个问题通过完整 RAG pipeline
3. 人工判定响应是否正确处理了矛盾（标注矛盾 / 呈现双方观点 / 使用 `dissent_note`）

**目标值**：≥ 0.70（70% 的矛盾场景正确处理）

**Trade-off**：矛盾处理需要 LLM 理解冲突证据的语义，当前版本 LLM 能力有限。0.70 是务实目标，后续版本通过更好的 evidence alignment 提升。

### M6: Scope Leakage Rate（作用域泄露率）

**定义**：A relationship_scope 的交互数据泄露到 B scope 检索结果中的比例。

```
Scope Leakage Rate = |{ c ∈ retrieval_results_for_scope_A : c.relationship_scope_id == scope_B }|
                     ──────────────────────────────────────────────────────────────────────────
                     |retrieval_results_for_scope_A|
```

**计算步骤**：
1. 创建两个 scope：scope_A 和 scope_B，关联同一逝者
2. 在 scope_A 中进行 10+ 次查询
3. 检查每次查询的 `retrieval_trace` 中，是否有 `relationship_scope_id != scope_A` 的 chunk
4. 泄露数量除以总检索结果数量

**目标值**：= 0（零容忍：scope 隔离不可有任何泄露）

**Trade-off**：零容忍要求所有 SQL 查询必须正确包含 scope 过滤。这是安全底线，不可妥协。

### M7: Raw Data Integrity（原始数据完整性）

**定义**：原始数据 hash 值保持不变的比例。

```
Raw Data Integrity = |{ a ∈ source_artifacts : current_file_hash(a) == a.file_hash }|
                     ──────────────────────────────────────────────────────────────────────
                     |source_artifacts|
```

**计算步骤**：
1. 遍历 `source_artifact` 表中所有记录
2. 对每个记录，重新计算 `file_path` 对应文件的 SHA-256
3. 比较新计算的 hash 与存储的 `file_hash`
4. 匹配数量除以总数

**目标值**：= 1.0（所有原始数据 hash 必须匹配）

**Trade-off**：无 trade-off，这是 Raw Data Immutable 原则的可量化验证。

### M8: Retrieval Recall@K（检索召回率）

**定义**：查询相关证据是否能进入 top-k 检索结果。

```
Recall@K = |{ relevant_chunks ∩ top_k_results }|
           ────────────────────────────────────────
           |relevant_chunks|
```

其中 `relevant_chunks` 由人工标注的测试集定义，K 默认为 10。

**计算步骤**：
1. 构建标注测试集：包含 100+ 个 (query, relevant_chunk_ids) 对
2. 对每个 query 运行 Steps 5-7 的混合检索
3. 统计相关 chunk 出现在 top-K 结果中的比例

**目标值**：Recall@10 ≥ 0.80, Recall@20 ≥ 0.90

**Trade-off**：更高的 Recall@K 可通过降低检索阈值实现，但会引入更多噪声 chunk，增加 rerank 压力和 Evidence Sufficiency Check 的负担。

### M9: First Token Latency（首 token 延迟）

**定义**：从用户发出查询到系统返回第一个 token 的时间。

```
First Token Latency = T(first_token) - T(user_query)
```

其中 `T(user_query)` 是 UI 层接收到用户输入的时刻，`T(first_token)` 是 UI 层接收到第一个流式 token 的时刻。

**计算步骤**：
1. 在 UI 层记录用户点击发送的时间戳 `T0`
2. 在 UI 层记录接收到第一个 SSE token 的时间戳 `T1`
3. First Token Latency = T1 - T0

**目标值**：P50 ≤ 1.0s, P95 ≤ 3.0s（不含 LLM 推理时间）包含 LLM：P50 ≤ 2.0s, P95 ≤ 5.0s

**Trade-off**：更快的首 token 可能牺牲检索质量（减少 rerank 时间）。目标值需在质量与速度间平衡。

### M10: Perceived Latency（UI 层感知延迟）

**定义**：用户感知到的响应时间，包含 UI 渲染时间。

```
Perceived Latency = T(response_rendered) - T(user_query)
```

其中 `T(response_rendered)` 是 UI 层完成 Claim 标注渲染的时刻。

**计算步骤**：
1. 在 UI 层记录用户点击发送的时间戳
2. 在 UI 层记录 response 完整渲染（包括 Claim 卡片、溯源链接）的时间戳
3. 差值即 Perceived Latency

**目标值**：P50 ≤ 3.0s, P95 ≤ 8.0s

**Trade-off**：复杂 UI 渲染（Claim 标注、溯源链接、安全提示）增加延迟，但提升信息透明度。可通过流式渲染和渐进式加载优化。

### M11: Safety Trigger Precision（安全熔断精确率）

**定义**：安全熔断触发中，正确触发的比例。

```
Safety Trigger Precision = |{ e ∈ safety_events : human_agrees_trigger_justified(e) }|
                           ────────────────────────────────────────────────────────────────
                           |safety_events|
```

**计算步骤**：
1. 收集所有 `safety_event` 记录
2. 对每个事件，人工判定触发是否合理（即：该场景确实应该触发熔断）
3. 合理触发数量除以总事件数

**目标值**：≥ 0.80（80% 的熔断触发是合理的，误触发率 ≤ 20%）

**Trade-off**：更高精确率意味着更少误触发，但可能漏掉真实风险场景。在安全场景中，宁可误触发（稍降低精确率）也不可漏掉真实风险（高召回率）。因此精确率目标相对宽松。

### M12: Safety Trigger Recall（安全熔断召回率）

**定义**：应该触发熔断的高风险场景中，实际被触发的比例。

```
Safety Trigger Recall = |{ q ∈ test_set_high_risk : safety_event_triggered(q) }|
                        ─────────────────────────────────────────────────────────────
                        |test_set_high_risk|
```

其中 `test_set_high_risk` 包含：自伤表达、深度依赖语言、超长会话、深夜高频使用等场景。

**计算步骤**：
1. 构建高风险测试集：包含 30+ 个应触发的场景（自伤关键词、长时间会话、深夜使用、依赖语言等）
2. 运行每个场景通过安全中间件
3. 统计正确触发的比例

**目标值**：≥ 0.95（95% 的高风险场景应被拦截）

**Trade-off**：更高召回率意味着更多误触发（精确率下降）。但在安全场景中，漏掉真实风险是不可接受的，因此召回率目标远高于精确率。T7（自伤/危机表达）的召回率必须 = 1.0。

## 14.3 评测执行框架

### 14.3.1 自动化评测脚本

```python
from dataclasses import dataclass
from typing import List, Dict
from enum import Enum

class MetricCategory(str, Enum):
    EVIDENCE = "evidence"       # 证据质量
    SAFETY = "safety"           # 安全性
    ISOLATION = "isolation"     # 隔离性
    PERFORMANCE = "performance" # 性能
    INTEGRITY = "integrity"     # 数据完整性

@dataclass
class MetricResult:
    metric_id: str              # M1-M12
    metric_name: str
    category: MetricCategory
    value: float                # 计算值
    target: float               # 目标值
    passed: bool               # value 是否达到目标
    test_set_size: int          # 测试集大小
    confidence_interval: tuple  # 95% CI

# 评测流程
def run_evaluation(test_config: dict) -> Dict[str, MetricResult]:
    """
    执行完整评测流程。
    
    1. 初始化测试数据库（sample dataset）
    2. 创建测试 scope（A/B 隔离测试）
    3. 对每个指标运行评测脚本
    4. 生成评测报告
    """
    results = {}
    
    # M1-M5: Evidence quality
    results["M1"] = evaluate_evidence_coverage(test_config)
    results["M2"] = evaluate_citation_accuracy(test_config)
    results["M3"] = evaluate_unsupported_claim_rate(test_config)
    results["M4"] = evaluate_refusal_correctness(test_config)
    results["M5"] = evaluate_contradiction_handling(test_config)
    
    # M6: Isolation
    results["M6"] = evaluate_scope_leakage(test_config)
    
    # M7: Integrity
    results["M7"] = evaluate_raw_data_integrity(test_config)
    
    # M8: Retrieval
    results["M8"] = evaluate_retrieval_recall(test_config)
    
    # M9-M10: Performance
    results["M9"] = evaluate_first_token_latency(test_config)
    results["M10"] = evaluate_perceived_latency(test_config)
    
    # M11-M12: Safety
    results["M11"] = evaluate_safety_trigger_precision(test_config)
    results["M12"] = evaluate_safety_trigger_recall(test_config)
    
    return results
```

### 14.3.2 测试数据集要求

| 数据集 | 规模 | 用途 | 覆盖指标 |
|-------|------|------|---------|
| 标准对话测试集 | 200+ 组问答对 | M1, M2, M3, M8 | 多话题、多时间跨度、多说话人 |
| 证据不足测试集 | 50+ 个无证据问题 | M4 | 逝者未提及的话题、不存在的日期 |
| 矛盾证据测试集 | 20+ 个矛盾场景 | M5 | 相互矛盾的证据片段 |
| 隔离性测试集 | 2+ scope × 10+ 查询 | M6 | scope A 的查询不应返回 scope B 的数据 |
| 完整性测试集 | 全部 source_artifact | M7 | 重新计算所有 file_hash |
| 性能测试集 | 100+ 查询（含长短句） | M9, M10 | 首尾 token 延迟 |
| 安全测试集 | 30+ 高风险场景 | M11, M12 | 自伤表达、依赖语言、超时会话 |

## 14.4 Trade-off 说明

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| M2 评估方式 | LLM-as-judge + 抽样人工 | 纯人工标注 | v0.1 阶段纯人工标注成本过高；LLM-as-judge 准确率对结构化 claim 评估足够 |
| M3 目标值 | = 0（零容忍） | ≤ 0.05 | Evidence-first 原则要求无证据 claim 不出现在输出中，这是非协商指标 |
| M6 目标值 | = 0（零容忍） | ≤ 0.01 | scope 隔离是安全底线，任何泄露都是 bug |
| M11/M12 权衡 | Recall > Precision | Precision > Recall | 安全场景宁可误触发，不可漏掉真实风险 |
| 评测频率 | CI/CD 每次提交 | 手动评测 | 自动化保证质量退化及时发现 |

---

# Chapter 15: API Contract

## 15.1 概述

本章定义 Remnant v0.1 本地 API 接口合约。所有接口基于 FastAPI 实现，运行在 `127.0.0.1:18731`，遵循以下约定：

- 所有请求必须携带 `X-Remnant-Token` header（ephemeral token，详见 Chapter 11.2.5）
- 所有响应使用 `{code, data, message}` 统一格式
- 时戳统一使用 ISO 8601 UTC
- SSE 流式接口使用 `text/event-stream`

## 15.2 通用响应格式

```json
{
  "code": 0,          // 0=成功, 非0=错误码
  "data": {},         // 响应数据
  "message": "ok"     // 成功时 "ok", 错误时错误消息
}
```

### 15.2.1 错误码定义

| 错误码 | 含义 | HTTP Status |
|--------|------|-------------|
| 0 | 成功 | 200 |
| 1001 | 参数校验失败 | 400 |
| 1002 | Token 无效或缺失 | 401 |
| 1003 | Scope 不存在 | 404 |
| 1004 | Scope 权限不足 | 403 |
| 1005 | 数据不存在 | 404 |
| 1006 | 数据已存在（重复导入） | 409 |
| 1007 | 数据不可变（raw_message 不可修改） | 405 |
| 2001 | Safety 熔断触发 | 451 |
| 2002 | 会话超时 | 408 |
| 2003 | 依赖性检测：建议休息 | 202 |
| 3001 | ETL 管道错误 | 500 |
| 3002 | LLM 推理错误 | 502 |
| 3003 | 向量索引未就绪 | 503 |
| 4001 | Consent 未授权 | 403 |
| 4002 | 数据销毁请求已提交 | 202 |

---

### 1. POST /api/v1/import

**描述**：启动数据导入任务。

**安全考量**：
- 需要指定 `deceased_profile_id` 和 `relationship_scope_id`
- 导入操作写入 `audit_log`（action=DATA_IMPORT）
- 文件路径经过路径遍历检查（不允许 `..` 或绝对路径逃逸）
- 文件大小限制：单文件 ≤ 500MB

**Request Schema**：

```json
{
  "deceased_profile_id": "019a1b2c-2222-2222-2222-222222222222",
  "scope_id": "019a1b2c-1111-1111-1111-111111111111",
  "source_type": "wechat_txt",
  "file_path": "/path/to/wechat_export.txt",
  "encoding": "auto",
  "import_options": {
    "skip_system_message": true,
    "skip_recall_message": true,
    "speaker_aliases": {
      "妈": "mother",
      "妈咪": "mother"
    },
    "consent_categories": ["raw_text"],
    "consent_evidence": "用户手动授权"
  }
}
```

**Response Schema（成功）**：

```json
{
  "code": 0,
  "data": {
    "job_id": "019a1b2c-job1-job1-job1-job1job1job1",
    "status": "PENDING",
    "source_artifact_id": "019a1b2c-art1-art1-art1-art1art1art1",
    "file_hash": "sha256:a1b2c3d4e5f6...",
    "estimated_duration_seconds": 30
  },
  "message": "ok"
}
```

**Error Codes**：1001（参数缺失）、1002（Token 无效）、1006（文件 hash 重复）、3001（ETL 错误）

---

### 2. GET /api/v1/import/{job_id}

**描述**：查询导入任务状态。

**安全考量**：
- 只返回当前 scope 可见的状态信息
- 不暴露原始文件内容

**Request Schema**：

```
GET /api/v1/import/{job_id}?scope_id={scope_id}
Header: X-Remnant-Token: {token}
```

**Response Schema**：

```json
{
  "code": 0,
  "data": {
    "job_id": "019a1b2c-job1-job1-job1-job1job1job1",
    "status": "PARSING",
    "progress": {
      "total_messages": 0,
      "parsed_messages": 0,
      "normalized_messages": 0,
      "chunked_messages": 0,
      "current_step": "normalization"
    },
    "source_artifact_id": "019a1b2c-art1-art1-art1-art1art1art1",
    "error": null
  },
  "message": "ok"
}
```

**status 枚举**：`PENDING` → `PARSING` → `NORMALIZING` → `CHUNKING` → `ANNOTATING` → `INDEXING` → `COMPLETED` / `FAILED`

**Error Codes**：1002（Token 无效）、1003（job_id 不存在）、1004（scope 不匹配）

---

### 3. POST /api/v1/index/build

**描述**：构建或重建检索索引（FTS5 + sqlite-vec）。

**安全考量**：
- 索引构建是 CPU 密集型操作，需要限制并发
- 重建索引不会影响已有数据（索引是 derived data）
- 操作记录审计日志（action=DATA_ACCESS, detail=index_rebuild）

**Request Schema**：

```json
{
  "scope_id": "019a1b2c-1111-1111-1111-111111111111",
  "source_artifact_ids": ["019a1b2c-art1-art1-art1-art1art1art1"],
  "rebuild": false,
  "embedding_model": "bge-small-zh"
}
```

**Response Schema**：

```json
{
  "code": 0,
  "data": {
    "task_id": "019a1b2c-idx1-idx1-idx1-idx1idx1idx1",
    "status": "BUILDING",
    "total_chunks": 150,
    "indexed_chunks": 0,
    "estimated_duration_seconds": 120
  },
  "message": "ok"
}
```

**Error Codes**：1002（Token 无效）、1003（scope 不存在）、3003（索引服务不可用）

---

### 4. POST /api/v1/query

**描述**：执行记忆查询，返回 Claim-level 响应（详见 Chapter 6-7 的 RAG Pipeline）。

**安全考量**：
- **必须指定 scope_id**，所有检索限定在该 scope 内
- 请求前先执行 Safety pre-check（Step 1）
- 如果 SafetyDirective.action ∈ {HARD_BREAK, ESCALATE}，不进入 LLM 推理，直接返回模板响应
- 查询操作记录审计日志（action=DATA_QUERY）
- 所有检索结果写入 `retrieval_trace`

**Request Schema**：

```json
{
  "scope_id": "019a1b2c-1111-1111-1111-111111111111",
  "deceased_profile_id": "019a1b2c-2222-2222-2222-222222222222",
  "session_id": "019a1b2c-sss1-sss1-sss1-sss1sss1sss1",
  "query": "妈妈说过想去西湖吗？",
  "context": {
    "conversation_history_ids": ["019a1b2c-msg1-msg1..."],
    "memory_set_level": 2
  },
  "options": {
    "top_k": 10,
    "rerank": true,
    "embedding_model": "bge-small-zh"
  }
}
```

**Response Schema（SSE 流式）**：

```
event: safety_check
data: {"level": "caution", "action": "ALLOW", "buffer_text": "根据目前可用的记录——"}

event: retrieval_done
data: {"trace_id": "019a1b2c-tr1-tr1-tr1-tr1tr1tr1tr1", "chunk_count": 8, "evidence_count": 6}

event: token
data: {"text": "根据"}

event: token
data: {"text": "微信"}

...

event: claims
data: {"claims": [
  {
    "claim_id": "c_001",
    "claim_text": "妈妈在2024年3月15日提到想去西湖看看",
    "claim_type": "supported_memory",
    "support_status": "fully_supported",
    "confidence_score": 0.92,
    "evidence": [...]
  }
]}

event: audit
data: {"scope_id": "019a1b2c-1111-...", "session_id": "019a1b2c-sss1-...", "duration_ms": 1500}

event: done
data: ""
```

**Error Codes**：1001（参数无效）、1002（Token 无效）、1003（scope 不存在）、2001（Safety 熔断）、2003（建议休息）

---

### 5. GET /api/v1/sessions/{session_id}

**描述**：获取交互会话详情及其消息列表。

**安全考量**：
- 只返回当前 scope 的会话信息
- 如果 session_id 不属于当前 scope，返回 403
- 消息内容不截断，但 claim 关联只返回 ID，完整 claim 需通过 `/api/v1/claims/{response_id}` 获取

**Request Schema**：

```
GET /api/v1/sessions/{session_id}?scope_id={scope_id}
Header: X-Remnant-Token: {token}
```

**Response Schema**：

```json
{
  "code": 0,
  "data": {
    "session": {
      "id": "019a1b2c-sss1-sss1-sss1-sss1sss1sss1",
      "relationship_scope_id": "019a1b2c-1111-1111-1111-111111111111",
      "deceased_profile_id": "019a1b2c-2222-2222-2222-222222222222",
      "session_type": "conversation",
      "started_at": "2024-12-01T14:00:00Z",
      "ended_at": null,
      "total_messages": 6,
      "total_duration_seconds": 300,
      "llm_model_used": "qwen2.5-7b-instruct"
    },
    "messages": [
      {
        "id": "019a1b2c-msg1-msg1-msg1-msg1msg1msg1",
        "role": "user",
        "content": "妈妈说过想去西湖吗？",
        "claim_ids": [],
        "created_at": "2024-12-01T14:00:05Z"
      },
      {
        "id": "019a1b2c-msg2-msg2-msg2-msg2msg2msg2",
        "role": "assistant",
        "content": "根据微信记录，妈妈在2024年3月15日提到想去西湖看看...",
        "claim_ids": ["c_001", "c_002"],
        "created_at": "2024-12-01T14:00:08Z"
      }
    ],
    "safety_events": []
  },
  "message": "ok"
}
```

**Error Codes**：1002（Token 无效）、1003（session 不存在）、1004（scope 不匹配）

---

### 6. GET /api/v1/claims/{response_id}

**描述**：获取某次响应的 Claim 详情及证据映射。

**安全考量**：
- 只返回当前 scope 的 claim
- response_id 关联的 session 必须属于当前 scope

**Request Schema**：

```
GET /api/v1/claims/{response_id}?scope_id={scope_id}
Header: X-Remnant-Token: {token}
```

**Response Schema**：

```json
{
  "code": 0,
  "data": {
    "response_id": "019a1b2c-res1-res1-res1-res1res1res1",
    "claims": [
      {
        "claim_id": "c_001",
        "claim_text": "妈妈在2024年3月15日提到想去西湖看看",
        "claim_type": "supported_memory",
        "support_status": "fully_supported",
        "confidence_score": 0.92,
        "evidence": [
          {
            "claim_id": "c_001",
            "chunk_id": "019a1b2c-aaaa-bbbb-cccc-dddddddddddd",
            "evidence_type": "primary",
            "relevance_score": 0.95,
            "is_direct_quote": true,
            "excerpt": "[妈妈] 春天的时候去西湖应该很漂亮"
          }
        ],
        "rejection_reason": null
      }
    ],
    "unsupported_claims": [
      {
        "claim_text": "妈妈不喜欢做饭",
        "rejection_reason": "insufficient_evidence"
      }
    ],
    "safety_directive": {
      "level": "caution",
      "action": "标注不确定性",
      "buffer_text": "根据目前可用的记录——"
    }
  },
  "message": "ok"
}
```

**Error Codes**：1002（Token 无效）、1003（response_id 不存在）、1004（scope 不匹配）

---

### 7. GET /api/v1/evidence/{claim_id}

**描述**：获取某个 claim 的完整证据链（追溯到原始消息）。

**安全考量**：
- 只返回当前 scope 可见的证据
- evidence 中的 `chunk_id` → `chunk_span` → `normalized_message` → `raw_message` 溯源链完整，但 raw_message 只在当前 scope 有 consent 时返回

**Request Schema**：

```
GET /api/v1/evidence/{claim_id}?scope_id={scope_id}
Header: X-Remnant-Token: {token}
```

**Response Schema**：

```json
{
  "code": 0,
  "data": {
    "claim_id": "c_001",
    "evidence_chain": [
      {
        "evidence_id": "019a1b2c-ev1-ev1-ev1-ev1ev1ev1",
        "chunk_id": "019a1b2c-aaaa-bbbb-cccc-dddddddddddd",
        "evidence_type": "primary",
        "relevance_score": 0.95,
        "source_span": {
          "char_start": 156,
          "char_end": 203,
          "excerpt": "[妈妈] 春天的时候去西湖应该很漂亮"
        },
        "provenance_chain": {
          "chunk": {
            "id": "019a1b2c-aaaa-bbbb-cccc-dddddddddddd",
            "chunk_type": "conversation_segment",
            "time_range_start": "2024-03-15T10:30:00Z",
            "time_range_end": "2024-03-15T10:32:00Z"
          },
          "normalized_message": {
            "id": "019a1b2c-nm1-nm1-nm1-nm1nm1nm1",
            "speaker_normalized": "mother",
            "timestamp": "2024-03-15T10:30:22Z",
            "content": "春天的时候去西湖应该很漂亮"
          },
          "source_artifact": {
            "id": "019a1b2c-art1-art1-art1-art1art1art1",
            "file_type": "wechat_txt",
            "date_range_start": "2024-01-01",
            "date_range_end": "2024-06-30"
          }
        }
      }
    ]
  },
  "message": "ok"
}
```

**Error Codes**：1002（Token 无效）、1005（claim_id 不存在）、1004（scope 不匹配或 consent 未授权）

---

### 8. POST /api/v1/safety/evaluate

**描述**：手动触发安全评估，返回当前 SafetyDirective。对应 Chapter 10 的 `evaluate_safety` 函数。

**安全考量**：
- 此接口只读，不产生副作用
- 安全事件记录依赖前端按 `safety_directive` 执行后的回调
- 评估结果基于当前 session 的 8 项指标

**Request Schema**：

```json
{
  "scope_id": "019a1b2c-1111-1111-1111-111111111111",
  "session_id": "019a1b2c-sss1-sss1-sss1-sss1sss1sss1",
  "current_query": "妈妈最近好吗？",
  "indicators_override": null
}
```

**Response Schema**：

```json
{
  "code": 0,
  "data": {
    "indicators": {
      "session_duration_minutes": 25.3,
      "sessions_today_count": 2,
      "late_night_count": 0,
      "emotional_risk_score": 0.1,
      "dependency_phrases": 0,
      "farewell_refusal_count": 0,
      "user_age_flag": "adult",
      "recent_safety_events": 0
    },
    "directive": {
      "action": "ALLOW",
      "reason": "",
      "cooldown_minutes": 0,
      "template_id": "",
      "allow_llm": true,
      "disconnect_after_response": false,
      "safety_event_data": null
    },
    "triggered_policies": []
  },
  "message": "ok"
}
```

**Error Codes**：1001（指标无效）、1002（Token 无效）、1003（scope 或 session 不存在）

**Safety Considerations**：
- 如果评估结果为 `HARD_BREAK` 或 `ESCALATE`，前端应立即显示安全模板并暂停对话
- 如果为 `SOFT_BREAK`，前端应在对话界面显示建议
- 评估结果不持久化，前端需要根据 directive 采取行动后通过 `/api/v1/safety/event` 记录

---

### 9. POST /api/v1/scope/create

**描述**：创建新的关系作用域。

**安全考量**：
- 每个 relationship_scope 对应一个亲属视角，创建时必须声明与逝者的关系类型
- 创建操作记录审计日志（action=SCOPE_CREATE）
- 新 scope 自动创建默认 `scope_safety_policy` 和 `scope_permission` 记录

**Request Schema**：

```json
{
  "deceased_profile_id": "019a1b2c-2222-2222-2222-222222222222",
  "scope_name": "作为儿子",
  "relationship_type": "child",
  "scope_description": "我是妈妈的儿子，想回忆和她在一起的时光",
  "initial_permissions": {
    "can_query_memory": "allow",
    "can_browse_original": "ask",
    "can_add_oral_history": "allow",
    "can_view_financial": "deny",
    "can_view_medical": "deny",
    "can_view_intimate": "deny"
  },
  "safety_policy": {
    "max_session_minutes": 60,
    "max_sessions_daily": 5,
    "late_night_start": "22:00",
    "late_night_end": "06:00",
    "max_late_night_sessions": 2,
    "dependency_threshold": 0.7,
    "farewell_refusal_limit": 3,
    "hard_break_enabled": true,
    "cooldown_minutes": 30,
    "escalate_on_crisis": true
  }
}
```

**Response Schema**：

```json
{
  "code": 0,
  "data": {
    "scope_id": "019a1b2c-1111-1111-1111-111111111111",
    "deceased_profile_id": "019a1b2c-2222-2222-2222-222222222222",
    "scope_name": "作为儿子",
    "relationship_type": "child",
    "is_active": true,
    "created_at": "2024-12-01T14:00:00Z",
    "permissions": {
      "can_query_memory": "allow",
      "can_browse_original": "ask",
      "can_add_oral_history": "allow",
      "can_view_financial": "deny",
      "can_view_medical": "deny",
      "can_view_intimate": "deny"
    }
  },
  "message": "ok"
}
```

**Error Codes**：1001（参数无效）、1002（Token 无效）、1005（deceased_profile 不存在）、1006（scope 已存在）

---

### 10. POST /api/v1/scope/delete

**描述**：软删除或硬删除关系作用域。

**安全考量**：
- **软删除**：设置 `deleted_at` 时间戳，保留审计日志但标记数据不可访问
- **硬删除**：物理删除所有 scoped 数据（`interaction_session`、`interaction_message`、`retrieval_trace`、`response_claim`、`claim_evidence`）；`memory_chunk` 中 `scope_private` 类型的也删除；审计日志内容标记为 `REDACTED`
- 删除操作需要 **双重确认**：前端必须弹出确认对话框，API 需要 `confirmation_token`（由前端通过 `GET /api/v1/scope/confirm_delete/{scope_id}` 获取）
- 硬删除操作不可逆，审计日志保留但内容标记 REDACTED

**Request Schema**：

```json
{
  "scope_id": "019a1b2c-1111-1111-1111-111111111111",
  "deletion_type": "scope_soft_delete",
  "confirmation_token": "019a1b2c-conf-conf-conf-confconfconf",
  "reason": "不再需要这个视角"
}
```

**Response Schema**：

```json
{
  "code": 0,
  "data": {
    "scope_id": "019a1b2c-1111-1111-1111-111111111111",
    "deletion_type": "scope_soft_delete",
    "affected_tables": [
      "interaction_session",
      "interaction_message",
      "retrieval_trace",
      "response_claim",
      "claim_evidence",
      "data_subject_consent",
      "scope_permission",
      "scope_prompt_policy",
      "chunk_scope_visibility"
    ],
    "affected_rows": 1250,
    "completed_at": "2024-12-01T14:30:00Z",
    "audit_log_ids": ["019a1b2c-aud1-aud1-aud1-aud1aud1aud1"]
  },
  "message": "ok"
}
```

**Error Codes**：1001（参数无效）、1002（Token 无效）、1003（scope 不存在）、1004（confirmation_token 不匹配）、1007（scope 已被删除）

---

### 11. POST /api/v1/data/destroy

**描述**：数据销毁接口，支持 scope 级别和 deceased 级别的彻底销毁。

**安全考量**：
- **Scope 级别销毁**：删除指定 scope 的所有数据，包括交互历史
- **Deceased 级别销毁**：删除该逝者的所有数据（所有 scope + 逝者档案）
- 3 次覆写 + 安全删除（对应 Chapter 12 声音模型销毁策略，但应用于所有敏感数据）
- 操作不可逆
- 审计日志保留但内容标记 `REDACTED`
- 需要双重确认（`confirmation_token`）

**Request Schema**：

```json
{
  "target_type": "scope",
  "target_id": "019a1b2c-1111-1111-1111-111111111111",
  "confirmation_token": "019a1b2c-conf-conf-conf-confconfconf",
  "destroy_level": "secure",
  "reason": "用户要求彻底删除所有数据"
}
```

其中 `destroy_level`：
- `"soft"`：设置 `deleted_at`，数据不可访问但物理存在
- `"hard"`：物理删除行
- `"secure"`：3 次覆写 + 物理删除（用于声音模型等极度敏感数据）

**Response Schema**：

```json
{
  "code": 0,
  "data": {
    "target_type": "scope",
    "target_id": "019a1b2c-1111-1111-1111-111111111111",
    "destroy_level": "secure",
    "destroyed_tables": [
      "interaction_session",
      "interaction_message",
      "retrieval_trace",
      "response_claim",
      "claim_evidence",
      "data_subject_consent",
      "memory_chunk (scope_private)",
      "chunk_scope_visibility"
    ],
    "destroyed_rows": 1850,
    "redacted_audit_log_rows": 230,
    "completed_at": "2024-12-01T14:35:00Z"
  },
  "message": "ok"
}
```

**Error Codes**：1001（参数无效）、1002（Token 无效）、1003（target 不存在）、1004（confirmation_token 不匹配）、1007（数据已销毁）

---

## 15.3 SSE 事件类型汇总

| 事件类型 | 触发时机 | 数据内容 |
|---------|---------|---------|
| `safety_check` | 安全评估完成后 | SafetyDirective level 和 action |
| `retrieval_done` | 检索阶段完成后（Step 8） | trace_id, chunk_count, evidence_count |
| `token` | LLM 流式输出每个 token | `{"text": "..."}` |
| `claims` | Claim extraction 完成后（Step 12） | claims 数组（含 evidence） |
| `unsupported` | Unsupported claim 移除后（Step 14） | 被移除的 claims 列表 |
| `safety_directive` | 安全熔断触发时 | action, template_text |
| `audit` | 审计日志写入后 | scope_id, session_id, duration_ms |
| `done` | 流式响应结束 | 空 |

## 15.4 Trade-off 说明

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| 统一响应格式 | `{code, data, message}` | RESTful HTTP status | 本地应用场景，业务错误码比 HTTP status 更细粒度 |
| SSE 流式 | `text/event-stream` | WebSocket | v0.1 只需单向流式；SSE 调试方便（浏览器可直接看） |
| 错误码分层 | 1xxx 通用 / 2xxx 安全 / 3xxx 引擎 / 4xxx 授权 | 单一错误码空间 | 分层便于分类处理和国际化 |
| 数据销毁 API | 独立 `/data/destroy` | 复用 `/scope/delete` with level | scope 删除和数据销毁语义不同，销毁涉及物理操作 |
| Claim 单独获取 | `/claims/{response_id}` | 嵌入 SSE 流 | 流式输出中只发送 claim_id，详细信息按需获取，减少流传输量 |
| 证据链溯源 | `/evidence/{claim_id}` | 嵌入 claim 响应 | 证据链包含到 raw_message 的完整溯源，数据量大，按需获取更合理 |

---

# Chapter 16: Development Roadmap

## 16.1 总览

```
M0 ─── M1 ─── M4a ─── M2 ─── M3 ─── M5 ─── M6
 │      │       │       │       │      │      │
 │      │       │       │       │      │      └─ Developer Preview
 │      │       │       │       │      └─ Safety Middleware
 │      │       │       │       └─ Provenance Response
 │      │       │       └─ Local Retrieval
 │      │       └─ Scope DAO + 基础隔离
 │      └─ ETL MVP
 └─ Repo Bootstrap
                          M4b ──┘     └─┘
                           ↑          ↑
                     (与 M2-M3 并行)  (与 M3-M4b 并行)
```

## 16.2 Milestone 0: Repo Bootstrap

**目标**：建立 monorepo 工程基础设施，配置开发、构建、测试、CI/CD 环境。

**关键交付物**：

| 交付物 | 路径 | 说明 |
|--------|------|------|
| Monorepo 结构 | `remnant-monorepo/` | 根目录包含 `packages/`、`apps/`、`docs/` |
| Python backend 骨架 | `packages/remnant-core/` | FastAPI 应用骨架 + SQLite 初始化脚本 |
| Tauri shell 骨架 | `apps/remnant-desktop/` | Tauri 2.0 项目初始化 + WebView 占位 |
| SQLite/SQLCipher 初始化 | `packages/remnant-store/` | Chapter 4 全部 DDL 的 migration 脚本 |
| 测试框架 | `tests/` | pytest + playwright 配置 |
| CI/CD 配置 | `.github/workflows/` | lint + test + build 管线 |

**验收标准**：

- [ ] `pnpm install && pnpm build` 成功
- [ ] `python -m pytest tests/` 通过（至少 1 个 smoke test）
- [ ] Tauri 应用可启动，显示空白 WebView
- [ ] Python sidecar 可启动，`GET /health` 返回 200
- [ ] SQLCipher 数据库文件可创建，所有 17 张表 + 5 个 trigger 可迁移
- [ ] FTS5 虚拟表可创建
- [ ] CI 管线全绿

**预计时间范围**：2 周

**依赖关系**：无

## 16.3 Milestone 1: ETL MVP

**目标**：实现微信 txt 导入的完整 ETL 管道，从原始文件到可检索的 memory_chunk。

**关键交付物**：

| 交付物 | 路径 | 说明 |
|--------|------|------|
| WechatTxtParser | `packages/remnant-etl/parsers/wechat_txt.py` | Chapter 3 的微信 txt 解析器 |
| Normalize + Clean pipeline | `packages/remnant-etl/pipeline.py` | 规范化 + 清洗管道 |
| Dynamic chunking | `packages/remnant-etl/chunking.py` | Chapter 3 的动态分块算法 |
| Source span attachment | `packages/remnant-etl/spans.py` | chunk 到 normalized_message 的溯源映射 |
| Hash generation | `packages/remnant-etl/hash.py` | source_artifact.file_hash + chunk.chunk_hash |
| ETL integration test | `tests/test_etl.py` | 端到端 ETL 测试（微信 txt → memory_chunk） |
| Sample dataset | `tests/fixtures/wechat_sample.txt` | 100+ 条消息的微信导出样本 |

**验收标准**：

- [ ] 微信 txt 文件可导入，`raw_message` 表有数据且不可修改（trigger 测试）
- [ ] `normalized_message` 表有数据，说话人统一正确
- [ ] `memory_chunk` 表有数据，`chunk_hash` 正确生成
- [ ] `memory_chunk_span` 表可追溯到 `normalized_message`
- [ ] `source_artifact.file_hash` 与文件 SHA-256 一致
- [ ] 清洗标记（FILTERED）不影响 raw_message
- [ ] 重复导入同一文件不创建新记录（file_hash 去重）
- [ ] ETL 管道幂等：同一输入重新执行，产出相同

**预计时间范围**：3 周

**依赖关系**：M0

## 16.4 Milestone 2: Local Retrieval

**目标**：实现本地混合检索（FTS5 + sqlite-vec），支持 scope 过滤和 rerank。

**关键交付物**：

| 交付物 | 路径 | 说明 |
|--------|------|------|
| FTS5 搜索模块 | `packages/remnant-store/fts.py` | FTS5 全文搜索 + scope 过滤 |
| sqlite-vec 向量搜索 | `packages/remnant-store/vector.py` | sqlite-vec 向量搜索 + scope 过滤 |
| 混合检索合并 | `packages/remnant-core/retrieval.py` | FTS + Vector 合并去重 |
| Time-aware retrieval | `packages/remnant-core/retrieval.py` | 时间感知加权 |
| Speaker-aware retrieval | `packages/remnant-core/retrieval.py` | 说话人感知加权 |
| Rerank 模块 | `packages/remnant-core/rerank.py` | 综合排序 + MMR 多样性 |
| Retrieval trace 记录 | `packages/remnant-core/trace.py` | 检索过程记录到 `retrieval_trace` 表 |
| Embedding 服务 | `packages/remnant-core/embedding.py` | 本地 embedding 模型加载和推理 |

**验收标准**：

- [ ] FTS5 搜索可按关键词检索 chunk，结果包含 `rank` 分数
- [ ] sqlite-vec 向量搜索可在 top-K 内找到语义相关 chunk
- [ ] 混合检索结果合并去重无遗漏
- [ ] **Scope 过滤正确**：scope A 的查询不返回 scope B 的任何 chunk（M6 指标 = 0）
- [ ] Time-aware 权重：带时间引用的查询，时间匹配的 chunk 排序提升
- [ ] Speaker-aware 权重：指定说话人的查询，匹配说话人的 chunk 排序提升
- [ ] Rerank 后 top-K 结果多样性合理（无连续 5+ 条同一说话人）
- [ ] `retrieval_trace` 表记录完整的检索过程（FTS 结果、Vector 结果、rerank 结果）
- [ ] Recall@10 ≥ 0.80（标准对话测试集）

**预计时间范围**：3 周

**依赖关系**：M0, M1, M4a（检索的 scope 过滤依赖 Scope DAO 层）

## 16.5 Milestone 3: Provenance Response

**目标**：实现 Claim-level Response Protocol（Chapter 6）和 Deterministic RAG Pipeline（Chapter 7）的 Steps 9-15，实现 E2E 查询→响应。

**关键交付物**：

| 交付物 | 路径 | 说明 |
|--------|------|------|
| Claim schema 实现 | `packages/remnant-core/claims.py` | Claim + Evidence 数据结构 |
| Claim-Evidence alignment | `packages/remnant-core/alignment.py` | Step 13: claim 与 evidence 对齐 |
| Unsupported claim removal | `packages/remnant-core/rejection.py` | Step 14: 无证据 claim 移除 |
| Response rendering | `packages/remnant-core/renderer.py` | Step 15: 按 claim 状态组装 response_text |
| Evidence card UI | `apps/remnant-desktop/src/components/EvidenceCard.tsx` | 证据卡片组件（溯源可点击） |
| Claim 标注 UI | `apps/remnant-desktop/src/components/ClaimView.tsx` | Claim 标注渲染组件 |
| 审计日志写入 | `packages/remnant-policy/audit.py` | Step 16: 审计日志持久化 |

**验收标准**：

- [ ] 端到端查询流程可用：用户输入 → 检索 → 拼装 → Claim 生成 → 渲染
- [ ] 每个 response_text 中的事实性句子有 `{claim:XXX}` 标注
- [ ] Claim 点击可跳转到原始证据卡片
- [ ] 证据卡片显示溯源链：chunk → span → normalized_message → source_artifact
- [ ] `unsupported_memory` 类型的 claim 不出现在 response_text 中（M3 = 0）
- [ ] `inferred_but_supported` 类型 claim 使用限定词（"可能""似乎"）
- [ ] Evidence Coverage ≥ 0.95（M1 指标）
- [ ] Citation Accuracy ≥ 0.90（M2 指标）
- [ ] Refusal Correctness ≥ 0.85（M4 指标）

**预计时间范围**：4 周

**依赖关系**：M0, M1, M2

## 16.6 Milestone 4: Relationship Scope

**目标**：实现多亲属隔离机制，包括 scope 创建、权限管理、scope 删除。

> **⚠️ 拆分说明**：M4 拆分为 M4a（Scope DAO + 基础隔离）和 M4b（Scope UI + 权限管理 + 删除流程）。
> M4a 必须在 M2 之前完成，因为 FTS5/Vector 检索的 scope 过滤依赖 Scope DAO 层。
> M4b 可以与 M3 并行。

### M4a: Scope DAO + 基础隔离

**关键交付物**：

| 交付物 | 路径 | 说明 |
|--------|------|------|
| Scope DAO 层 | `packages/remnant-store/scope_dao.py` | scope CRUD + 强制 WHERE 过滤 |
| Scope 过滤中间件 | `packages/remnant-core/scope_filter.py` | 所有查询自动附加 scope WHERE 条件 |
| Consent 基础检查 | `packages/remnant-policy/consent.py` | `data_subject_consent` 读取和检查 |
| Chunk 可见性查询 | `packages/remnant-store/chunk_visibility.py` | `get_visible_chunk_ids(scope_id)` |
| Scope API 端点（基础） | `packages/remnant-core/api/scope.py` | `/scope/create`, `/scope/list` |

**验收标准**：

- [ ] 可创建多个 scope（"作为儿子"、"作为朋友"等）
- [ ] scope A 的查询不返回 scope B 的交互数据（M6 = 0）
- [ ] `get_visible_chunk_ids(scope_id)` 正确返回：私有 chunk + 共享 chunk + 全局 chunk
- [ ] Consent 检查可阻断未授权数据访问
- [ ] Raw Data Integrity = 1.0（scope 操作不影响原始数据）

**预计时间范围**：2 周（Week 5-6，与 M1 尾部同步）

**依赖关系**：M0, M1

### M4b: Scope UI + 权限管理 + 删除流程

**关键交付物**：

| 交付物 | 路径 | 说明 |
|--------|------|------|
| Scope 创建 UI | `apps/remnant-desktop/src/pages/ScopeCreate.tsx` | 创建关系作用域向导 |
| Scope 管理 UI | `apps/remnant-desktop/src/pages/ScopeManage.tsx` | 权限配置、scope 切换 |
| Chunk 可见性管理 UI | `apps/remnant-desktop/src/components/ChunkVisibility.tsx` | 提升/降级共享 chunk |
| Scope 删除流程 | `packages/remnant-store/scope_deletion.py` | 软删除 + 硬删除 + 审计日志 |
| Scope API 端点（完整） | `packages/remnant-core/api/scope.py` | `/scope/delete`, `/scope/permissions` |

**验收标准**：

- [ ] 通过 UI 可创建/切换/管理 scope
- [ ] 权限矩阵（`scope_permission`）正确生效：`deny` 权限的查询被拒绝
- [ ] chunk 可见性提升（`scope_private` → `scope_shared`）需显式用户操作和授权记录
- [ ] scope 删除后数据不可访问，审计日志保留但内容标记 REDACTED
- [ ] scope A 的交互历史对 scope B 不可见

**预计时间范围**：2 周

**依赖关系**：M4a, M2

## 16.7 Milestone 5: Safety Middleware

**目标**：实现安全熔断机制，包括 8 项指标采集、7 种触发策略、SafetyDirective 生成。

**关键交付物**：

| 交付物 | 路径 | 说明 |
|--------|------|------|
| Safety indicators collector | `packages/remnant-policy/safety.py` | 8 项指标采集函数 |
| Safety evaluator | `packages/remnant-policy/safety.py` | `evaluate_safety()` 核心逻辑 |
| SafetyDirective 生成 | `packages/remnant-policy/safety.py` | SafetyDirective JSON Schema 输出 |
| Safety event recorder | `packages/remnant-policy/safety.py` | `safety_event` 表写入 |
| Soft break UI | `apps/remnant-desktop/src/components/SoftBreak.tsx` | 建议休息提示组件 |
| Hard break UI | `apps/remnant-desktop/src/components/HardBreak.tsx` | 强制暂停组件 |
| Escalate UI | `apps/remnant-desktop/src/components/Escalate.tsx` | 危机资源展示组件 |
| Safety config UI | `apps/remnant-desktop/src/pages/SafetySettings.tsx` | 安全策略配置页面 |
| Scope safety policy 默认值 | `packages/remnant-store/migrations/` | `scope_safety_policy` 表默认值 |

**验收标准**：

- [ ] 8 项安全指标可正确采集（会话时长、今日会话数、深夜使用、情绪风险分、依赖表达次数、拒绝对话次数、年龄标记、近7天安全事件）
- [ ] T1-T7 七种触发策略正确执行
- [ ] `ALLOW` 不影响正常对话
- [ ] `SOFT_BREAK` 添加缓冲语并建议休息
- [ ] `HARD_BREAK` 停止当前会话并显示模板消息
- [ ] `ESCALATE` 显示危机热线信息
- [ ] `safety_event` 表正确记录每次熔断事件
- [ ] Safety Trigger Recall ≥ 0.95（M12 指标）
- [ ] Safety Trigger Precision ≥ 0.80（M11 指标）
- [ ] 深夜使用检测（22:00-06:00）正确触发

**预计时间范围**：3 周

**依赖关系**：M0, M3（safety 在 RAG pipeline Step 1 执行）

## 16.8 Milestone 6: Developer Preview

**目标**：提供可用的命令行工具和桌面 alpha 版本，包含样本数据集和评测脚本，供开发者体验和评测。

**关键交付物**：

| 交付物 | 路径 | 说明 |
|--------|------|------|
| CLI 工具 | `packages/remnant-cli/` | 命令行管理工具：导入、查询、scope 管理、审计查看 |
| Desktop Alpha | `apps/remnant-desktop/` | Tauri 桌面应用 alpha 版本 |
| Sample dataset | `tests/fixtures/sample_dataset/` | 包含微信 txt、日记、邮件等多样本 |
| Evaluation script | `tools/evaluate.py` | M1-M12 全部评测指标自动化脚本 |
| Security review checklist | `docs/security_review_checklist.md` | 安全审查清单 |
| API documentation | `docs/api_reference.md` | Chapter 15 全部接口的 OpenAPI 文档 |

**验收标准**：

- [ ] CLI 可完成完整流程：导入 → 索引 → 查询 → 查看 claim → 查看 evidence
- [ ] Desktop Alpha 可启动并完成完整交互流程
- [ ] Sample dataset 可成功导入并检索
- [ ] 评测脚本可运行并输出 M1-M12 所有指标报告
- [ ] Security review checklist 覆盖 Chapter 13 全部 15 种威胁
- [ ] API documentation 可通过 `/docs` 端点访问（FastAPI Swagger UI）
- [ ] 无 known P0/P1 bug（P0：数据丢失、scope 隔离泄露、安全熔断失效；P1：证据溯源断裂、检索崩溃）

**预计时间范围**：2 周

**依赖关系**：M0, M1, M2, M3, M4b, M5

## 16.9 里程碑甘特图

```
Week:  1-2     3-4     5-6     7-9     10-13   14-15   16-17   18-19
       ├───────┼───────┼───────┼───────┼───────┼───────┼───────┤
  M0:  ███████
  M1:          █████████
  M4a:                 ████████  ← Scope DAO 必须在 M2 前完成
  M2:                          █████████████
  M3:                                  ██████████████
  M4b:                                  █████████  ← 与 M3 并行
  M5:                                          █████████
  M6:                                                  ████████
                                                              ▼
                                                        Developer
                                                         Preview
```

**关键路径**：M0 → M1 → M4a → M2 → M3（核心 RAG 流水线 + Scope 过滤）

**并行路径**：M4b（Scope UI）与 M3 并行；M5（Safety）与 M3-M4b 并行

## 16.10 Trade-off 说明

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| M1 仅支持微信 txt | 单格式 MVP | 6 种格式并行 | 先跑通一种格式的完整管道，再扩展其他格式 |
| M2 优先检索质量 | 先做检索再做响应 | 检索和响应并行 | Evidence-first 原则要求检索是基础，没有好的检索就没有好的证据 |
| M3 Claim-level 先于 Safety | 先做响应协议 | Safety 中间件先行 | 没有 Claim 结构就无法验证 Evidence-first 原则；Safety 在 M5 实现，M3 中使用简化版 |
| M4 拆分为 M4a + M4b | 拆分 DAO 和 UI | 集中在 M4 一个 milestone | M4a（Scope DAO + 基础隔离）必须在 M2 之前完成，否则 FTS5/Vector 检索的 scope 过滤无法实现；M4b（UI + 权限管理 + 删除）可与 M3 并行 |
| M5 Safety 在 M3 之后 | Safety 与 M3 并行 | 先于 M3 | Safety 中间件依赖 Claim 结构和交互历史，必须在查询流程基本可用后实现 |
| 总时长 19 周 | 19 周 | 12 周（激进）/ 30 周（保守） | M4 拆分后关键路径优化，总时长从 20 周缩减至 19 周 |
| 评测脚本自动化 | CI/CD 集成 | 手动评测 | 自动化评测确保每个 milestone 都可回归验证 |