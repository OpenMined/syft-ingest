import pytest

from syft_ingest.rag.embedders.multimodal_post import (
    build_post_embedding_text,
    fuse_modality_embeddings,
    simple_summarize_text,
)


def test_simple_summarize_text_noop_for_short_text():
    text = "Short post with #tag and @mention."
    assert simple_summarize_text(text, max_chars=120) == text


def test_simple_summarize_text_truncates_long_text():
    text = (
        "Sentence one about watercolor flowers. "
        "Sentence two includes #floral tips. "
        "Sentence three with @friend reference. "
        "Sentence four has a link https://example.com/tutorial. "
        "Sentence five wraps up."
    )
    summary = simple_summarize_text(text, max_chars=90, max_sentences=3)
    assert len(summary) <= 90
    assert "Sentence one" in summary


def test_build_post_embedding_text_uses_summary_and_tags():
    text = build_post_embedding_text(
        author="Jen",
        title="Floral study",
        text="Long body text",
        tags=["watercolor", "floral"],
        mentions=["paintedwildflower"],
        published_at="2026-03-22T10:00:00Z",
        image_count=2,
        video_count=1,
        summary="Short summary",
        include_tags_in_text=True,
    )
    assert "Author: Jen" in text
    assert "Tags: #watercolor #floral" in text
    assert "Media: 2 image(s), 1 video(s)" in text
    assert text.endswith("Post: Short summary")


def test_build_post_embedding_text_excludes_tags_by_default():
    text = build_post_embedding_text(
        author="Jen",
        title="Floral study",
        text="Long body text",
        tags=["watercolor", "floral"],
        mentions=[],
        published_at="2026-03-22T10:00:00Z",
        image_count=0,
        video_count=0,
        summary=None,
    )
    assert "Tags:" not in text


def test_fuse_modality_embeddings_reweights_missing_modalities():
    fused = fuse_modality_embeddings(
        text_embedding=[1.0, 0.0],
        image_embedding=[0.0, 1.0],
        video_embedding=None,
        text_weight=0.8,
        image_weight=0.2,
        video_weight=0.0,
    )
    assert fused == pytest.approx([0.970143, 0.242536], abs=1e-5)


def test_fuse_modality_embeddings_falls_back_to_uniform_when_weights_zero():
    fused = fuse_modality_embeddings(
        text_embedding=[1.0, 0.0],
        image_embedding=[0.0, 1.0],
        video_embedding=None,
        text_weight=0.0,
        image_weight=0.0,
        video_weight=0.0,
    )
    assert fused == pytest.approx([0.707106, 0.707106], abs=1e-5)
