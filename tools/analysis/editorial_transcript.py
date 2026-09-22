"""Build a compact, source-aware editorial transcript artifact.

The transcript produced by :mod:`tools.analysis.transcriber` is useful for
captions, but it is not an efficient surface for an editing agent.  This tool
normalises the provider output, groups words into phrase-sized takes, and
keeps enough provenance to make cached editorial decisions safe to reuse.

The implementation deliberately accepts the existing Whisper/WhisperX shape
instead of depending on a particular transcription provider.  A packed
Markdown view is a derived convenience; the JSON artifact remains canonical.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ResumeSupport,
    RetryPolicy,
    ToolResult,
    ToolStability,
    ToolTier,
)


_CJK_RANGES = (
    (0x2E80, 0x2FFF),
    (0x3000, 0x303F),
    (0x3040, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xAC00, 0xD7AF),
)
_NO_SPACE_BEFORE = set(",.!?;:%)]}»”'\u3001\u3002\uff0c\uff01\uff1f\uff1b\uff1a\uff09\u300d\u300f")
_NO_SPACE_AFTER = set("([{«“'\u300c\u300e")


def _number(value: Any, default: float = 0.0) -> float:
    """Return a finite float without allowing malformed provider values through."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result and abs(result) != float("inf") else default


def _is_cjk(text: str) -> bool:
    return any(start <= ord(char) <= end for char in text for start, end in _CJK_RANGES)


def join_tokens(tokens: Iterable[str]) -> str:
    """Join ASR tokens without inserting spaces into CJK text or punctuation."""
    result = ""
    for raw in tokens:
        token = str(raw).strip()
        if not token:
            continue
        if not result:
            result = token
            continue
        previous = result[-1:]
        first = token[:1]
        no_space = (
            first in _NO_SPACE_BEFORE
            or previous in _NO_SPACE_AFTER
            or _is_cjk(previous + first)
        )
        result += ("" if no_space else " ") + token
    return result


def _normalise_word(item: Any, index: int) -> Optional[dict[str, Any]]:
    """Normalise common Whisper/WhisperX word shapes."""
    if isinstance(item, str):
        return {"index": index, "start": 0.0, "end": 0.0, "text": item.strip()}
    if not isinstance(item, dict):
        return None
    text = item.get("text", item.get("word", item.get("token", "")))
    text = str(text or "").strip()
    if not text:
        return None
    start = _number(item.get("start", item.get("start_seconds", item.get("from"))))
    end = _number(item.get("end", item.get("end_seconds", item.get("to"))), start)
    if end < start:
        start, end = end, start
    # Provider output occasionally omits word timing.  Keep the token for
    # editorial reading, but exclude it from boundary arithmetic.
    return {
        "index": index,
        "start": round(max(start, 0.0), 3),
        "end": round(max(end, 0.0), 3),
        "text": text,
        "speaker": item.get("speaker", item.get("speaker_id")),
        "source_id": item.get("source_id", item.get("source")),
        "confidence": item.get("confidence", item.get("probability")),
    }


