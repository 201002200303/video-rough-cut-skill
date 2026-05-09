"""Core model and utility tests."""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from core.utils import (
    ConfigError,
    ExternalCommandError,
    ProviderError,
    SkillError,
    ValidationError,
    ensure_output_dir,
    job_output_paths,
    load_config,
    reload_config,
)
from schemas.models import (
    EditDecision,
    EditDecisionFile,
    SemanticSegment,
    SkillInput,
    SkillOutput,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
)


class TestTranscriptWord:
    def test_valid(self):
        word = TranscriptWord(word="hello", start=0.0, end=1.5)
        assert word.timestamp_source == "estimated"

    def test_provider_timestamp_source(self):
        word = TranscriptWord(word="hello", start=0.0, end=1.5, timestamp_source="provider")
        assert word.timestamp_source == "provider"

    def test_invalid_timestamp_source(self):
        with pytest.raises(PydanticValidationError):
            TranscriptWord(word="x", start=0.0, end=1.5, timestamp_source="mock")

    def test_invalid_times(self):
        with pytest.raises(PydanticValidationError):
            TranscriptWord(word="x", start=-0.1, end=1.0)
        with pytest.raises(PydanticValidationError):
            TranscriptWord(word="x", start=1.0, end=1.0)


class TestTranscriptSegment:
    def test_valid_with_words(self):
        word = TranscriptWord(word="hello", start=0.0, end=0.5)
        segment = TranscriptSegment(id="s0", start=0.0, end=5.0, text="hello", words=[word])
        assert len(segment.words) == 1

    def test_invalid_times(self):
        with pytest.raises(PydanticValidationError):
            TranscriptSegment(id="s", start=-1.0, end=5.0, text="x")
        with pytest.raises(PydanticValidationError):
            TranscriptSegment(id="s", start=3.0, end=3.0, text="x")


class TestTranscript:
    def test_json_roundtrip(self):
        segment = TranscriptSegment(id="s0", start=0.0, end=5.0, text="hello")
        transcript = Transcript(language="zh", segments=[segment])
        restored = Transcript.model_validate_json(transcript.model_dump_json())
        assert restored.segments[0].text == "hello"


class TestSemanticSegment:
    def test_valid(self):
        segment = SemanticSegment(segment_id="seg0", start=0.0, end=10.0, text="content")
        assert segment.segment_id == "seg0"

    def test_invalid_times(self):
        with pytest.raises(PydanticValidationError):
            SemanticSegment(segment_id="x", start=-1.0, end=5.0, text="x")
        with pytest.raises(PydanticValidationError):
            SemanticSegment(segment_id="x", start=5.0, end=3.0, text="x")


class TestEditDecision:
    def test_delete(self):
        decision = EditDecision(type="delete", start=10.0, end=20.0, reason="repeat", source="llm")
        assert decision.type == "delete"

    def test_compress_pause(self):
        decision = EditDecision(
            type="compress_pause",
            start=5.0,
            end=10.0,
            reason="pause",
            source="rule",
            target_duration=1.0,
        )
        assert decision.target_duration == 1.0

    def test_invalid(self):
        with pytest.raises(PydanticValidationError):
            EditDecision(type="keep", start=0.0, end=5.0, reason="x", source="rule")
        with pytest.raises(PydanticValidationError):
            EditDecision(type="delete", start=-1.0, end=5.0, reason="x", source="rule")
        with pytest.raises(PydanticValidationError):
            EditDecision(type="delete", start=10.0, end=5.0, reason="x", source="rule")


class TestEditDecisionFile:
    def test_json_roundtrip(self):
        decision = EditDecision(type="delete", start=0.0, end=5.0, reason="x", source="rule")
        file = EditDecisionFile(edits=[decision], review_needed=[{"reason": "uncertain"}])
        restored = EditDecisionFile.model_validate_json(file.model_dump_json())
        assert restored.edits[0].type == "delete"
        assert len(restored.review_needed) == 1


