"""Remnant Policy — 安全、授权、过滤中间件。

本包实现系统级安全策略:
- safety:       安全中间件（反依赖、深夜使用、过度使用等）
- consent:      授权检查
- scope_filter: Scope 过滤中间件（确保查询严格隔离）
"""