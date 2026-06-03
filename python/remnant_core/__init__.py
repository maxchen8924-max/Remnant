"""Remnant Core — RAG、Claim、Prompt 核心逻辑。

本包实现记忆检索增强生成（RAG）、事实声明（Claim）提取与对齐、
以及 Prompt 构建的核心逻辑。

子模块:
    rag:         RAG Pipeline 骨架（检索、重排序、证据验证）
    claim:       Claim 提取与对齐骨架
    claims:      Claim 溯源响应数据结构（M3 新增）
    evidence:    Evidence Sufficiency Check（M3 新增）
    alignment:   Claim Alignment 对齐（M3 新增）
    rejection:   Unsupported Claim Removal（M3 新增）
    renderer:    Response Rendering（M3 新增）
    prompt:      Prompt 构建骨架
    models:      Pydantic 数据模型
"""