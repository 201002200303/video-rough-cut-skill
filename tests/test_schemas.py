"""Pydantic 数据协议校验与 core/db 功能测试。"""

import json
import os
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from schemas.transcript import TranscriptWord, TranscriptSegment, Transcript
from schemas.segment import SemanticSegment
from schemas.edit_decision import EditDecision, EditDecisionFile
from schemas.skill_input import SkillInput
from schemas.skill_output import SkillOutput
from schemas.subtitle import SubtitleEvent, SubtitleData
from schemas.job import (
    JobStatus,
    JobRecord,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
)
from core.exceptions import SkillError, ExternalCommandError, ProviderError, ValidationError, ConfigError
from core.config import load_config, reload_config
from core.paths import ensure_output_dir, job_output_paths
from core.logging import setup_logger
from api.db import init_db, create_job, get_job, get_next_pending_job, mark_job_running, update_job_status, mark_job_completed, mark_job_failed


# ─── 转写 ───

class TestTranscriptWord:
    def test_valid(self):
        w = TranscriptWord(word="你好", start=0.0, end=1.5)
        assert w.word == "你好"
        assert w.end > w.start
        assert w.timestamp_source == "estimated"

    def test_provider_timestamp_source(self):
        w = TranscriptWord(word="你好", start=0.0, end=1.5, timestamp_source="provider")
        assert w.timestamp_source == "provider"

    def test_invalid_timestamp_source(self):
        with pytest.raises(PydanticValidationError):
            TranscriptWord(word="你好", start=0.0, end=1.5, timestamp_source="mock")

    def test_negative_start(self):
        with pytest.raises(PydanticValidationError):
            TranscriptWord(word="x", start=-0.1, end=1.0)

    def test_end_not_greater_than_start(self):
        with pytest.raises(PydanticValidationError):
            TranscriptWord(word="x", start=1.0, end=1.0)

    def test_end_less_than_start(self):
        with pytest.raises(PydanticValidationError):
            TranscriptWord(word="x", start=2.0, end=1.0)


class TestTranscriptSegment:
    def test_valid_with_words(self):
        w = TranscriptWord(word="你", start=0.0, end=0.5)
        s = TranscriptSegment(id="s0", start=0.0, end=5.0, text="你好", words=[w])
        assert s.id == "s0"
        assert len(s.words) == 1

    def test_valid_without_words(self):
        s = TranscriptSegment(id="s1", start=5.0, end=10.0, text="世界")
        assert s.words == []

    def test_negative_start(self):
        with pytest.raises(PydanticValidationError):
            TranscriptSegment(id="s", start=-1.0, end=5.0, text="x")

    def test_end_equals_start(self):
        with pytest.raises(PydanticValidationError):
            TranscriptSegment(id="s", start=3.0, end=3.0, text="x")


class TestTranscript:
    def test_valid(self):
        s = TranscriptSegment(id="s0", start=0.0, end=5.0, text="你好世界")
        t = Transcript(language="zh", segments=[s])
        assert t.language == "zh"
        assert len(t.segments) == 1

    def test_json_roundtrip(self):
        s = TranscriptSegment(id="s0", start=0.0, end=5.0, text="你好世界")
        t = Transcript(language="zh", segments=[s])
        json_str = t.model_dump_json()
        restored = Transcript.model_validate_json(json_str)
        assert restored.segments[0].text == "你好世界"


# ─── 语义段 ───

class TestSemanticSegment:
    def test_valid(self):
        seg = SemanticSegment(
            segment_id="seg0", start=0.0, end=10.0, text="内容",
            source_segment_ids=["s0", "s1"],
        )
        assert seg.source_segment_ids == ["s0", "s1"]

    def test_negative_start(self):
        with pytest.raises(PydanticValidationError):
            SemanticSegment(segment_id="x", start=-1.0, end=5.0, text="x")

    def test_end_before_start(self):
        with pytest.raises(PydanticValidationError):
            SemanticSegment(segment_id="x", start=5.0, end=3.0, text="x")


# ─── 编辑决策 ───

class TestEditDecision:
    def test_delete(self):
        d = EditDecision(type="delete", start=10.0, end=20.0, reason="重复表达", source="llm", confidence=0.9)
        assert d.type == "delete"
        assert d.target_duration is None

    def test_compress_pause(self):
        d = EditDecision(type="compress_pause", start=5.0, end=10.0, reason="长停顿", source="rule", target_duration=1.0)
        assert d.type == "compress_pause"
        assert d.target_duration == 1.0

    def test_invalid_type(self):
        with pytest.raises(PydanticValidationError):
            EditDecision(type="keep", start=0.0, end=5.0, reason="x", source="rule")

    def test_negative_start(self):
        with pytest.raises(PydanticValidationError):
            EditDecision(type="delete", start=-1.0, end=5.0, reason="x", source="rule")

    def test_end_before_start(self):
        with pytest.raises(PydanticValidationError):
            EditDecision(type="delete", start=10.0, end=5.0, reason="x", source="rule")


