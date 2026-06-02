"""DDL 初始化测试 — 验证所有 24 张表、索引、触发器、FTS5 虚拟表。"""

from __future__ import annotations

import sqlite3

import pytest

from remnant_store.schema import (
    DDL_INDEXES,
    DDL_TABLES,
    DDL_TRIGGERS,
    DDL_VIRTUAL_TABLE_TEMPLATES,
    get_index_names,
    get_table_names,
    get_trigger_names,
    init_db,
)


class TestSchemaInitialization:
    """测试 schema 初始化。"""

    def test_init_db_memory(self) -> None:
        """测试内存数据库初始化。"""
        conn = init_db(":memory:")
        tables = get_table_names(conn)
        assert len(tables) >= 24
        conn.close()

    def test_init_db_file(self, tmp_path) -> None:
        """测试文件数据库初始化。"""
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)
        tables = get_table_names(conn)
        assert len(tables) >= 24
        conn.close()

    def test_all_24_tables_exist(self, db: sqlite3.Connection) -> None:
        """验证全部 24 张表都已创建。"""
        tables = get_table_names(db)
        expected_tables = [
            "deceased_profile",
            "data_subject_consent",
            "relationship_scope",
            "source_artifact",
            "raw_message",
            "normalized_message",
            "memory_chunk",
            "memory_chunk_span",
            "memory_annotation",
            "embedding_index_ref",
            "retrieval_trace",
            "response_claim",
            "claim_evidence",
            "interaction_session",
            "interaction_message",
            "safety_event",
            "audit_log",
            "scope_permission",
            "scope_prompt_policy",
            "chunk_scope_visibility",
            "scope_safety_policy",
            "scope_deletion_log",
            "voice_profile",
            "voice_synthesis_log",
        ]
        for table in expected_tables:
            assert table in tables, f"表 {table} 未找到"

    def test_fts5_virtual_table_exists(self, db: sqlite3.Connection) -> None:
        """验证 FTS5 虚拟表已创建。"""
        tables = get_table_names(db)
        assert "memory_chunk_fts" in tables

    def test_all_indexes_created(self, db: sqlite3.Connection) -> None:
        """验证所有索引已创建。"""
        indexes = get_index_names(db)
        # 至少应有白皮书定义的关键索引
        expected_indexes = [
            "idx_deceased_profile_name",
            "idx_consent_scope",
            "idx_scope_deceased",
            "idx_artifact_deceased",
            "idx_raw_source",
            "idx_chunk_scope",
            "idx_session_scope",
            "idx_audit_action",
        ]
        for idx in expected_indexes:
            assert idx in indexes, f"索引 {idx} 未找到"

    def test_all_triggers_created(self, db: sqlite3.Connection) -> None:
        """验证所有触发器已创建。"""
        triggers = get_trigger_names(db)
        expected_triggers = [
            "trg_prevent_raw_message_update",
            "trg_prevent_raw_message_delete",
            "trg_prevent_audit_update",
            "trg_prevent_audit_delete",
            "trg_chunk_fts_insert",
            "trg_chunk_fts_update",
            "trg_chunk_fts_delete",
            "trg_scope_soft_delete_chunks",
        ]
        for trigger in expected_triggers:
            assert trigger in triggers, f"触发器 {trigger} 未找到"

    def test_raw_message_immutable_update(self, db: sqlite3.Connection) -> None:
        """测试 raw_message 不可变触发器 — 禁止 UPDATE。"""
        # 先插入依赖数据
        db.execute(
            "INSERT INTO deceased_profile (id, name) VALUES ('dp-1', 'Test')",
        )
        db.execute(
            "INSERT INTO source_artifact (id, deceased_profile_id, file_path, file_hash, file_size, file_type) "
            "VALUES ('sa-1', 'dp-1', '/test.txt', 'hash1', 100, 'wechat_txt')",
        )
        db.execute(
            "INSERT INTO raw_message (id, source_artifact_id, speaker, content) "
            "VALUES ('rm-1', 'sa-1', 'A', 'Hello')",
        )
        db.commit()

        # 尝试 UPDATE 应该触发 RAISE ABORT
        with pytest.raises(Exception, match="immutable"):
            db.execute("UPDATE raw_message SET content = 'Modified' WHERE id = 'rm-1'")

    def test_raw_message_immutable_delete(self, db: sqlite3.Connection) -> None:
        """测试 raw_message 不可变触发器 — 禁止 DELETE。"""
        # 先插入依赖数据
        db.execute(
            "INSERT INTO deceased_profile (id, name) VALUES ('dp-2', 'Test2')",
        )
        db.execute(
            "INSERT INTO source_artifact (id, deceased_profile_id, file_path, file_hash, file_size, file_type) "
            "VALUES ('sa-2', 'dp-2', '/test2.txt', 'hash2', 200, 'wechat_txt')",
        )
        db.execute(
            "INSERT INTO raw_message (id, source_artifact_id, speaker, content) "
            "VALUES ('rm-2', 'sa-2', 'B', 'World')",
        )
        db.commit()

        # 尝试 DELETE 应该触发 RAISE ABORT
        with pytest.raises(Exception, match="immutable"):
            db.execute("DELETE FROM raw_message WHERE id = 'rm-2'")

    def test_audit_log_immutable_update(self, db: sqlite3.Connection) -> None:
        """测试 audit_log 不可变触发器 — 禁止 UPDATE。"""
        db.execute(
            "INSERT INTO audit_log (id, action, actor, target_type, target_id) "
            "VALUES ('al-1', 'DATA_IMPORT', 'user', 'source_artifact', 'sa-1')",
        )
        db.commit()

        with pytest.raises(Exception, match="append-only"):
            db.execute("UPDATE audit_log SET action = 'MODIFIED' WHERE id = 'al-1'")

    def test_audit_log_immutable_delete(self, db: sqlite3.Connection) -> None:
        """测试 audit_log 不可变触发器 — 禁止 DELETE。"""
        db.execute(
            "INSERT INTO audit_log (id, action, actor, target_type, target_id) "
            "VALUES ('al-2', 'DATA_ACCESS', 'system', 'raw_message', 'rm-1')",
        )
        db.commit()

        with pytest.raises(Exception, match="append-only"):
            db.execute("DELETE FROM audit_log WHERE id = 'al-2'")

    def test_fts5_sync_trigger_insert(self, db: sqlite3.Connection) -> None:
        """测试 FTS5 同步触发器 — INSERT 时自动同步。"""
        # 插入依赖数据
        db.execute(
            "INSERT INTO deceased_profile (id, name) VALUES ('dp-3', 'Test3')",
        )
        db.execute(
            "INSERT INTO relationship_scope (id, deceased_profile_id, scope_name, relationship_type) "
            "VALUES ('rs-1', 'dp-3', '作为儿子', 'child')",
        )
        db.execute(
            "INSERT INTO source_artifact (id, deceased_profile_id, file_path, file_hash, file_size, file_type) "
            "VALUES ('sa-3', 'dp-3', '/test3.txt', 'hash3', 300, 'wechat_txt')",
        )
        # 注意: unicode61 tokenizer 不支持中文分词，使用空格分隔的文本模拟 jieba 预分词
        db.execute(
            "INSERT INTO memory_chunk "
            "(id, source_artifact_id, relationship_scope_id, chunk_hash, chunk_type, content, token_count) "
            "VALUES ('mc-1', 'sa-3', 'rs-1', 'chash1', 'conversation_segment', '爸爸 喜欢 喝茶', 10)",
        )
        db.commit()

        # 验证 FTS5 同步 — 使用空格分隔的词进行搜索
        cursor = db.execute("SELECT * FROM memory_chunk_fts WHERE memory_chunk_fts MATCH '喝茶'")
        results = cursor.fetchall()
        assert len(results) >= 1

    def test_scope_soft_delete_cascade(self, db: sqlite3.Connection) -> None:
        """测试软删除级联触发器。"""
        # 插入完整的作用域数据
        db.execute(
            "INSERT INTO deceased_profile (id, name) VALUES ('dp-4', 'Test4')",
        )
        db.execute(
            "INSERT INTO relationship_scope (id, deceased_profile_id, scope_name, relationship_type) "
            "VALUES ('rs-2', 'dp-4', '作为朋友', 'friend')",
        )
        db.execute(
            "INSERT INTO source_artifact (id, deceased_profile_id, file_path, file_hash, file_size, file_type) "
            "VALUES ('sa-4', 'dp-4', '/test4.txt', 'hash4', 400, 'wechat_txt')",
        )
        db.execute(
            "INSERT INTO memory_chunk "
            "(id, source_artifact_id, relationship_scope_id, chunk_hash, chunk_type, content, token_count) "
            "VALUES ('mc-2', 'sa-4', 'rs-2', 'chash2', 'conversation_segment', '一起去爬山', 10)",
        )
        db.execute(
            "INSERT INTO interaction_session (id, relationship_scope_id, deceased_profile_id) "
            "VALUES ('is-1', 'rs-2', 'dp-4')",
        )
        db.commit()

        # 软删除 scope
        db.execute(
            "UPDATE relationship_scope SET deleted_at = '2025-01-01T00:00:00.000Z' WHERE id = 'rs-2'",
        )
        db.commit()

        # 验证级联：memory_chunk 被软删除
        cursor = db.execute("SELECT deleted_at FROM memory_chunk WHERE id = 'mc-2'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] is not None

        # 验证审计日志
        cursor = db.execute(
            "SELECT * FROM audit_log WHERE action = 'DATA_DESTROY' AND target_id = 'rs-2'"
        )
        audit_rows = cursor.fetchall()
        assert len(audit_rows) >= 1

    def test_foreign_keys_enabled(self, db: sqlite3.Connection) -> None:
        """验证外键约束已启用。"""
        cursor = db.execute("PRAGMA foreign_keys")
        result = cursor.fetchone()
        assert result[0] == 1

    def test_wal_mode_enabled(self, file_db: sqlite3.Connection) -> None:
        """验证 WAL 模式已启用（仅文件数据库支持 WAL，内存数据库不支持）。"""
        cursor = file_db.execute("PRAGMA journal_mode")
        result = cursor.fetchone()
        assert result[0].lower() == "wal"

    def test_data_subject_consent_scope_id_field(self, db: sqlite3.Connection) -> None:
        """验证 data_subject_consent 表使用 relationship_scope_id（不是 scope_id）。"""
        cursor = db.execute("PRAGMA table_info(data_subject_consent)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "relationship_scope_id" in columns
        assert "scope_id" not in columns

    def test_scope_permission_scope_id_field(self, db: sqlite3.Connection) -> None:
        """验证 scope_permission 表使用 relationship_scope_id。"""
        cursor = db.execute("PRAGMA table_info(scope_permission)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "relationship_scope_id" in columns
        assert "scope_id" not in columns

    def test_memory_chunk_chunk_type_values(self, db: sqlite3.Connection) -> None:
        """验证 memory_chunk.chunk_type 支持 6 种枚举。"""
        valid_types = [
            "conversation_segment",
            "diary_entry",
            "letter",
            "mixed",
            "user_provided_context",
            "transcription",
        ]
        # 插入依赖数据
        db.execute(
            "INSERT INTO deceased_profile (id, name) VALUES ('dp-5', 'Test5')",
        )
        db.execute(
            "INSERT INTO source_artifact (id, deceased_profile_id, file_path, file_hash, file_size, file_type) "
            "VALUES ('sa-5', 'dp-5', '/test5.txt', 'hash5', 500, 'wechat_txt')",
        )

        for i, chunk_type in enumerate(valid_types):
            db.execute(
                "INSERT INTO memory_chunk "
                "(id, source_artifact_id, chunk_hash, chunk_type, content, token_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f"mc-type-{i}", "sa-5", f"chash-type-{i}", chunk_type, f"content-{i}", 5),
            )
        db.commit()

        # 验证所有类型都能查询到
        cursor = db.execute("SELECT DISTINCT chunk_type FROM memory_chunk WHERE id LIKE 'mc-type-%'")
        types = {row[0] for row in cursor.fetchall()}
        assert types == set(valid_types)

    def test_init_db_idempotent(self, db: sqlite3.Connection) -> None:
        """测试重复调用 init_db 不会报错（IF NOT EXISTS）。"""
        # 再次初始化不应出错
        from remnant_store.schema import DDL_INDEXES, DDL_TABLES, DDL_TRIGGERS, DDL_VIRTUAL_TABLE_TEMPLATES, _FTS5_TOKENIZER_FALLBACK

        for ddl in DDL_TABLES:
            db.execute(ddl)
        for ddl in DDL_INDEXES:
            db.execute(ddl)
        for ddl in DDL_TRIGGERS:
            db.execute(ddl)
        for template in DDL_VIRTUAL_TABLE_TEMPLATES:
            ddl = template.format(tokenizer=_FTS5_TOKENIZER_FALLBACK)
            db.execute(ddl)
        db.commit()

        # 表数量不应翻倍
        tables = get_table_names(db)
        assert len(tables) >= 24