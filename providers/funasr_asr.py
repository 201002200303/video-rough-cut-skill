"""Local FunASR provider with provider-grade timestamps."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from core.utils import ProviderError, load_config, setup_logger
from providers.asr_base import ASRProvider
from schemas.models import Transcript, TranscriptSegment, TranscriptWord

logger = setup_logger(__name__)


class FunASRProvider(ASRProvider):
    """Transcribe audio locally with FunASR and normalize timestamps."""

    def __init__(self) -> None:
        cfg = load_config().get("funasr", {})
        self.model_name = os.getenv("FUNASR_MODEL", cfg.get("model", "paraformer-zh"))
        self.vad_model = os.getenv("FUNASR_VAD_MODEL", cfg.get("vad_model", "fsmn-vad"))
        self.punc_model = os.getenv("FUNASR_PUNC_MODEL", cfg.get("punc_model", "ct-punc"))
        self.device = os.getenv("FUNASR_DEVICE", cfg.get("device", "cpu"))
        self.batch_size_s = int(os.getenv("FUNASR_BATCH_SIZE_S", str(cfg.get("batch_size_s", 300))))
        self.sentence_timestamp = self._env_bool(
            "FUNASR_SENTENCE_TIMESTAMP",
            bool(cfg.get("sentence_timestamp", True)),
        )
        self.disable_update = bool(cfg.get("disable_update", True))

    def transcribe(self, audio_path: Path, output_path: Path) -> Transcript:
        if not audio_path.exists():
            raise ProviderError(f"Audio file not found: {audio_path}")
        try:
            logger.info("FunASR importing runtime")
            from funasr import AutoModel
        except ImportError as exc:
            raise ProviderError(
                f"FunASR import failed because a dependency is missing: {exc}. "
                "Install requirements, including torch and torchaudio, before running local timestamp ASR."
            ) from exc

        try:
            logger.info(
                "FunASR initializing model=%s vad_model=%s punc_model=%s device=%s",
                self.model_name,
                self.vad_model,
                self.punc_model,
                self.device,
            )
            model = AutoModel(
                model=self.model_name,
                vad_model=self.vad_model,
                punc_model=self.punc_model,
                device=self.device,
                disable_update=self.disable_update,
            )
            logger.info("FunASR transcribing audio: %s", audio_path)
            result = model.generate(
                input=str(audio_path),
                batch_size_s=self.batch_size_s,
                sentence_timestamp=self.sentence_timestamp,
            )
        except Exception as exc:
            raise ProviderError(f"FunASR transcription failed: {exc}") from exc

        transcript = self._build_transcript(result)
        logger.info("FunASR transcript parsed: segments=%d", len(transcript.segments))
        return transcript

    def _build_transcript(self, result: Any) -> Transcript:
        items = result if isinstance(result, list) else [result]
        segments: list[TranscriptSegment] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            segments.extend(self._segments_from_sentence_info(item))
            if not segments:
                segment = self._segment_from_item(item, len(segments) + 1)
                if segment:
                    segments.append(segment)
        if not segments:
            raise ProviderError(f"FunASR returned no usable transcript: {result}")
        return Transcript(language="zh", segments=segments)

    def _segments_from_sentence_info(self, item: dict[str, Any]) -> list[TranscriptSegment]:
        sentence_info = item.get("sentence_info") or item.get("sentences")
        if not isinstance(sentence_info, list):
            return []

        segments: list[TranscriptSegment] = []
        for index, sentence in enumerate(sentence_info, start=1):
            if not isinstance(sentence, dict):
                continue
            text = str(sentence.get("text") or sentence.get("sentence") or "").strip()
            raw_ts = sentence.get("timestamp") or sentence.get("ts_list") or sentence.get("words")
            words = self._words_from_timestamps(text, raw_ts)
            start = self._milliseconds_to_seconds(sentence.get("start") or sentence.get("begin_time"))
            end = self._milliseconds_to_seconds(sentence.get("end") or sentence.get("end_time"))
            if words:
                start = min(word.start for word in words)
                end = max(word.end for word in words)
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
        return segments

    def _segment_from_item(self, item: dict[str, Any], index: int) -> TranscriptSegment | None:
        text = str(item.get("text") or "").strip()
        words = self._words_from_timestamps(text, item.get("timestamp"))
        if not text:
            text = "".join(word.word for word in words)
        if not text:
            return None
        start = min((word.start for word in words), default=0.0)
        end = max((word.end for word in words), default=max(0.001, start + 0.001))
        return TranscriptSegment(
            id=f"seg-{index:03d}",
            start=round(start, 3),
            end=round(end, 3),
            text=text,
            words=words,
        )

    def _words_from_timestamps(self, text: str, raw_timestamps: Any) -> list[TranscriptWord]:
        timestamps = self._timestamp_pairs(raw_timestamps)
        if not timestamps:
            return []

        units = self._timestamp_units(text, len(timestamps))
        if len(units) != len(timestamps):
            logger.warning(
                "FunASR timestamp/text length mismatch: text_units=%s timestamps=%s",
                len(units),
                len(timestamps),
            )
            units = units[: len(timestamps)]

        words: list[TranscriptWord] = []
        for unit, (start, end) in zip(units, timestamps):
            if not unit.strip() or end <= start:
                continue
            words.append(
                TranscriptWord(
                    word=unit,
                    start=round(start, 3),
                    end=round(end, 3),
                    timestamp_source="provider",
                )
            )
        return words

    def _timestamp_pairs(self, raw_timestamps: Any) -> list[tuple[float, float]]:
        if not isinstance(raw_timestamps, list):
            return []
        pairs: list[tuple[float, float]] = []
        for item in raw_timestamps:
            if isinstance(item, dict):
                start = item.get("start") or item.get("begin_time")
                end = item.get("end") or item.get("end_time")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                start, end = item[0], item[1]
            else:
                continue
            start_s = self._milliseconds_to_seconds(start)
            end_s = self._milliseconds_to_seconds(end)
            if end_s > start_s:
                pairs.append((start_s, end_s))
        return pairs

    def _timestamp_units(self, text: str, timestamp_count: int) -> list[str]:
        tokens = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", text)
        if len(tokens) == timestamp_count:
            return tokens

        compact_chars = [char for char in text if not char.isspace()]
        if len(compact_chars) == timestamp_count:
            return compact_chars
        return compact_chars

    def _milliseconds_to_seconds(self, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, number / 1000.0)

    def _env_bool(self, name: str, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}
