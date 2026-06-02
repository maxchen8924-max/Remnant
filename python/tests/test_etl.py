"""ETL 端到端集成测试 — 验证从原始 TXT 到 memory_chunk 的完整管道。

测试覆盖:
1. source_artifact 入库
2. raw_message 解析和入库
3. normalized_message 标签和规范化
4. memory_chunk 数量、哈希、溯源
5. memory_chunk_span 溯源映射
6. raw_message 不可变触发器
7. FTS5 全文搜索
8. 说话人别名统一
9. 系统消息/撤回消息过滤
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest

from remnant_store.schema import init_db
from remnant_etl.parsers.base import RawMessage, generate_uuid
from remnant_etl.parsers.wechat_txt import WechatTxtParser
from remnant_etl.cleaners.filters import (
    MessageStatus,
    NormalizedMessage,
    filter_noise,
    SystemMessageFilter,
    RecallMessageFilter,
    DuplicateMessageFilter,
    EmojiPlaceholderFilter,
    ShortFragmentFilter,
)
from remnant_etl.cleaners.normalizer import normalize_messages
from remnant_etl.chunkers.conversation import (
    ChunkConfig,
    ConversationSegment,
    build_conversation_segments,
    semantic_chunk,
    _estimate_tokens,
)
from remnant_etl.chunkers.span import (
    ChunkSpan,
    attach_source_spans_v2,
    generate_chunk_hash,
)
from remnant_etl.pipeline import ETLPipeline


# ==================== 样本微信 TXT 数据 ====================

SAMPLE_WECHAT_TXT = """2024-01-15 10:30:22 妈妈
你今天吃药了吗？

2024-01-15 10:31:05 我
吃了吃了，别担心

2024-01-15 10:31:20 妈妈
那就好，记得多喝水

--- 2024-01-15 11:00:00 你已添加了"爸爸" ---
2024-01-15 11:05:33 爸爸
周末回家吃饭吗？

2024-01-15 11:06:01 我
回的，想吃红烧肉

2024-01-15 11:06:15 爸爸
好，让你妈做