class TestEditDecisionFile:
    def test_valid(self):
        d = EditDecision(type="delete", start=0.0, end=5.0, reason="x", source="rule")
        f = EditDecisionFile(edits=[d], review_needed=[{"segment_id": "s2", "reason": "不确定"}])
        assert len(f.edits) == 1
        assert len(f.review_needed) == 1

    def test_json_roundtrip(self):
        d = EditDecision(type="delete", start=0.0, end=5.0, reason="x", source="rule")
        f = EditDecisionFile(edits=[d])
        json_str = f.model_dump_json()
        restored = EditDecisionFile.model_validate_json(json_str)
        assert restored.edits[0].type == "delete"


# ─── 技能输入 ───

class TestSkillInput:
    def test_valid(self):
        inp = SkillInput(input_video_path="/path/to/video.mp4", output_dir="/path/to/output")
        assert inp.mode == "standard"

    def test_all_modes(self):
        for mode in ("standard", "conservative", "aggressive"):
            inp = SkillInput(input_video_path="x", output_dir="y", mode=mode)
            assert inp.mode == mode

    def test_invalid_mode(self):
        with pytest.raises(PydanticValidationError):
            SkillInput(input_video_path="x", output_dir="y", mode="fast")


# ─── 技能输出 ───

class TestSkillOutput:
    def test_valid(self):
        out = SkillOutput(
            edited_video_path="/out/edited.mp4",
            transcript_path="/out/transcript.json",
            edit_decisions_path="/out/edit_decisions.json",
            subtitles_path="/out/subtitles.ass",
            report_path="/out/report.md",
        )
        assert out.edited_video_path == "/out/edited.mp4"


# ─── 字幕 ───

class TestSubtitleEvent:
    def test_valid(self):
        e = SubtitleEvent(id="ev0", start=0.0, end=5.0, text="字幕")
        assert e.style == "Default"

    def test_negative_start(self):
        with pytest.raises(PydanticValidationError):
            SubtitleEvent(id="x", start=-1.0, end=5.0, text="x")

    def test_end_before_start(self):
        with pytest.raises(PydanticValidationError):
            SubtitleEvent(id="x", start=5.0, end=3.0, text="x")


class TestSubtitleData:
    def test_valid(self):
        events = [
            SubtitleEvent(id="ev0", start=0.0, end=5.0, text="第一句"),
            SubtitleEvent(id="ev1", start=5.0, end=10.0, text="第二句"),
        ]
        data = SubtitleData(events=events, total_duration=10.0)
        assert len(data.events) == 2


# ─── 任务状态 / 任务记录 ───

class TestJobStatus:
    def test_valid_statuses(self):
        for s in (JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_COMPLETED, JOB_STATUS_FAILED):
            js = JobStatus(id="test", status=s)
            assert js.status == s

    def test_invalid_status(self):
        with pytest.raises(PydanticValidationError):
            JobStatus(id="test", status="unknown")

    def test_defaults(self):
        js = JobStatus(id="test", status=JOB_STATUS_PENDING)
        assert js.progress == 0.0
        assert js.error_message is None


class TestJobRecord:
    def test_valid(self):
        now = "2026-04-28T08:00:00+00:00"
        rec = JobRecord(
            id="uuid-1",
            input_video_path="/video.mp4",
            output_dir="/output",
            created_at=now,
            updated_at=now,
        )
        assert rec.status == JOB_STATUS_PENDING
        assert rec.started_at is None

    def test_json_roundtrip(self):
        now = "2026-04-28T08:00:00+00:00"
        rec = JobRecord(
            id="uuid-1",
            input_video_path="/video.mp4",
            output_dir="/output",
            created_at=now,
            updated_at=now,
        )
        json_str = rec.model_dump_json()
        restored = JobRecord.model_validate_json(json_str)
        assert restored.id == "uuid-1"


# ─── 异常 ───

class TestExceptions:
    def test_hierarchy(self):
        assert issubclass(ExternalCommandError, SkillError)
        assert issubclass(ProviderError, SkillError)
        assert issubclass(ValidationError, SkillError)
        assert issubclass(ConfigError, SkillError)

    def test_raise_and_catch(self):
        with pytest.raises(SkillError):
            raise ProviderError("ASR failed")


# ─── 配置 ───

class TestConfig:
    def test_load_default(self):
        reload_config()
        cfg = load_config()
        assert "pause_cut" in cfg
        assert "subtitle" in cfg
        assert "pause_threshold" in cfg["pause_cut"]

    def test_reload_returns_new(self):
        cfg1 = load_config()
        cfg2 = reload_config()
        assert cfg2 is not cfg1


