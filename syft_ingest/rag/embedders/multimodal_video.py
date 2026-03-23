from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FrameSample:
    timestamp_seconds: float
    image_path: Path


@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str


def compute_sample_timestamps(
    duration_seconds: float, interval_seconds: float, max_frames: int | None = None
) -> list[float]:
    """Compute frame sampling timestamps across a video's duration."""
    if duration_seconds <= 0:
        return []
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be > 0")
    if max_frames is not None and max_frames <= 0:
        raise ValueError("max_frames must be > 0 when set")

    timestamps: list[float] = []
    current = 0.0
    while current < duration_seconds:
        timestamps.append(round(current, 3))
        current += interval_seconds
        if max_frames is not None and len(timestamps) >= max_frames:
            break

    return timestamps


def _l2_normalize(vector: list[float]) -> list[float]:
    squared_norm = sum(v * v for v in vector)
    if squared_norm <= 0:
        return vector
    inv_norm = squared_norm**-0.5
    return [v * inv_norm for v in vector]


def fuse_embeddings(
    image_embedding: list[float],
    text_embedding: list[float] | None = None,
    *,
    text_weight: float = 0.35,
) -> list[float]:
    """Fuse image and text embeddings into one vector (weighted average + L2 norm)."""
    if not 0 <= text_weight <= 1:
        raise ValueError("text_weight must be between 0 and 1")

    if text_embedding is None:
        return _l2_normalize(image_embedding)

    if len(image_embedding) != len(text_embedding):
        raise ValueError("image and text embedding dimensions must match")

    image_weight = 1.0 - text_weight
    fused = [
        (image_weight * i) + (text_weight * t)
        for i, t in zip(image_embedding, text_embedding, strict=True)
    ]
    return _l2_normalize(fused)


def transcript_text_near_timestamp(
    segments: list[TranscriptSegment], timestamp_seconds: float, window_seconds: float
) -> str:
    """Collect transcript text near a timestamp within a symmetric time window."""
    if window_seconds <= 0:
        return ""

    half = window_seconds / 2.0
    start_window = timestamp_seconds - half
    end_window = timestamp_seconds + half

    matches: list[str] = []
    for segment in segments:
        if segment.end_seconds < start_window:
            continue
        if segment.start_seconds > end_window:
            continue
        text = segment.text.strip()
        if text:
            matches.append(text)

    return " ".join(matches).strip()


def load_transcript_segments(path: str | Path) -> list[TranscriptSegment]:
    """Load transcript segments from JSON or JSONL.

    Segment format:
    {"start": 0.0, "end": 2.5, "text": "..."}
    """
    transcript_path = Path(path)
    raw = transcript_path.read_text(encoding="utf-8").strip()
    if not raw:
        return []

    entries: list[dict]
    if transcript_path.suffix.lower() == ".jsonl":
        entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Transcript JSON must be a list of segment objects")
        entries = data

    segments: list[TranscriptSegment] = []
    for entry in entries:
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        start = float(entry.get("start", 0.0))
        end = float(entry.get("end", start))
        if end < start:
            end = start
        segments.append(
            TranscriptSegment(
                start_seconds=start,
                end_seconds=end,
                text=text,
            )
        )

    return segments


def extract_frames_with_opencv(
    video_path: str | Path,
    *,
    output_dir: str | Path,
    interval_seconds: float = 2.0,
    max_frames: int = 240,
) -> list[FrameSample]:
    """Extract frames from a video at fixed time intervals with OpenCV."""
    try:
        import cv2
    except ImportError as e:
        raise RuntimeError(
            "OpenCV is required for frame extraction. Install with: "
            "`uv sync --extra multimodal`"
        ) from e

    source = Path(video_path)
    if not source.is_file():
        raise FileNotFoundError(f"Video file not found: {source}")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {source}")

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration_seconds = frame_count / fps if fps > 0 else 0.0

        timestamps = compute_sample_timestamps(
            duration_seconds, interval_seconds, max_frames
        )
        samples: list[FrameSample] = []

        for idx, ts in enumerate(timestamps):
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            file_path = out / f"frame_{idx:05d}_{int(ts * 1000):010d}.jpg"
            cv2.imwrite(str(file_path), frame)
            samples.append(FrameSample(timestamp_seconds=ts, image_path=file_path))

        return samples
    finally:
        cap.release()


