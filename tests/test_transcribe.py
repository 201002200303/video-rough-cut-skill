"""ASR 提供者和转写脚本测试。"""

from pathlib import Path

import pytest

from core.exceptions import ProviderError
from providers.aliyun_asr import AliyunASRProvider
from scripts.transcribe import transcribe_audio
from schemas.transcript import Transcript, TranscriptSegment


class TestAliyunASRProvider:
    def test_missing_credentials_raises(self, monkeypatch):
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("ALIYUN_ASR_APP_KEY", raising=False)
        monkeypatch.delenv("ALIYUN_ASR_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("ALIYUN_ASR_ACCESS_KEY_SECRET", raising=False)

        provider = AliyunASRProvider()
        with pytest.raises(ProviderError):
            provider.transcribe(Path("audio.wav"), Path("transcript.json"))

    def test_dashscope_asr_path_with_api_key(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-key")
        monkeypatch.setenv("DASHSCOPE_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        monkeypatch.setenv("DASHSCOPE_ASR_MODEL", "qwen3-asr-flash")
        monkeypatch.setenv("DASHSCOPE_ASR_ENABLE_WORD_TIMESTAMPS", "false")
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"fake-audio")

        class FakeResp:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": "这是测试转写文本。"}
                                ]
                            }
                        }
                    ]
                }

        def fake_post(url, headers, json, timeout):
            assert url.endswith("/chat/completions")
            assert json["model"] == "qwen3-asr-flash"
            return FakeResp()

        monkeypatch.setattr("providers.aliyun_asr.requests.post", fake_post)
        provider = AliyunASRProvider()
        t = provider.transcribe(audio, tmp_path / "out.json")
        assert isinstance(t, Transcript)
        assert t.segments[0].text == "这是测试转写文本。"

    def test_filetrans_requires_file_url_when_auto_upload_disabled(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-key")
        monkeypatch.setenv("DASHSCOPE_ASR_ENABLE_WORD_TIMESTAMPS", "true")
        monkeypatch.delenv("DASHSCOPE_ASR_FILETRANS_FILE_URL", raising=False)
        monkeypatch.setenv("DASHSCOPE_ASR_FILETRANS_AUTO_UPLOAD", "false")
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"fake-audio")

        provider = AliyunASRProvider()
        with pytest.raises(ProviderError, match="DASHSCOPE_ASR_FILETRANS_FILE_URL"):
            provider.transcribe(audio, tmp_path / "out.json")

    def test_filetrans_result_uses_provider_word_timestamps(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-key")
        provider = AliyunASRProvider()
        transcript = provider._build_transcript_from_filetrans_result(
            {
                "transcripts": [
                    {
                        "channel_id": 0,
                        "text": "Hello 世界。",
                        "sentences": [
                            {
                                "begin_time": 100,
                                "end_time": 820,
                                "text": "Hello 世界。",
                                "words": [
                                    {"begin_time": 100, "end_time": 300, "text": "Hello", "punctuation": " "},
                                    {"begin_time": 420, "end_time": 820, "text": "世界", "punctuation": "。"},
                                ],
                            }
                        ],
                    }
                ]
            }
        )

        assert transcript.segments[0].start == 0.1
        assert transcript.segments[0].end == 0.82
        assert transcript.segments[0].words[0].word == "Hello "
        assert transcript.segments[0].words[0].timestamp_source == "provider"


class TestTranscribeAudio:
    def test_transcribe_audio_writes_json(self, monkeypatch, tmp_path: Path):
        class FakeProvider:
            def transcribe(self, audio_path: Path, output_path: Path) -> Transcript:
                return Transcript(
                    language="zh",
                    segments=[
                        TranscriptSegment(id="s1", start=0.0, end=1.0, text="真实链路单测使用 provider stub。", words=[])
                    ],
                )

        monkeypatch.setattr("scripts.transcribe._get_provider", lambda provider_name: FakeProvider())

        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"fake-audio")
        transcript_path = tmp_path / "transcript.json"

        transcript = transcribe_audio(audio_path=audio_path, transcript_path=transcript_path)
        assert isinstance(transcript, Transcript)
        assert transcript_path.exists()

        loaded = Transcript.model_validate_json(transcript_path.read_text(encoding="utf-8"))
        assert loaded.language == "zh"
        assert len(loaded.segments) == 1
