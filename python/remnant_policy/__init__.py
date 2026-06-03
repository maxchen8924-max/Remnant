"""Remnant Policy — 安全、授权、过滤、审计中间件。

本包实现系统级策略:
- safety:       安全中间件（Ch10 完整实现：8指标采集 + 7触发策略 + 事件入库）
- consent:      授权检查
- scope_filter: Scope 过滤中间件（确保查询严格隔离）
- audit:        审计日志（M3 新增：response_claim + claim_evidence + interaction 写入）

使用时直接从子模块导入:
    from remnant_policy.safety import evaluate_safety, handle_directive
"""