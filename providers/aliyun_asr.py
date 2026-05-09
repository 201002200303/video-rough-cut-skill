"""阿里云 ASR 提供者（DashScope Qwen-ASR，仅真实 API）。"""

import base64
import os
import re
import time
import wave
from pathlib import Path
from typing import Any

import requests

from core.utils import load_config
from core.utils import ProviderError
from core.utils import setup_logger
from providers.asr_base import ASRProvider
from schemas.models import Transcript, TranscriptSegment, TranscriptWord

logger = setup_logger(__name__)


class AliyunASRProvider(ASRProvider):
    """基于阿里云 DashScope（百炼）服务的 ASR 提供者。"""

    def __init__(self) -> None:
        cfg = load_config().get("aliyun", {}).get("asr", {})
        self.dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
        self.base_url = os.getenv(
            "DASHSCOPE_API_BASE_URL",
            cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
        self.model = os.getenv("DASHSCOPE_ASR_MODEL", cfg.get("model", "qwen3-asr-flash"))
        self.enable_word_timestamps = self._env_bool(
            "DASHSCOPE_ASR_ENABLE_WORD_TIMESTAMPS",
            bool(cfg.get("enable_word_timestamps", True)),
        )
        self.filetrans_model = os.getenv(
            "DASHSCOPE_ASR_FILETRANS_MODEL",
            cfg.get("filetrans_model", "qwen3-asr-flash-filetrans"),
        )
        self.filetrans_api_url = os.getenv(
            "DASHSCOPE_ASR_FILETRANS_API_URL",
            cfg.get("filetrans_api_url", "https://dashscope.aliyuncs.com/api/v1"),
        )
        self.filetrans_file_url = os.getenv(
            "DASHSCOPE_ASR_FILETRANS_FILE_URL",
            cfg.get("filetrans_file_url", ""),
        ).strip()
        self.filetrans_auto_upload = self._env_bool(
            "DASHSCOPE_ASR_FILETRANS_AUTO_UPLOAD",
            bool(cfg.get("filetrans_auto_upload", True)),
        )
        self.filetrans_poll_interval = float(cfg.get("filetrans_poll_interval", 5))
        self.filetrans_poll_timeout = float(cfg.get("filetrans_poll_timeout", 900))
        self.audio_format = cfg.get("format", "wav")

        # 旧版环境变量（保留向后兼容）
        self.app_key = os.getenv("ALIYUN_ASR_APP_KEY")
        self.access_key_id = os.getenv("ALIYUN_ASR_ACCESS_KEY_ID")
        self.access_key_secret = os.getenv("ALIYUN_ASR_ACCESS_KEY_SECRET")

    def transcribe(self, audio_path: Path, output_path: Path) -> Transcript:
        """使用阿里云 ASR 进行转写（仅真实 API）。"""
        try:
            if not self._has_credentials():
                raise ProviderError(
                    "ASR credentials missing: provide DASHSCOPE_API_KEY (or legacy ALIYUN_ASR_*)."
                )
            if self.enable_word_timestamps:
                logger.info("Aliyun ASR using Qwen-ASR FileTrans with provider word timestamps")
                return self._filetrans_transcribe(audio_path)
            logger.info("Aliyun ASR using DashScope text-only API path")
            return self._real_transcribe(audio_path)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"ASR transcription failed: {exc}") from exc

    def _has_credentials(self) -> bool:
        # 优先使用 dashscope api key；回退：旧版 aliyun 三元组
        return bool(self.dashscope_api_key or (self.app_key and self.access_key_id and self.access_key_secret))

    # 已移除 mock 转写路径：仅使用真实 API。

    def _filetrans_transcribe(self, audio_path: Path) -> Transcript:
        """调用 Qwen-ASR FileTrans 异步接口，解析 enable_words 返回的真实时间戳。"""
        if not audio_path.exists():
            raise ProviderError(f"Audio file not found: {audio_path}")
        if not self.dashscope_api_key:
            raise ProviderError("DASHSCOPE_API_KEY is required for Qwen-ASR FileTrans")

        file_url = self.filetrans_file_url
        if not file_url:
            if not self.filetrans_auto_upload:
                raise ProviderError(
                    "Qwen-ASR FileTrans requires DASHSCOPE_ASR_FILETRANS_FILE_URL or "
                    "DASHSCOPE_ASR_FILETRANS_AUTO_UPLOAD=true."
                )
            file_url = self._upload_local_audio(audio_path)

        task_id = self._submit_filetrans_task(file_url)
        result_url = self._wait_filetrans_result(task_id)
        result = self._fetch_filetrans_result(result_url)
        return self._build_transcript_from_filetrans_result(result)

    def _upload_local_audio(self, audio_path: Path) -> str:
        try:
            import dashscope
            from dashscope.utils.oss_utils import OssUtils
        except ImportError as exc:
            raise ProviderError("dashscope package is required for Qwen-ASR temporary upload") from exc

        dashscope.api_key = self.dashscope_api_key
        dashscope.base_http_api_url = self.filetrans_api_url
        logger.info("Uploading local audio to DashScope temporary OSS for Qwen-ASR FileTrans: %s", audio_path)
        try:
            file_url, _ = OssUtils.upload(
                model=self.filetrans_model,
                file_path=str(audio_path),
                api_key=self.dashscope_api_key,
            )
        except Exception as exc:
            raise ProviderError(f"Qwen-ASR temporary upload failed: {exc}") from exc
        if not file_url:
            raise ProviderError("Qwen-ASR temporary upload returned empty file_url")
        return file_url

    def _submit_filetrans_task(self, file_url: str) -> str:
        endpoint = f"{self.filetrans_api_url.rstrip('/')}/services/audio/asr/transcription"
        headers = {
            "Authorization": f"Bearer {self.dashscope_api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        payload = {
            "model": self.filetrans_model,
            "input": {"file_url": file_url},
            "parameters": {
                "enable_words": True,
                "enable_itn": False,
            },
        }
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=120)
        if resp.status_code >= 400:
            raise ProviderError(f"Qwen-ASR FileTrans submit failed status={resp.status_code}: {resp.text}")
        data = resp.json()
        task_id = data.get("output", {}).get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ProviderError(f"Qwen-ASR FileTrans submit missing task_id: {data}")
        return task_id

    def _wait_filetrans_result(self, task_id: str) -> str:
        endpoint = f"{self.filetrans_api_url.rstrip('/')}/tasks/{task_id}"
        headers = {
            "Authorization": f"Bearer {self.dashscope_api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        deadline = time.monotonic() + self.filetrans_poll_timeout
        while time.monotonic() < deadline:
            resp = requests.get(endpoint, headers=headers, timeout=120)
            if resp.status_code >= 400:
                raise ProviderError(f"Qwen-ASR FileTrans fetch failed status={resp.status_code}: {resp.text}")
            data = resp.json()
            output = data.get("output", {})
            status = output.get("task_status")
            if status == "SUCCEEDED":
                transcription_url = output.get("result", {}).get("transcription_url")
                if not isinstance(transcription_url, str) or not transcription_url:
                    raise ProviderError(f"Qwen-ASR FileTrans succeeded without transcription_url: {data}")
                return transcription_url
            if status in {"FAILED", "UNKNOWN"}:
                raise ProviderError(f"Qwen-ASR FileTrans task failed: {data}")
            time.sleep(self.filetrans_poll_interval)
        raise ProviderError(f"Qwen-ASR FileTrans task timed out after {int(self.filetrans_poll_timeout)}s: {task_id}")

    def _fetch_filetrans_result(self, transcription_url: str) -> dict[str, Any]:
        resp = requests.get(transcription_url, timeout=120)
        if resp.status_code >= 400:
            raise ProviderError(f"Qwen-ASR FileTrans result fetch failed status={resp.status_code}: {resp.text}")
        data = resp.json()
        if not isinstance(data, dict):
            raise ProviderError("Qwen-ASR FileTrans result is not a JSON object")
        return data

    def _build_transcript_from_filetrans_result(self, data: dict[str, Any]) -> Transcript:
        transcripts = data.get("transcripts")
        if not isinstance(transcripts, list) or not transcripts:
            raise ProviderError("Qwen-ASR FileTrans result missing transcripts")

        first = transcripts[0]
        if not isinstance(first, dict):
            raise ProviderError("Qwen-ASR FileTrans result transcript is invalid")
        raw_sentences = first.get("sentences")
        if not isinstance(raw_sentences, list) or not raw_sentences:
            raise ProviderError("Qwen-ASR FileTrans result missing sentences")

        segments: list[TranscriptSegment] = []
        for index, sentence in enumerate(raw_sentences, start=1):
            if not isinstance(sentence, dict):
                continue
            text = str(sentence.get("text") or "").strip()
            start = self._ms_to_seconds(sentence.get("begin_time"))
            end = self._ms_to_seconds(sentence.get("end_time"))
            words = self._build_provider_words(sentence.get("words"))
            if words:
                start = min(word.start for word in words)
                end = max(word.end for word in words)
                text = text or "".join(word.word for word in words)
            if not text or end <= start:
                continue
            segments.append(
                TranscriptSegment(
                    id=f"seg-{index:03d}",
                    start=round(start, 3),
                    end=round(end, 3),
                    text=text,
                    words=words,
                )
            )
        if not segments:
            raise ProviderError("Qwen-ASR FileTrans result did not contain usable transcript segments")
        return Transcript(language="zh", segments=segments)

    def _build_provider_words(self, raw_words: Any) -> list[TranscriptWord]:
        if not isinstance(raw_words, list):
            return []
        words: list[TranscriptWord] = []
        for item in raw_words:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            punctuation = str(item.get("punctuation") or "")
            start = self._ms_to_seconds(item.get("begin_time"))
            end = self._ms_to_seconds(item.get("end_time"))
            if not text or end <= start:
                continue
            words.append(
                TranscriptWord(
                    word=f"{text}{punctuation}",
                    start=round(start, 3),
                    end=round(end, 3),
                    timestamp_source="provider",
                )
            )
        return words

    def _real_transcribe(self, audio_path: Path) -> Transcript:
        """调用 DashScope OpenAI 兼容 chat/completions 接口进行 Qwen-ASR 转写。"""
        if not audio_path.exists():
            raise ProviderError(f"Audio file not found: {audio_path}")
        if not self.dashscope_api_key:
            raise ProviderError("DASHSCOPE_API_KEY is required for real ASR call")

        audio_b64 = base64.b64encode(audio_path.read_bytes()).decode("utf-8")
        audio_data = f"data:audio/{self.audio_format};base64,{audio_b64}"
        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.dashscope_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_data,
                                "format": self.audio_format,
                            },
                        }
                    ],
                }
            ],
            "stream": False,
        }
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=120)
        text = ""
        if resp.status_code < 400:
            data = resp.json()
            text = self._extract_text_from_response(data)
        else:
            # 回退：DashScope 原生 ASR endpoint
            text = self._call_dashscope_native_asr(audio_b64)
        if not text.strip():
            raise ProviderError("DashScope ASR returned empty transcript text")
        return self._build_transcript_from_text(text.strip(), audio_path)

    def _call_dashscope_native_asr(self, audio_b64: str) -> str:
        native_base = self.base_url.replace("/compatible-mode/v1", "/api/v1")
        endpoint = f"{native_base.rstrip('/')}/services/aigc/multimodal-generation/generation"
        headers = {
            "Authorization": f"Bearer {self.dashscope_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "audio": f"data:audio/wav;base64,{audio_b64}",
                            }
                        ],
                    }
                ]
            },
            "parameters": {"result_format": "message"},
        }
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=120)
        if resp.status_code >= 400:
            raise ProviderError(
                f"DashScope native ASR API error status={resp.status_code}: {resp.text}"
            )
        data = resp.json()
        try:
            content = data["output"]["choices"][0]["message"]["content"]
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        texts.append(item["text"])
                return "".join(texts)
        except Exception:
            pass
        return ""

    def _extract_text_from_response(self, data: dict) -> str:
        """稳健提取 ASR 文本，兼容多种响应格式。"""
        try:
            # OpenAI 兼容格式
            msg = data["choices"][0]["message"]
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # 示例可能包含 {"type":"text","text":"..."}
                texts = []
                for item in content:
                    if isinstance(item, dict):
                        if "text" in item and isinstance(item["text"], str):
                            texts.append(item["text"])
                if texts:
                    return "".join(texts)
            # 回退：原始 text 字段
            if "text" in msg and isinstance(msg["text"], str):
                return msg["text"]
        except Exception:
            pass
        return ""

    def _build_transcript_from_text(self, text: str, audio_path: Path) -> Transcript:
        """将 ASR 文本拆分为带时间戳的片段，覆盖完整音频时长。"""
        duration = self._get_audio_duration(audio_path)
        if duration <= 0:
            duration = 1.0
        parts = [p.strip() for p in re.split(r"(?<=[。！？!?；;])", text) if p.strip()]
        if not parts:
            parts = [text]
        gap_count = max(0, len(parts) - 1)
        per_gap = 0.45
        total_gap = min(duration * 0.2, per_gap * gap_count)
        speech_total = max(0.5, duration - total_gap)
        total_chars = sum(len(p) for p in parts) or 1
        segs: list[TranscriptSegment] = []
        cursor = 0.0
        for i, part in enumerate(parts):
            ratio = len(part) / total_chars
            seg_dur = max(0.3, speech_total * ratio)
            start = cursor
            end = min(duration, start + seg_dur)
            words = self._build_word_timestamps(part, start, end)
            segs.append(
                TranscriptSegment(
                    id=f"seg-{i+1:03d}",
                    start=round(start, 3),
                    end=round(end, 3),
                    text=part,
                    words=words,
                )
            )
            cursor = end + (per_gap if i < len(parts) - 1 else 0.0)
        if segs:
            # 强制覆盖完整时长
            last = segs[-1]
            segs[-1] = TranscriptSegment(
                id=last.id,
                start=last.start,
                end=round(duration, 3),
                text=last.text,
                words=self._build_word_timestamps(last.text, last.start, duration),
            )
        return Transcript(language="zh", segments=segs)

    def _build_word_timestamps(self, text: str, start: float, end: float) -> list[TranscriptWord]:
        tokens = [t for t in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text) if t]
        if not tokens:
            return []
        dur = max(0.001, end - start)
        step = dur / len(tokens)
        words = []
        for i, tok in enumerate(tokens):
            w_start = start + i * step
            w_end = start + (i + 1) * step
            words.append(
                TranscriptWord(
                    word=tok,
                    start=round(w_start, 3),
                    end=round(w_end, 3),
                    timestamp_source="estimated",
                )
            )
        return words

    def _get_audio_duration(self, audio_path: Path) -> float:
        try:
            with wave.open(str(audio_path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate() or 16000
                return float(frames) / float(rate)
        except Exception:
            return 0.0

    def _ms_to_seconds(self, value: Any) -> float:
        try:
            return max(0.0, float(value) / 1000.0)
        except (TypeError, ValueError):
            return 0.0

    def _env_bool(self, name: str, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}