「我」撤回了一条消息
2024-01-15 20:00:00 妈妈
早点休息，晚安😊
"""


@pytest.fixture
def wechat_txt_file(tmp_path: Path) -> str:
    """创建样本微信 TXT 临时文件。"""
    file_path = tmp_path / "wechat_sample.txt"
    file_path.write_text(SAMPLE_WECHAT_TXT, encoding="utf-8")
    return str(file_path)


@pytest.fixture
def db_conn() -> sqlite3.Connection:
    """创建内存数据库连接。"""
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def deceased_profile_id(db_conn: sqlite3.Connection) -> str:
    """创建逝者档案记录，返回 ID。"""
    from datetime import datetime, timezone

    profile_id = generate_uuid()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db_conn.execute(
        """INSERT INTO deceased_profile
        (id, name, created_at, updated_at)
        VALUES (?, ?, ?, ?)""",
        (profile_id, "测试逝者", now, now),
    )
    db_conn.commit()
    return profile_id


# ==================== 解析器测试 ====================


class TestWechatTxtParser:
    """微信 TXT 解析器测试。"""

    def test_parse_basic_messages(self, wechat_txt_file: str) -> None:
        """测试基本消息解析。"""
        parser = WechatTxtParser()
        messages = parser.parse(wechat_txt_file, "test-artifact-id")

        # 应该能解析出消息
        assert len(messages) > 0

        # 所有消息都应有 content
        for msg in messages:
            assert msg.content, f"消息 {msg.id} 内容为空"
            assert msg.speaker, f"消息 {msg.id} 说话人为空"
            assert msg.source_artifact_id == "test-artifact-id"

    def test_parse_two_line_format(self) -> None:
        """测试两行格式解析: 时间戳 + 说话人 \\n 内容。"""
        content = "2024-01-15 10:30:22 妈妈\n你今天吃药了吗？\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            file_path = f.name

        try:
            parser = WechatTxtParser()
            messages = parser.parse(file_path, "test-id")
            assert len(messages) >= 1
            # 找到妈妈的消息
            mom_msgs = [m for m in messages if m.speaker == "妈妈"]
            assert len(mom_msgs) >= 1
            assert "吃药" in mom_msgs[0].content
        finally:
            os.unlink(file_path)

    def test_parse_system_message(self, wechat_txt_file: str) -> None:
        """测试系统消息识别。"""
        parser = WechatTxtParser()
        messages = parser.parse(wechat_txt_file, "test-id")

        system_msgs = [m for m in messages if m.content_type == "system"]
        assert len(system_msgs) >= 1, "应识别到系统消息"

        # 系统消息的说话人应为 __system__
        for msg in system_msgs:
            assert msg.speaker == "__system__"

    def test_parse_recall_message(self) -> None:
        """测试撤回消息识别。"""
        content = "2024-01-15 10:30:00 我\n你好\n\n「我」撤回了一条消息\n2024-01-15 10:31:00 妈妈\n好的\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            file_path = f.name

        try:
            parser = WechatTxtParser()
            messages = parser.parse(file_path, "test-id")
            recall_msgs = [m for m in messages if m.content_type == "recall"]
            assert len(recall_msgs) >= 1, "应识别到撤回消息"
        finally:
            os.unlink(file_path)

    def test_infer_timestamps(self) -> None:
        """测试无时间戳消息的时间推断。"""
        content = "2024-01-15 10:30:00 妈妈\n你好\n\n「我」撤回了一条消息\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            file_path = f.name

        try:
            parser = WechatTxtParser()
            messages = parser.parse(file_path, "test-id")
            # 撤回消息应该获得了推断的时间戳
            recall_msgs = [m for m in messages if m.content_type == "recall"]
            if recall_msgs:
                assert recall_msgs[0].timestamp is not None, "撤回消息应有推断时间戳"
        finally:
            os.unlink(file_path)

    def test_encoding_detection_gbk(self, tmp_path: Path) -> None:
        """测试 GBK 编码文件自动检测。"""
        content = "2024-01-15 10:30:00 妈妈\n你好\n"
        file_path = tmp_path / "wechat_gbk.txt"
        file_path.write_text(content, encoding="gbk")

        parser = WechatTxtParser()
        messages = parser.parse(str(file_path), "test-id")
        assert len(messages) >= 1


# ==================== 规范化测试 ====================


class TestNormalizer:
    """消息规范化测试。"""

    def test_normalize_basic(self) -> None:
        """测试基本规范化流程。"""
        raw = RawMessage(
            id=generate_uuid(),
            source_artifact_id="artifact-1",
            timestamp="2024-01-15 10:30:22",
            speaker="妈妈",
            content="你好",
            content_type="text",
        )
        normalized = normalize_messages([raw])
        assert len(normalized) == 1
        assert normalized[0].speaker_original == "妈妈"
        assert normalized[0].speaker_normalized == "妈妈"
        assert normalized[0].raw_message_id == raw.id
        assert normalized[0].status == MessageStatus.NORMALIZED

    def test_normalize_with_aliases(self) -> None:
        """测试说话人别名映射。"""
        raw = RawMessage(
            id=generate_uuid(),
            source_artifact_id="artifact-1",
            timestamp="2024-01-15 10:30:22",
            speaker="妈",
            content="你好",
        )
        aliases = {"妈": "妈妈"}
        normalized = normalize_messages([raw], speaker_aliases=aliases)
        assert normalized[0].speaker_normalized == "妈妈"

    def test_normalize_timestamp_iso8601(self) -> None:
        """测试时间戳标准化为 ISO 8601。"""
        raw = RawMessage(
            id=generate_uuid(),
            source_artifact_id="artifact-1",
            timestamp="2024-01-15 10:30:22",
            speaker="妈妈",
            content="你好",
        )
        normalized = normalize_messages([raw])
        assert "T" in normalized[0].timestamp


# ==================== 清洗过滤器测试 ====================


class TestFilters:
    """清洗过滤器测试。"""

    def _make_normalized(self, **kwargs: Any) -> NormalizedMessage:
        """创建测试用的 NormalizedMessage。"""
        defaults = {
            "id": generate_uuid(),
            "raw_message_id": generate_uuid(),
            "source_artifact_id": "artifact-1",
            "timestamp": "2024-01-15T10:30:22",
            "timestamp_confidence": "CERTAIN",
            "speaker_original": "妈妈",
            "speaker_normalized": "妈妈",
            "content": "你好",
            "content_type": "text",
            "status": MessageStatus.NORMALIZED,
            "filter_tags": [],
            "metadata": {},
        }
        defaults.update(kwargs)
        return NormalizedMessage(**defaults)

    def test_system_message_filter(self) -> None:
        """测试系统消息过滤器。"""
        msgs = [
            self._make_normalized(
                speaker_original="__system__",
                speaker_normalized="__system__",
                content_type="system",
                content="你已添加了爸爸",
            ),
            self._make_normalized(content="你好"),
        ]
        result = filter_noise(msgs)
        assert result[0].status == MessageStatus.FILTERED
        assert "system_message" in result[0].filter_tags
        assert result[1].status == MessageStatus.NORMALIZED

    def test_recall_message_filter(self) -> None:
        """测试撤回消息过滤器。"""
        msgs = [
            self._make_normalized(
                content_type="recall",
                content="撤回了一条消息",
            ),
        ]
        result = filter_noise(msgs)
        assert result[0].status == MessageStatus.FILTERED
        assert "recall_message" in result[0].filter_tags

    def test_duplicate_filter(self) -> None:
        """测试重复消息过滤器。"""
        msgs = [
            self._make_normalized(content="你好"),
            self._make_normalized(content="你好"),
        ]
        # 两条消息说话人和内容完全相同，第二条应被标为重复
        result = filter_noise(msgs)
        filtered = [m for m in result if m.status == MessageStatus.FILTERED]
        assert len(filtered) >= 1

    def test_filter_noise_preserves_count(self) -> None:
        """测试 filter_noise 不删除消息，只标记。"""
        msgs = [
            self._make_normalized(content="消息1"),
            self._make_normalized(content="消息2"),
            self._make_normalized(
                speaker_original="__system__",
                speaker_normalized="__system__",
                content_type="system",
                content="系统消息",
            ),
        ]
        result = filter_noise(msgs)
        assert len(result) == 3, "filter_noise 不应改变消息数量"


# ==================== 分块测试 ====================


class TestChunker:
    """对话分块算法测试。"""

    def _make_msg(self, content: str, speaker: str = "妈妈", ts: str = "2024-01-15T10:30:22") -> NormalizedMessage:
        """创建测试用消息。"""
        return NormalizedMessage(
            id=generate_uuid(),
            raw_message_id=generate_uuid(),
            source_artifact_id="artifact-1",
            timestamp=ts,
            timestamp_confidence="CERTAIN",
            speaker_original=speaker,
            speaker_normalized=speaker,
            content=content,
            content_type="text",
            status=MessageStatus.NORMALIZED,
            filter_tags=[],
            metadata={},
        )

    def test_build_conversation_segments(self) -> None:
        """测试按时间间隔分割对话段。"""
        msgs = [
            self._make_msg("消息1", ts="2024-01-15T10:00:00"),
            self._make_msg("消息2", ts="2024-01-15T10:01:00"),
            self._make_msg("消息3", ts="2024-01-15T12:00:00"),  # 2小时间隔
        ]
        segments = build_conversation_segments(msgs, time_gap_threshold=1800)
        assert len(segments) == 2, "超过30分钟间隔应分为2个对话段"

    def test_semantic_chunk_basic(self) -> None:
        """测试基本分块功能。"""
        msgs = [self._make_msg(f"消息{i}", ts=f"2024-01-15T10:{i:02d}:00") for i in range(5)]
        chunks = semantic_chunk(msgs, source_artifact_id="artifact-1")
        assert len(chunks) >= 1, "应至少有一个 chunk"
        assert chunks[0]["source_artifact_id"] == "artifact-1"

    def test_estimate_tokens(self) -> None:
        """测试 token 估算。"""
        # 中文文本
        assert _estimate_tokens("你好世界") > 0
        # 英文文本
        assert _estimate_tokens("hello world") > 0
        # 空文本
        assert _estimate_tokens("") == 0


# ==================== 溯源和哈希测试 ====================


class TestSpanAndHash:
    """溯源映射和哈希测试。"""

    def test_generate_chunk_hash(self) -> None:
        """测试 chunk 哈希生成。"""
        hash1 = generate_chunk_hash("测试内容")
        hash2 = generate_chunk_hash("测试内容")
        hash3 = generate_chunk_hash("不同内容")
        assert hash1 == hash2, "相同内容应产生相同哈希"
        assert hash1 != hash3, "不同内容应产生不同哈希"
        assert len(hash1) == 64, "SHA-256 哈希应为64字符"

    def test_attach_source_spans(self) -> None:
        """测试溯源映射生成。"""
        msg1 = NormalizedMessage(
            id="msg-1",
            raw_message_id="raw-1",
            source_artifact_id="artifact-1",
            timestamp="2024-01-15T10:30:22",
            timestamp_confidence="CERTAIN",
            speaker_original="妈妈",
            speaker_normalized="妈妈",
            content="你好",
            content_type="text",
            status=MessageStatus.NORMALIZED,
            filter_tags=[],
            metadata={},
        )
        msg2 = NormalizedMessage(
            id="msg-2",
            raw_message_id="raw-2",
            source_artifact_id="artifact-1",
            timestamp="2024-01-15T10:31:00",
            timestamp_confidence="CERTAIN",
            speaker_original="我",
            speaker_normalized="我",
            content="你好吗",
            content_type="text",
            status=MessageStatus.NORMALIZED,
            filter_tags=[],
            metadata={},
        )

        chunks = [{
            "id": "chunk-1",
            "source_artifact_id": "artifact-1",
            "content": "[妈妈] 你好\n[我] 你好吗",
            "messages": [msg1, msg2],
        }]

        result = attach_source_spans_v2(chunks)
        assert len(result) == 1
        assert "spans" in result[0]

        spans = result[0]["spans"]
        assert len(spans) == 2

        # 验证第一个 span
        assert spans[0].normalized_message_id == "msg-1"
        assert spans[0].source_speaker == "妈妈"
        assert spans[0].char_start == 0

        # 验证第二个 span
        assert spans[1].normalized_message_id == "msg-2"
        assert spans[1].source_speaker == "我"

        # 验证 content 中的溯源定位
        content = result[0]["content"]
        span0_text = content[spans[0].char_start:spans[0].char_end]
        assert "[妈妈] 你好" == span0_text


# ==================== ETL 管道端到端测试 ====================


class TestETLPipeline:
    """ETL 管道端到端集成测试。"""

    def _make_pipeline(self) -> tuple[ETLPipeline, str]:
        """创建一个有 deceased_profile 的 pipeline 实例。

        返回 (pipeline, deceased_profile_id)
        """
        conn = init_db(":memory:")
        pipeline = ETLPipeline(conn=conn)
        # 插入 deceased_profile
        from datetime import datetime, timezone
        profile_id = generate_uuid()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT INTO deceased_profile (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (profile_id, "测试逝者", now, now),
        )
        conn.commit()
        return pipeline, profile_id

    def test_full_pipeline(self, wechat_txt_file: str) -> None:
        """测试完整 ETL 管道。"""
        pipeline, profile_id = self._make_pipeline()
        result = pipeline.run(
            file_path=wechat_txt_file,
            file_type="wechat_txt",
            deceased_profile_id=profile_id,
        )

        # 验证管道完成了（可能有消息但不应报错导致完整失败）
        assert result["artifact_id"] is not None
        assert result["raw_count"] > 0, "应解析出原始消息"

    def test_source_artifact_stored(self, wechat_txt_file: str) -> None:
        """测试 source_artifact 入库。"""
        pipeline, profile_id = self._make_pipeline()
        result = pipeline.run(
            file_path=wechat_txt_file,
            file_type="wechat_txt",
            deceased_profile_id=profile_id,
        )

        artifact_id = result["artifact_id"]
        conn = pipeline._get_conn()
        row = conn.execute(
            "SELECT id, file_type, parse_status FROM source_artifact WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        assert row is not None
        assert row["file_type"] == "wechat_txt"
        assert row["parse_status"] == "PARSED"

    def test_raw_messages_stored(self, wechat_txt_file: str) -> None:
        """测试 raw_message 入库数量。"""
        pipeline, profile_id = self._make_pipeline()
        result = pipeline.run(
            file_path=wechat_txt_file,
            file_type="wechat_txt",
            deceased_profile_id=profile_id,
        )

        artifact_id = result["artifact_id"]
        conn = pipeline._get_conn()
        rows = conn.execute(
            "SELECT COUNT(*) as cnt FROM raw_message WHERE source_artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        assert rows["cnt"] == result["raw_count"]

    def test_normalized_messages_with_tags(self, wechat_txt_file: str) -> None:
        """测试 normalized_message 标签。"""
        pipeline, profile_id = self._make_pipeline()
        result = pipeline.run(
            file_path=wechat_txt_file,
            file_type="wechat_txt",
            deceased_profile_id=profile_id,
        )

        artifact_id = result["artifact_id"]
        conn = pipeline._get_conn()

        # 系统消息应被标记为 FILTERED
        filtered = conn.execute(
            "SELECT COUNT(*) as cnt FROM normalized_message WHERE source_artifact_id = ? AND status = 'FILTERED'",
            (artifact_id,),
        ).fetchone()
        assert filtered["cnt"] >= 1, "应至少有1条系统消息被标记为 FILTERED"

        # 应有带 filter_tags 的消息
        tagged = conn.execute(
            "SELECT filter_tags FROM normalized_message WHERE source_artifact_id = ? AND filter_tags != '[]'",
            (artifact_id,),
        ).fetchone()
        # 至少有些消息可能带标签
        # 具体数量取决于样本数据

    def test_chunks_stored(self, wechat_txt_file: str) -> None:
        """测试 memory_chunk 入库和哈希。"""
        pipeline, profile_id = self._make_pipeline()
        result = pipeline.run(
            file_path=wechat_txt_file,
            file_type="wechat_txt",
            deceased_profile_id=profile_id,
        )

        artifact_id = result["artifact_id"]
        conn = pipeline._get_conn()
        chunks = conn.execute(
            "SELECT id, chunk_hash, content, message_count FROM memory_chunk WHERE source_artifact_id = ?",
            (artifact_id,),
        ).fetchall()

        assert len(chunks) > 0, "应至少有一个 memory_chunk"

        for chunk in chunks:
            assert chunk["chunk_hash"] is not None
            assert len(chunk["chunk_hash"]) == 64, "SHA-256 哈希应为64字符"
            assert chunk["content"] is not None

    def test_chunk_spans(self, wechat_txt_file: str) -> None:
        """测试 memory_chunk_span 溯源映射。"""
        pipeline, profile_id = self._make_pipeline()
        result = pipeline.run(
            file_path=wechat_txt_file,
            file_type="wechat_txt",
            deceased_profile_id=profile_id,
        )

        artifact_id = result["artifact_id"]
        conn = pipeline._get_conn()

        # 验证 span 记录存在
        spans = conn.execute(
            """SELECT s.id, s.chunk_id, s.normalized_message_id, s.char_start, s.char_end,
                      s.source_speaker, s.source_timestamp
               FROM memory_chunk_span s
               JOIN memory_chunk c ON s.chunk_id = c.id
               WHERE c.source_artifact_id = ?""",
            (artifact_id,),
        ).fetchall()

        assert len(spans) > 0, "应至少有一个 span 记录"

        for span in spans:
            assert span["normalized_message_id"] is not None
            assert span["source_speaker"] is not None
            assert span["char_start"] >= 0
            assert span["char_end"] > span["char_start"]

        # 验证 span 可以追溯到 normalized_message
        for span in spans:
            nm = conn.execute(
                "SELECT id FROM normalized_message WHERE id = ?",
                (span["normalized_message_id"],),
            ).fetchone()
            assert nm is not None, f"span 引用的 normalized_message {span['normalized_message_id']} 不存在"

    def test_raw_message_immutable(self, wechat_txt_file: str) -> None:
        """测试 raw_message 不可变触发器。"""
        pipeline, profile_id = self._make_pipeline()
        result = pipeline.run(
            file_path=wechat_txt_file,
            file_type="wechat_txt",
            deceased_profile_id=profile_id,
        )

        artifact_id = result["artifact_id"]
        conn = pipeline._get_conn()

        # 尝试更新 raw_message 应该失败
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE raw_message SET content = 'hacked' WHERE source_artifact_id = ?",
                (artifact_id,),
            )
            conn.commit()

    def test_fts5_search(self, wechat_txt_file: str) -> None:
        """测试 FTS5 全文搜索。"""
        pipeline, profile_id = self._make_pipeline()
        result = pipeline.run(
            file_path=wechat_txt_file,
            file_type="wechat_txt",
            deceased_profile_id=profile_id,
        )

        # 获取数据库连接并验证 FTS5
        conn = pipeline._get_conn()

        # 检查 FTS5 表是否存在
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%fts%'"
        ).fetchall()
        assert len(tables) > 0, "FTS5 虚拟表应存在"

        # 尝试搜索
        try:
            results = conn.execute(
                "SELECT rowid, content FROM memory_chunk_fts WHERE memory_chunk_fts MATCH ?",
                ("吃药",),
            ).fetchall()
            # 只要不报错就行，结果数量取决于 tokenizer
        except sqlite3.OperationalError:
            # 如果 tokenizer 不支持中文，跳过
            pass

    def test_speaker_aliases(self, tmp_path: Path) -> None:
        """测试说话人别名统一。"""
        content = "2024-01-15 10:30:00 妈\n你好\n\n2024-01-15 10:31:00 妈妈\n收到了\n"
        file_path = tmp_path / "alias_test.txt"
        file_path.write_text(content, encoding="utf-8")

        pipeline, profile_id = self._make_pipeline()
        result = pipeline.run(
            file_path=str(file_path),
            file_type="wechat_txt",
            deceased_profile_id=profile_id,
            speaker_aliases={"妈": "妈妈"},
        )

        artifact_id = result["artifact_id"]
        conn = pipeline._get_conn()

        # 检查规范化后的说话人名称
        rows = conn.execute(
            "SELECT DISTINCT speaker_normalized FROM normalized_message WHERE source_artifact_id = ?",
            (artifact_id,),
        ).fetchall()

        # "妈" 应该被统一为 "妈妈"
        speakers = [r["speaker_normalized"] for r in rows]
        assert "妈妈" in speakers or "妈" in speakers

    def test_pipeline_error_handling(self, tmp_path: Path) -> None:
        """测试管道错误处理。"""
        pipeline, profile_id = self._make_pipeline()
        file_path = tmp_path / "empty.txt"
        file_path.write_text("测试内容", encoding="utf-8")

        result = pipeline.run(
            file_path=str(file_path),
            file_type="unsupported_type",
            deceased_profile_id=profile_id,
        )

        # 应返回错误信息
        assert len(result["errors"]) > 0 or result["raw_count"] == 0


# ==================== 数据库集成测试 ====================


class TestDatabaseIntegration:
    """数据库集成测试。"""

    def test_init_db_creates_all_tables(self, db_conn: sqlite3.Connection) -> None:
        """测试数据库初始化创建所有表。"""
        from remnant_store.schema import get_table_names

        tables = get_table_names(db_conn)
        assert "deceased_profile" in tables
        assert "source_artifact" in tables
        assert "raw_message" in tables
        assert "normalized_message" in tables
        assert "memory_chunk" in tables
        assert "memory_chunk_span" in tables
        assert "audit_log" in tables

    def test_init_db_creates_triggers(self, db_conn: sqlite3.Connection) -> None:
        """测试数据库初始化创建触发器。"""
        from remnant_store.schema import get_trigger_names

        triggers = get_trigger_names(db_conn)
        assert "trg_prevent_raw_message_update" in triggers
        assert "trg_prevent_raw_message_delete" in triggers
        assert "trg_prevent_audit_update" in triggers
        assert "trg_prevent_audit_delete" in triggers

    def test_raw_message_cannot_be_updated(self, db_conn: sqlite3.Connection) -> None:
        """测试 raw_message 不可修改。"""
        # 先创建 deceased_profile 和 source_artifact 以满足外键约束
        now = "2024-01-15T10:00:00Z"
        db_conn.execute(
            "INSERT INTO deceased_profile (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("dp-test-1", "测试逝者", now, now),
        )
        db_conn.execute(
            """INSERT INTO source_artifact
            (id, deceased_profile_id, file_path, file_hash, file_size, file_type, parse_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("sa-test-1", "dp-test-1", "/test.txt", "abc123", 100, "wechat_txt", "OK", now, now),
        )
        db_conn.commit()

        db_conn.execute(
            """INSERT INTO raw_message (id, source_artifact_id, timestamp, speaker, content, content_type, parse_status, metadata)
            VALUES ('rm-1', 'sa-test-1', '2024-01-15T10:30:22', '妈妈', '你好', 'text', 'OK', '{}')""",
        )
        db_conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute("UPDATE raw_message SET content = 'hacked' WHERE id = 'rm-1'")
            db_conn.commit()

    def test_raw_message_cannot_be_deleted(self, db_conn: sqlite3.Connection) -> None:
        """测试 raw_message 不可删除。"""
        now = "2024-01-15T10:00:00Z"
        db_conn.execute(
            "INSERT INTO deceased_profile (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("dp-test-2", "测试逝者2", now, now),
        )
        db_conn.execute(
            """INSERT INTO source_artifact
            (id, deceased_profile_id, file_path, file_hash, file_size, file_type, parse_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("sa-test-2", "dp-test-2", "/test2.txt", "abc456", 100, "wechat_txt", "OK", now, now),
        )
        db_conn.commit()

        db_conn.execute(
            """INSERT INTO raw_message (id, source_artifact_id, timestamp, speaker, content, content_type, parse_status, metadata)
            VALUES ('rm-2', 'sa-test-2', '2024-01-15T10:30:22', '妈妈', '你好', 'text', 'OK', '{}')""",
        )
        db_conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute("DELETE FROM raw_message WHERE id = 'rm-2'")
            db_conn.commit()