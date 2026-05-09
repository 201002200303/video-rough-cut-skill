"""scripts.extract_audio 测试（mock subprocess）。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.utils import ExternalCommandError
from scripts.extract_audio import check_ffmpeg_available, extract_audio, probe_video


def _ok_process(stdout: str = "", stderr: str = "", returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


class TestCheckFFmpegAvailable:
    def test_success(self, monkeypatch):
        calls = []

        def fake_run(cmd, capture_output, text):
            calls.append(cmd)
            return _ok_process(stdout="ok")

        monkeypatch.setattr("scripts.extract_audio.subprocess.run", fake_run)
        check_ffmpeg_available()
        assert Path(calls[0][0]).stem == "ffmpeg"
        assert calls[0][1] == "-version"
        assert Path(calls[1][0]).stem == "ffprobe"
        assert calls[1][1] == "-version"

    def test_ffmpeg_missing(self, monkeypatch):
        def fake_run(cmd, capture_output, text):
            return _ok_process(stderr="not found", returncode=1)

        monkeypatch.setattr("scripts.extract_audio.subprocess.run", fake_run)
        with pytest.raises(ExternalCommandError):
            check_ffmpeg_available()


class TestProbeVideo:
    def test_probe_success(self, monkeypatch, tmp_path: Path):
        input_video = tmp_path / "in.mp4"
        input_video.write_bytes(b"dummy")
        payload = '{"format":{"duration":"12.3"},"streams":[{"codec_type":"video"},{"codec_type":"audio"}]}'

        def fake_run(cmd, capture_output, text):
            return _ok_process(stdout=payload)

        monkeypatch.setattr("scripts.extract_audio.subprocess.run", fake_run)
        data = probe_video(input_video)
        assert data["format"]["duration"] == "12.3"
        assert len(data["streams"]) == 2

    def test_probe_failure(self, monkeypatch, tmp_path: Path):
        input_video = tmp_path / "in.mp4"
        input_video.write_bytes(b"dummy")

        def fake_run(cmd, capture_output, text):
            return _ok_process(stderr="probe error", returncode=2)

        monkeypatch.setattr("scripts.extract_audio.subprocess.run", fake_run)
        with pytest.raises(ExternalCommandError) as e:
            probe_video(input_video)
        assert "probe error" in str(e.value)

    def test_probe_invalid_json(self, monkeypatch, tmp_path: Path):
        input_video = tmp_path / "in.mp4"
        input_video.write_bytes(b"dummy")

        def fake_run(cmd, capture_output, text):
            return _ok_process(stdout="{invalid-json")

        monkeypatch.setattr("scripts.extract_audio.subprocess.run", fake_run)
        with pytest.raises(ExternalCommandError):
            probe_video(input_video)


class TestExtractAudio:
    def test_extract_success(self, monkeypatch, tmp_path: Path):
        input_video = tmp_path / "in.mp4"
        input_video.write_bytes(b"dummy")
        output_audio = tmp_path / "audio.wav"

        def fake_run(cmd, capture_output, text):
            output_audio.write_bytes(b"wav")
            return _ok_process()

        monkeypatch.setattr("scripts.extract_audio.subprocess.run", fake_run)
        out = extract_audio(input_video, output_audio)
        assert out == output_audio
        assert output_audio.exists()

    def test_extract_failure(self, monkeypatch, tmp_path: Path):
        input_video = tmp_path / "in.mp4"
        input_video.write_bytes(b"dummy")
        output_audio = tmp_path / "audio.wav"

        def fake_run(cmd, capture_output, text):
            return _ok_process(stderr="ffmpeg failed", returncode=1)

        monkeypatch.setattr("scripts.extract_audio.subprocess.run", fake_run)
        with pytest.raises(ExternalCommandError) as e:
            extract_audio(input_video, output_audio)
        assert "ffmpeg failed" in str(e.value)

    def test_extract_missing_output(self, monkeypatch, tmp_path: Path):
        input_video = tmp_path / "in.mp4"
        input_video.write_bytes(b"dummy")
        output_audio = tmp_path / "audio.wav"

        def fake_run(cmd, capture_output, text):
            return _ok_process()

        monkeypatch.setattr("scripts.extract_audio.subprocess.run", fake_run)
        with pytest.raises(ExternalCommandError):
            extract_audio(input_video, output_audio)
