"""Remnant Bridge — FastAPI HTTP 桥接层。

本包实现 Remnant 后端的 HTTP API，绑定 127.0.0.1:18731。
子模块:
    main:        FastAPI 入口
    routes:      API 路由
    middleware:   中间件（鉴权、审计）
    config:      配置常量
"""