def transcribe_video_with_whisper(
    video_path: str | Path,
    *,
    model_name: str = "base",
) -> list[TranscriptSegment]:
    """Transcribe video audio with Whisper and return timed transcript segments."""
    try:
        import whisper
    except ImportError as e:
        raise RuntimeError(
            "Whisper is required for automatic transcripts. Install with: "
            "`uv sync --extra podcast`"
        ) from e

    model = whisper.load_model(model_name)
    result = model.transcribe(str(video_path))
    raw_segments = result.get("segments", [])

    segments: list[TranscriptSegment] = []
    for segment in raw_segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        segments.append(
            TranscriptSegment(start_seconds=start, end_seconds=end, text=text)
        )

    return segments


def embed_records_with_clip(
    records: list[dict],
    *,
    model_name: str = "clip-ViT-B-32",
    text_weight: float = 0.35,
    batch_size: int = 16,
) -> list[dict]:
    """Embed frame+text records with a CLIP-family model from sentence-transformers."""
    if not records:
        return []

    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            "Pillow is required for image loading. Install with: "
            "`uv sync --extra multimodal`"
        ) from e

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError(
            "sentence-transformers is required for CLIP embeddings. "
            "Install with: `uv sync --extra multimodal`"
        ) from e

    model = SentenceTransformer(model_name)

    images = [Image.open(r["image_path"]).convert("RGB") for r in records]
    image_vectors = model.encode(
        images,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    text_indices = [i for i, record in enumerate(records) if record["transcript"]]
    text_lookup: dict[int, list[float]] = {}
    if text_indices:
        text_inputs = [records[i]["transcript"] for i in text_indices]
        text_vectors = model.encode(
            text_inputs,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        text_lookup = {
            idx: vector.tolist()
            for idx, vector in zip(text_indices, text_vectors, strict=True)
        }

    enriched: list[dict] = []
    for i, record in enumerate(records):
        image_embedding = image_vectors[i].tolist()
        text_embedding = text_lookup.get(i)
        fused = fuse_embeddings(
            image_embedding,
            text_embedding,
            text_weight=text_weight,
        )

        enriched.append(
            {
                **record,
                "embedding": fused,
                "embedding_dim": len(fused),
            }
        )

    return enriched


def write_embeddings_jsonl(records: list[dict], output_path: str | Path) -> Path:
    """Write multimodal embedding records to JSONL."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as f:
        for record in records:
            row = {
                **record,
                "image_path": str(record["image_path"]),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return output


def embed_video_multimodal(
    video_path: str | Path,
    *,
    output_path: str | Path,
    frames_dir: str | Path | None = None,
    interval_seconds: float = 2.0,
    max_frames: int = 240,
    transcript_path: str | Path | None = None,
    whisper_model: str | None = None,
    transcript_window_seconds: float = 8.0,
    clip_model: str = "clip-ViT-B-32",
    text_weight: float = 0.35,
    batch_size: int = 16,
) -> Path:
    """Run a full multimodal video embedding pipeline and write JSONL output."""
    video = Path(video_path)
    if not video.is_file():
        raise FileNotFoundError(f"Video file not found: {video}")

    out = Path(output_path)
    frame_output_dir = Path(frames_dir) if frames_dir else out.parent / "frames"

    frame_samples = extract_frames_with_opencv(
        video,
        output_dir=frame_output_dir,
        interval_seconds=interval_seconds,
        max_frames=max_frames,
    )
    if not frame_samples:
        raise RuntimeError("No frames extracted from video")

    if transcript_path:
        segments = load_transcript_segments(transcript_path)
    elif whisper_model:
        segments = transcribe_video_with_whisper(video, model_name=whisper_model)
    else:
        segments = []

    records: list[dict] = []
    for sample in frame_samples:
        transcript = transcript_text_near_timestamp(
            segments,
            sample.timestamp_seconds,
            window_seconds=transcript_window_seconds,
        )
        chunk_id = hashlib.sha256(
            f"{video}:{sample.timestamp_seconds:.3f}".encode("utf-8")
        ).hexdigest()[:32]
        records.append(
            {
                "id": chunk_id,
                "video_path": str(video),
                "timestamp_seconds": sample.timestamp_seconds,
                "image_path": sample.image_path,
                "transcript": transcript,
            }
        )

    embedded = embed_records_with_clip(
        records,
        model_name=clip_model,
        text_weight=text_weight,
        batch_size=batch_size,
    )
    return write_embeddings_jsonl(embedded, out)
