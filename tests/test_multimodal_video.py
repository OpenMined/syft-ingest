import json

import pytest

from syft_ingest.rag.embedders.multimodal_video import (
    TranscriptSegment,
    compute_sample_timestamps,
    fuse_embeddings,
    load_transcript_segments,
    transcript_text_near_timestamp,
)


def test_compute_sample_timestamps_basic():
    timestamps = compute_sample_timestamps(5.1, 2.0)
    assert timestamps == [0.0, 2.0, 4.0]


def test_compute_sample_timestamps_respects_max_frames():
    timestamps = compute_sample_timestamps(20.0, 1.0, max_frames=3)
    assert timestamps == [0.0, 1.0, 2.0]


def test_fuse_embeddings_image_only_normalizes():
    fused = fuse_embeddings([3.0, 4.0], None)
    assert fused == pytest.approx([0.6, 0.8])


def test_fuse_embeddings_with_text_weight():
    fused = fuse_embeddings([1.0, 0.0], [0.0, 1.0], text_weight=0.25)
    assert fused == pytest.approx([0.948683, 0.316228], abs=1e-5)


def test_transcript_text_near_timestamp_joins_overlaps():
    segments = [
        TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello"),
        TranscriptSegment(start_seconds=1.0, end_seconds=3.0, text="world"),
        TranscriptSegment(start_seconds=8.0, end_seconds=9.0, text="ignored"),
    ]
    text = transcript_text_near_timestamp(segments, timestamp_seconds=2.0, window_seconds=4.0)
    assert text == "hello world"


def test_load_transcript_segments_json(tmp_path):
    transcript = [
        {"start": 0.0, "end": 1.5, "text": "a"},
        {"start": 2.0, "end": 3.0, "text": "b"},
    ]
    path = tmp_path / "segments.json"
    path.write_text(json.dumps(transcript), encoding="utf-8")

    segments = load_transcript_segments(path)
    assert len(segments) == 2
    assert segments[0].text == "a"
    assert segments[1].start_seconds == 2.0


def test_load_transcript_segments_jsonl(tmp_path):
    path = tmp_path / "segments.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"start": 0.0, "end": 2.0, "text": "first"}),
                json.dumps({"start": 2.0, "end": 4.0, "text": "second"}),
            ]
        ),
        encoding="utf-8",
    )

    segments = load_transcript_segments(path)
    assert [segment.text for segment in segments] == ["first", "second"]
