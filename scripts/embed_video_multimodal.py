from __future__ import annotations

import argparse

from syft_ingest.rag.embedders.multimodal_video import embed_video_multimodal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create multimodal (frame + transcript) embeddings for a local video."
    )
    parser.add_argument("video", help="Path to local video file (mp4, mov, etc.)")
    parser.add_argument(
        "--output",
        default="output/video_embeddings.jsonl",
        help="Output JSONL path",
    )
    parser.add_argument(
        "--frames-dir",
        default=None,
        help="Directory for extracted frames (defaults to <output parent>/frames)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=2.0,
        help="Seconds between sampled frames",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=240,
        help="Maximum number of sampled frames",
    )
    parser.add_argument(
        "--transcript-json",
        default=None,
        help="Optional transcript file (.json or .jsonl) with start/end/text segments",
    )
    parser.add_argument(
        "--whisper-model",
        default=None,
        help="Optional Whisper model name for auto-transcription (e.g. base, small, medium)",
    )
    parser.add_argument(
        "--transcript-window-seconds",
        type=float,
        default=8.0,
        help="Time window for attaching transcript text to each frame",
    )
    parser.add_argument(
        "--clip-model",
        default="clip-ViT-B-32",
        help="sentence-transformers CLIP model",
    )
    parser.add_argument(
        "--text-weight",
        type=float,
        default=0.35,
        help="Weight of transcript embedding in final fused vector (0..1)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="Embedding batch size",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output = embed_video_multimodal(
        args.video,
        output_path=args.output,
        frames_dir=args.frames_dir,
        interval_seconds=args.interval_seconds,
        max_frames=args.max_frames,
        transcript_path=args.transcript_json,
        whisper_model=args.whisper_model,
        transcript_window_seconds=args.transcript_window_seconds,
        clip_model=args.clip_model,
        text_weight=args.text_weight,
        batch_size=args.batch_size,
    )
    print(f"Wrote multimodal embeddings to {output}")


if __name__ == "__main__":
    main()