# ─── 路径 ───

class TestPaths:
    def test_ensure_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = str(Path(tmp) / "job_output")
            result = ensure_output_dir(out_dir)
            assert result.exists()

    def test_empty_output_dir_raises(self):
        with pytest.raises(ValidationError):
            ensure_output_dir("")

    def test_job_output_paths_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = str(Path(tmp) / "job_output")
            paths = job_output_paths(out_dir)
            assert "transcript" in paths
            assert "edit_decisions" in paths
            assert "subtitles" in paths
            assert "edited_video" in paths
            assert "report" in paths
            assert "vad_segments" in paths
            assert "transcript_before_edit" in paths
            assert "transcript_after_edit" in paths
            assert "semantic_segments" in paths
            assert "remapped_transcript" in paths
            assert "audio" in paths


# ─── 数据库 ───

class TestDB:
    def test_init_and_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            init_db(db_path)
            job_id = create_job(db_path, "/video.mp4", "/output", "standard")
            assert isinstance(job_id, str)
            assert len(job_id) > 0

    def test_get_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            init_db(db_path)
            job_id = create_job(db_path, "/video.mp4", "/output")
            job = get_job(db_path, job_id)
            assert job is not None
            assert job.id == job_id
            assert job.status == JOB_STATUS_PENDING
            assert job.input_video_path == "/video.mp4"

    def test_get_nonexistent_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            init_db(db_path)
            result = get_job(db_path, "nonexistent-id")
            assert result is None

    def test_get_next_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            init_db(db_path)
            j1 = create_job(db_path, "/v1.mp4", "/out1")
            j2 = create_job(db_path, "/v2.mp4", "/out2")
            next_job = get_next_pending_job(db_path)
            assert next_job is not None
            assert next_job.id == j1

    def test_mark_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            init_db(db_path)
            job_id = create_job(db_path, "/video.mp4", "/output")
            mark_job_running(db_path, job_id)
            job = get_job(db_path, job_id)
            assert job.status == JOB_STATUS_RUNNING
            assert job.started_at is not None

    def test_update_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            init_db(db_path)
            job_id = create_job(db_path, "/video.mp4", "/output")
            mark_job_running(db_path, job_id)
            update_job_status(db_path, job_id, 0.5, "transcribe")
            job = get_job(db_path, job_id)
            assert job.progress == 0.5
            assert job.current_step == "transcribe"

    def test_mark_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            init_db(db_path)
            job_id = create_job(db_path, "/video.mp4", "/output")
            mark_job_running(db_path, job_id)
            mark_job_completed(db_path, job_id, edited_video_path="/out/edited.mp4")
            job = get_job(db_path, job_id)
            assert job.status == JOB_STATUS_COMPLETED
            assert job.progress == 1.0
            assert job.completed_at is not None
            assert job.edited_video_path == "/out/edited.mp4"

    def test_mark_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            init_db(db_path)
            job_id = create_job(db_path, "/video.mp4", "/output")
            mark_job_running(db_path, job_id)
            mark_job_failed(db_path, job_id, "ASR transcription failed")
            job = get_job(db_path, job_id)
            assert job.status == JOB_STATUS_FAILED
            assert job.error_message == "ASR transcription failed"

    def test_no_pending_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            init_db(db_path)
            result = get_next_pending_job(db_path)
            assert result is None


# ── API 模型 ──

class TestCreateJobRequest:
    def test_valid(self):
        from api.models import CreateJobRequest
        req = CreateJobRequest(input_video_path="/video.mp4", output_dir="/out")
        assert req.mode == "standard"

    def test_invalid_mode(self):
        from api.models import CreateJobRequest
        with pytest.raises(PydanticValidationError):
            CreateJobRequest(input_video_path="x", output_dir="y", mode="fast")


class TestResponseModels:
    def test_create_job_response(self):
        from api.models import CreateJobResponse
        r = CreateJobResponse(job_id="id1", status="pending", output_dir="/out")
        assert r.job_id == "id1"

    def test_job_outputs_response(self):
        from api.models import JobOutputsResponse
        r = JobOutputsResponse(status="completed", edited_video_path="/out/edited.mp4")
        assert r.status == "completed"
        assert r.edited_video_path == "/out/edited.mp4"


# ── API 端点 ──