class TestSkillIO:
    def test_input_modes(self):
        for mode in ("standard", "conservative", "aggressive"):
            assert SkillInput(input_video_path="x", output_dir="y", mode=mode).mode == mode
        with pytest.raises(PydanticValidationError):
            SkillInput(input_video_path="x", output_dir="y", mode="fast")

    def test_output(self):
        output = SkillOutput(
            edited_video_path="/out/edited.mp4",
            transcript_path="/out/transcript.json",
            edit_decisions_path="/out/edit_decisions.json",
            subtitles_path="/out/subtitles.ass",
            report_path="/out/report.md",
        )
        assert output.report_path == "/out/report.md"


class TestExceptions:
    def test_hierarchy(self):
        assert issubclass(ExternalCommandError, SkillError)
        assert issubclass(ProviderError, SkillError)
        assert issubclass(ValidationError, SkillError)
        assert issubclass(ConfigError, SkillError)


class TestConfig:
    def test_load_default(self):
        reload_config()
        cfg = load_config()
        assert cfg["asr"]["provider"] == "funasr"
        assert cfg["asr"]["allow_fallback"] is False
        assert "pause_cut" in cfg
        assert "subtitle" in cfg

    def test_reload_returns_new(self):
        cfg1 = load_config()
        cfg2 = reload_config()
        assert cfg2 is not cfg1


class TestPaths:
    def test_ensure_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = str(Path(tmp) / "job_output")
            assert ensure_output_dir(output_dir).exists()

    def test_empty_output_dir_raises(self):
        with pytest.raises(ValidationError):
            ensure_output_dir("")

    def test_job_output_paths_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = job_output_paths(str(Path(tmp) / "job_output"))
            expected = {
                "audio",
                "vad_segments",
                "transcript",
                "semantic_segments",
                "edit_decisions",
                "transcript_before_edit",
                "transcript_after_edit",
                "remapped_transcript",
                "subtitles",
                "edited_video",
                "report",
            }
            assert expected.issubset(paths)


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
                    TranscriptSegment(id="s1", start=0.0, end=1.0, text="first", words=[]),
                    TranscriptSegment(id="s2", start=1.8, end=2.6, text="second", words=[]),
                ],
            )
            monkeypatch.setattr("scripts.run.extract_audio", fake_extract_audio)
            monkeypatch.setattr(
                "scripts.run.detect_vad",
                lambda *args, **kwargs: {"speech_segments": [], "silence_segments": []},
            )
            monkeypatch.setattr("scripts.run.transcribe_audio", lambda *args, **kwargs: fake_transcript)
            monkeypatch.setattr("scripts.run.split_transcript_segments_on_word_gaps", lambda transcript, *args, **kwargs: transcript)
            monkeypatch.setattr("scripts.run.build_utterance_units", lambda *args, **kwargs: [])
            monkeypatch.setattr("scripts.run.detect_unit_deletions", lambda units, *args, **kwargs: (units, [], []))
            monkeypatch.setattr("scripts.run.detect_local_false_start_repairs", lambda *args, **kwargs: ([], []))
            monkeypatch.setattr("scripts.run.write_utterance_units", lambda *args, **kwargs: None)
            monkeypatch.setattr("scripts.run.detect_content_cleanup", lambda *args, **kwargs: ([], []))
            monkeypatch.setattr(
                "scripts.run.resolve_edit_boundaries",
                lambda edits, transcript, vad_data, review_needed: (edits, review_needed),
            )
            monkeypatch.setattr("scripts.run.generate_transcript_debug_files", lambda *args, **kwargs: None)
            monkeypatch.setattr("scripts.run.correct_subtitle_text", lambda transcript, *args, **kwargs: transcript)
            monkeypatch.setattr("scripts.run.render_video", lambda **kwargs: kwargs["output_video_path"])
            monkeypatch.setattr("scripts.run.generate_report", lambda **kwargs: kwargs["output_path"])

            outputs = run_pipeline(input_video_path="/fake/video.mp4", output_dir=str(out_dir))
            payload = outputs.model_dump()
            assert "edited_video_path" in payload
            assert "transcript_path" in payload
            assert "edit_decisions_path" in payload
            assert "subtitles_path" in payload
            assert "report_path" in payload
