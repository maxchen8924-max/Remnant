"""Remnant Core — RAG、Claim、Prompt 核心逻辑。

本包实现记忆检索增强生成（RAG）、事实声明（Claim）提取与对齐、
以及 Prompt 构建的核心逻辑。

子模块:
    rag:    RAG Pipeline 骨架（检索、重排序、证据验证）
    claim:  Claim 提取与对齐骨架
    prompt: Prompt 构建骨架
    models: Pydantic 数据模型
"""