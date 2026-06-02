"""Remnant Store — SQLite/SQLCipher 存储层。

本包负责:
- db:     数据库连接管理（SQLCipher 支持）
- schema: DDL 定义 + init_db()
- scope_dao: Scope DAO
- chunk_dao: Chunk DAO
- migrations: 迁移脚本目录
"""