class TestAPIEndpoints:
    def _make_client_and_db(self):
        """创建带有独立临时数据库的 TestClient。"""
        tmp = tempfile.mkdtemp()
        db_path = Path(tmp) / "api_test.db"
        os.environ["VIDEO_SKILL_DB_PATH"] = str(db_path)
        from fastapi.testclient import TestClient
        from api.app import app
        from api.db import init_db
        init_db(db_path)
        client = TestClient(app)
        return client, tmp, db_path

    def _cleanup(self, tmp):
        os.environ.pop("VIDEO_SKILL_DB_PATH", None)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    def test_health(self):
        client, tmp, _ = self._make_client_and_db()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        self._cleanup(tmp)

    def test_create_job_with_valid_video(self):
        client, tmp, _ = self._make_client_and_db()
        video_dir = tempfile.mkdtemp()
        video = Path(video_dir) / "test_video.mp4"
        video.write_bytes(b"\x00" * 1024)
        out_dir = Path(video_dir) / "output"
        resp = client.post("/jobs", json={
            "input_video_path": str(video),
            "output_dir": str(out_dir),
            "mode": "standard",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        self._cleanup(tmp)
        import shutil
        shutil.rmtree(video_dir, ignore_errors=True)

    def test_create_job_missing_video(self):
        client, tmp, _ = self._make_client_and_db()
        resp = client.post("/jobs", json={
            "input_video_path": "/nonexistent/video.mp4",
            "output_dir": "/tmp/out",
        })
        assert resp.status_code == 400
        self._cleanup(tmp)

    def test_create_job_bad_extension(self):
        client, tmp, _ = self._make_client_and_db()
        video_dir = tempfile.mkdtemp()
        video = Path(video_dir) / "test_video.avi"
        video.write_bytes(b"\x00" * 1024)
        resp = client.post("/jobs", json={
            "input_video_path": str(video),
            "output_dir": str(Path(video_dir) / "output"),
        })
        assert resp.status_code == 400
        self._cleanup(tmp)
        import shutil
        shutil.rmtree(video_dir, ignore_errors=True)

    def test_get_job_status(self):
        client, tmp, _ = self._make_client_and_db()
        video_dir = tempfile.mkdtemp()
        video = Path(video_dir) / "test_video.mp4"
        video.write_bytes(b"\x00" * 1024)
        out_dir = Path(video_dir) / "output"
        create_resp = client.post("/jobs", json={
            "input_video_path": str(video),
            "output_dir": str(out_dir),
        })
        job_id = create_resp.json()["job_id"]
        status_resp = client.get(f"/jobs/{job_id}")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "pending"
        self._cleanup(tmp)
        import shutil
        shutil.rmtree(video_dir, ignore_errors=True)

    def test_get_job_not_found(self):
        client, tmp, _ = self._make_client_and_db()
        resp = client.get("/jobs/nonexistent-id")
        assert resp.status_code == 404
        self._cleanup(tmp)

    def test_get_job_outputs_not_found(self):
        client, tmp, _ = self._make_client_and_db()
        resp = client.get("/jobs/nonexistent-id/outputs")
        assert resp.status_code == 404
        self._cleanup(tmp)


# ── 流水线 ──

class TestRunPipeline:
    def test_pipeline_returns_paths_with_stubbed_steps(self, monkeypatch):
        from scripts.run import run_pipeline
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "pipeline_output"

            def fake_extract_audio(input_video_path, output_audio_path):
                output_audio_path.parent.mkdir(parents=True, exist_ok=True)
                output_audio_path.write_bytes(b"fake")
                return output_audio_path

            fake_transcript = Transcript(
                language="zh",
                segments=[
                    TranscriptSegment(id="s1", start=0.0, end=1.0, text="第一句。", words=[]),
                    TranscriptSegment(id="s2", start=1.8, end=2.6, text="第二句。", words=[]),
                ],
            )
            monkeypatch.setattr("scripts.run.extract_audio", fake_extract_audio)
            monkeypatch.setattr("scripts.run.detect_vad", lambda *args, **kwargs: {"speech_segments": [], "silence_segments": []})
            monkeypatch.setattr("scripts.run.transcribe_audio", lambda *args, **kwargs: fake_transcript)
            monkeypatch.setattr("scripts.run.detect_repetition", lambda *args, **kwargs: ([], []))
            monkeypatch.setattr("scripts.run.detect_content_cleanup", lambda *args, **kwargs: ([], []))
            monkeypatch.setattr("scripts.run.resolve_edit_boundaries", lambda edits, transcript, vad_data, review_needed: (edits, review_needed))
            monkeypatch.setattr("scripts.run.generate_transcript_debug_files", lambda *args, **kwargs: None)
            monkeypatch.setattr("scripts.run.render_video", lambda **kwargs: kwargs["output_video_path"])
            monkeypatch.setattr("scripts.run.generate_report", lambda **kwargs: kwargs["output_path"])

            outputs = run_pipeline(input_video_path="/fake/video.mp4", output_dir=str(out_dir))
            payload = outputs.model_dump() if hasattr(outputs, "model_dump") else outputs
            assert "edited_video_path" in payload
            assert "transcript_path" in payload
            assert "edit_decisions_path" in payload
            assert "subtitles_path" in payload
            assert "report_path" in payload