def extract_words(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten provider output into a stable list of word records."""
    raw_words = list(payload.get("word_timestamps") or payload.get("words") or [])
    if not raw_words:
        for segment in payload.get("segments") or []:
            if isinstance(segment, dict):
                raw_words.extend(segment.get("words") or [])

    words: list[dict[str, Any]] = []
    for raw in raw_words:
        word = _normalise_word(raw, len(words))
        if word is not None:
            words.append(word)
    # Do not reorder a transcript with missing timings; stable provider order
    # is more useful than inventing a timeline.  Timed records are sorted only
    # when all records have a positive interval.
    if words and all(word["end"] > word["start"] for word in words):
        words.sort(key=lambda word: (word["start"], word["end"], word["index"]))
        for index, word in enumerate(words):
            word["index"] = index
    return words


def _normalise_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events = payload.get("audio_events") or payload.get("events") or []
    normalised: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        start = _number(event.get("start", event.get("start_seconds")))
        end = _number(event.get("end", event.get("end_seconds")), start)
        record = {
            "start": round(max(start, 0.0), 3),
            "end": round(max(end, start), 3),
            "type": str(event.get("type", event.get("event", "unknown"))),
        }
        if event.get("confidence") is not None:
            record["confidence"] = event["confidence"]
        normalised.append(record)
    return normalised


def _phrase_events(start: float, end: float, events: list[dict[str, Any]]) -> list[str]:
    return sorted({event["type"] for event in events if event["end"] >= start and event["start"] <= end})


def pack_phrases(
    words: list[dict[str, Any]],
    *,
    silence_gap_seconds: float = 0.5,
    max_words: int = 80,
    events: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Group words at silence/speaker/source boundaries into editorial phrases."""
    if not words:
        return []
    # Keep the public helper friendly to raw Whisper-shaped records in tests
    # and integrations; extract_words already produces this shape for the
    # normal tool path.
    if any("text" not in word or "index" not in word for word in words):
        normalised: list[dict[str, Any]] = []
        for index, raw in enumerate(words):
            word = _normalise_word(raw, index)
            if word is not None:
                normalised.append(word)
        words = normalised
        if not words:
            return []
    events = events or []
    phrases: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        timed = [word for word in current if word["end"] > word["start"]]
        start = timed[0]["start"] if timed else 0.0
        end = timed[-1]["end"] if timed else start
        first = current[0]
        last = current[-1]
        phrase = {
            "id": f"phrase-{len(phrases):04d}",
            "start": round(start, 3),
            "end": round(end, 3),
            "text": join_tokens(word["text"] for word in current),
            "word_start": first["index"],
            "word_end": last["index"],
            "speaker": first.get("speaker"),
            "source_id": first.get("source_id"),
            "audio_events": _phrase_events(start, end, events),
        }
        phrases.append(phrase)
        current.clear()

    for word in words:
        if current:
            previous = current[-1]
            gap = word["start"] - previous["end"]
            speaker_changed = (
                word.get("speaker") is not None
                and previous.get("speaker") is not None
                and word.get("speaker") != previous.get("speaker")
            )
            source_changed = (
                word.get("source_id") is not None
                and previous.get("source_id") is not None
                and word.get("source_id") != previous.get("source_id")
            )
            if gap >= silence_gap_seconds or speaker_changed or source_changed or len(current) >= max_words:
                flush()
        current.append(word)
    flush()
    return phrases


def source_fingerprint(source_path: Optional[Path], payload: dict[str, Any]) -> str:
    """Hash the source when available, otherwise hash the transcript payload."""
    digest = hashlib.sha256()
    if source_path is not None and source_path.is_file():
        with source_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    digest.update(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
    return digest.hexdigest()


def _load_payload(inputs: dict[str, Any]) -> tuple[dict[str, Any], Optional[Path]]:
    payload = inputs.get("transcript")
    transcript_path: Optional[Path] = None
    if isinstance(payload, str):
        transcript_path = Path(payload)
        payload = None
    if payload is None and inputs.get("transcript_path"):
        transcript_path = Path(inputs["transcript_path"])
        if not transcript_path.is_file():
            raise FileNotFoundError(f"Transcript not found: {transcript_path}")
        payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    if payload is None:
        raise ValueError("Provide transcript or transcript_path")
    if not isinstance(payload, dict):
        raise ValueError("Transcript must be a JSON object")
    return payload, transcript_path


class EditorialTranscript(BaseTool):
    name = "editorial_transcript"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies: list[str] = []
    capabilities = ["pack_transcript", "source_fingerprint", "editorial_phrases"]
    input_schema = {
        "type": "object",
        "properties": {
            "transcript_path": {"type": "string"},
            "transcript": {"type": "object"},
            "source_path": {"type": "string"},
            "source_id": {"type": "string"},
            "audio_track": {"type": ["integer", "string", "null"]},
            "silence_gap_seconds": {"type": "number", "minimum": 0, "default": 0.5},
            "max_words_per_phrase": {"type": "integer", "minimum": 1, "default": 80},
            "output_path": {"type": "string"},
        },
        "anyOf": [{"required": ["transcript_path"]}, {"required": ["transcript"]}],
    }
    output_schema = {"type": "object", "required": ["version", "words", "phrases", "source_fingerprint"]}
    artifact_schema = {"name": "editorial_transcript", "version": "1.0"}
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, disk_mb=50)
    retry_policy = RetryPolicy(max_retries=0)
    resume_support = ResumeSupport.FROM_START
    idempotency_key_fields = ["transcript_path", "source_path", "source_id", "silence_gap_seconds", "max_words_per_phrase"]
    side_effects = ["writes editorial transcript JSON to output_path"]
    user_visible_verification = ["Check packed phrase boundaries against the source transcript"]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        try:
            payload, transcript_path = _load_payload(inputs)
            source_path = Path(inputs["source_path"]) if inputs.get("source_path") else None
            words = extract_words(payload)
            events = _normalise_events(payload)
            phrases = pack_phrases(
                words,
                silence_gap_seconds=max(_number(inputs.get("silence_gap_seconds"), 0.5), 0.0),
                max_words=max(int(inputs.get("max_words_per_phrase", 80)), 1),
                events=events,
            )
            fingerprint = source_fingerprint(source_path, payload)
            artifact: dict[str, Any] = {
                "version": "1.0",
                "source_id": inputs.get("source_id") or payload.get("source_id") or (source_path.stem if source_path else None),
                "source_path": str(source_path) if source_path else None,
                "source_fingerprint": fingerprint,
                "audio_track": inputs.get("audio_track", payload.get("audio_track")),
                "provider": str(payload.get("provider") or "unknown"),
                "model": (str(payload.get("model") or payload.get("model_size"))
                          if payload.get("model") or payload.get("model_size") else None),
                "language": (str(payload.get("language")) if payload.get("language") else None),
                "words": words,
                "phrases": phrases,
                "audio_events": events,
                "metadata": {
                    "word_count": len(words),
                    "phrase_count": len(phrases),
                    "transcript_path": str(transcript_path) if transcript_path else None,
                    "silence_gap_seconds": max(_number(inputs.get("silence_gap_seconds"), 0.5), 0.0),
                },
            }
            cache_material = {key: value for key, value in artifact.items() if key != "metadata"}
            artifact["cache_key"] = hashlib.sha256(
                json.dumps(cache_material, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:24]

            output_path = inputs.get("output_path")
            if output_path:
                destination = Path(output_path)
            elif transcript_path:
                destination = transcript_path.with_suffix(".editorial.json")
            else:
                destination = Path.cwd() / "editorial_transcript.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return ToolResult(
                success=True,
                data=artifact,
                artifacts=[str(destination)],
                duration_seconds=round(time.time() - started, 2),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return ToolResult(success=False, error=str(exc), duration_seconds=round(time.time() - started, 2))
