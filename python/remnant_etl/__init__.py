"""Remnant ETL — 数据解析、清洗、分块管道。

本包负责将原始数据（微信聊天记录、日记、邮件等）通过 ETL 管道
转换为标准化的记忆分块（memory_chunk），供后续 RAG 检索使用。

子模块:
    parsers:    数据解析器（微信 TXT、微信 DB、日记、邮件等）
    cleaners:   清洗管道（去重、敏感词、系统消息过滤）
    chunkers:   分块算法（滑动窗口、话题切割、语义分块）
    pipeline:   ETL Pipeline 入口（Protocol + ABC 定义）
"""