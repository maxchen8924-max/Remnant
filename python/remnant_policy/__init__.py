"""Remnant Policy — 安全、授权、过滤、审计中间件。

本包实现系统级策略:
- safety:       安全中间件（反依赖、深夜使用、过度使用等）
- consent:      授权检查
- scope_filter: Scope 过滤中间件（确保查询严格隔离）
- audit:        审计日志（M3 新增：response_claim + claim_evidence + interaction 写入）
"""