"""End-to-end tests: gather() → export() pipeline."""

import json

import pytest

import syft_ingest


@pytest.fixture
def output_dir(tmp_path):
    return tmp_path / "output"


def test_e2e_facebook_gather_and_export_jsonl(fb_export_path, output_dir):
    if not fb_export_path.exists():
        pytest.skip("Test data not available")

    output_file = output_dir / "fb.jsonl"
    corpus = syft_ingest.gather(
        "Syft Influencer Test",
        sources=["local"],
        local_dirs=[str(fb_export_path)],
    )
    corpus.export("jsonl", output=str(output_file))

    assert output_file.exists()
    lines = output_file.read_text().strip().splitlines()
    assert len(lines) == len(corpus.all_items())
    assert len(lines) > 0

    for line in lines:
        record = json.loads(line)
        assert record["text"].startswith("[Facebook post by")
        assert record["author"] == "Syft Influencer Test"
        assert record["metadata"]["platform"] == "facebook"
        assert record["metadata"]["content_hash"]
        # Encoding fixed
        assert "\u00e2\u0080\u0099" not in record["text"]
        # Export fields for RAG
        assert record["id"]  # stable ID
        assert record["site"] == "facebook.com"
        assert record["source_type"] == "social_media_post"
        assert record["published_at"]  # ISO 8601
        assert record["excerpt"]  # first 280 chars of raw text
        assert record["ingested_at"]  # timestamp


def test_e2e_brightdata_facebook_gather_and_export_jsonl(tmp_path, output_dir):
    brightdata_dir = tmp_path / "brightdata-fb"
    brightdata_dir.mkdir(parents=True, exist_ok=True)
    brightdata_payload = [
        {
            "post_id": "122243006504090679",
            "url": "https://www.facebook.com/reel/1378171301018195/",
            "date_posted": "2025-08-22T18:04:35.000Z",
            "page_name": "Painted Wildflowers",
            "content": "Easy flower tutorial #watercolor",
            "attachments": [
                {
                    "video_url": "https://video-ord5-3.xx.fbcdn.net/example/video.mp4",
                    "thumbnail_url": (
                        "https://scontent-ord5-1.xx.fbcdn.net/example/thumb.jpg"
                    ),
                }
            ],
        }
    ]
    (brightdata_dir / "brightdata-sample.json").write_text(
        json.dumps(brightdata_payload), encoding="utf-8"
    )

    output_file = output_dir / "fb-brightdata.jsonl"
    corpus = syft_ingest.gather(
        "Syft Influencer Test",
        sources=["local"],
        local_dirs=[str(brightdata_dir)],
    )
    corpus.export("jsonl", output=str(output_file))

    lines = output_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["metadata"]["platform"] == "facebook"
    assert record["metadata"]["extractor"] == "brightdata"
    assert record["metadata"]["post_ref"]["post_id"] == "122243006504090679"
    media = record["metadata"]["post_representation"]["media"]
    assert len(media) == 2
    assert sum(1 for entry in media if entry["media_type"] == "video") == 1
    assert sum(1 for entry in media if entry["media_type"] == "image") == 1


def test_e2e_instagram_gather_and_export_jsonl(ig_export_path, output_dir):
    if not ig_export_path.exists():
        pytest.skip("Test data not available")

    output_file = output_dir / "ig.jsonl"
    corpus = syft_ingest.gather(
        "Syft Influencer Test",
        sources=["local"],
        local_dirs=[str(ig_export_path)],
    )
    corpus.export("jsonl", output=str(output_file))

    assert output_file.exists()
    lines = output_file.read_text().strip().splitlines()
    assert len(lines) == len(corpus.all_items())
    assert len(lines) > 0

    for line in lines:
        record = json.loads(line)
        assert record["text"].startswith("[Instagram post by")
        assert record["metadata"]["platform"] == "instagram"
        assert record["metadata"]["content_hash"]
        assert record["metadata"]["cross_post_source"] == "FB"
        # Export fields for RAG
        assert record["id"]
        assert record["site"] == "instagram.com"
        assert record["source_type"] == "social_media_post"
        assert record["published_at"]
        assert record["excerpt"]
        assert record["ingested_at"]


def test_e2e_brightdata_instagram_gather_and_export_jsonl(tmp_path, output_dir):
    brightdata_dir = tmp_path / "brightdata-ig"
    brightdata_dir.mkdir(parents=True, exist_ok=True)
    brightdata_payload = [
        {
            "url": "https://www.instagram.com/p/DIWPWGpsUQX/",
            "shortcode": "DIWPWGpsUQX",
            "user_posted": "paintedwildflower",
            "description": "Carousel caption #watercolor",
            "hashtags": ["#painting"],
            "date_posted": "2025-04-12T13:03:14.000Z",
            "photos": [
                "https://cdninstagram.com/example/photo-1.jpg",
                "https://cdninstagram.com/example/photo-2.jpg",
            ],
        }
    ]
    (brightdata_dir / "brightdata-instagram.json").write_text(
        json.dumps(brightdata_payload), encoding="utf-8"
    )

    output_file = output_dir / "ig-brightdata.jsonl"
    corpus = syft_ingest.gather(
        "Syft Influencer Test",
        sources=["local"],
        local_dirs=[str(brightdata_dir)],
    )
    corpus.export("jsonl", output=str(output_file))

    lines = output_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["metadata"]["platform"] == "instagram"
    assert record["metadata"]["extractor"] == "brightdata"
    assert record["metadata"]["post_ref"]["shortcode"] == "DIWPWGpsUQX"
    media = record["metadata"]["post_representation"]["media"]
    assert len(media) == 2
    assert all(entry["media_type"] == "image" for entry in media)


def test_e2e_brightdata_instagram_export_preserves_rich_media_fields(
    tmp_path, output_dir
):
    brightdata_dir = tmp_path / "brightdata-ig-rich"
    brightdata_dir.mkdir(parents=True, exist_ok=True)
    brightdata_payload = [
        {
            "url": "https://www.instagram.com/p/DWCU6pojQMN/",
            "shortcode": "DWCU6pojQMN",
            "user_posted": "katykicker",
            "description": "Video caption",
            "date_posted": "2026-03-18T18:47:21.000Z",
            "content_type": "Reel",
            "photos": ["https://cdninstagram.com/example/cover.jpg"],
            "videos": ["https://cdninstagram.com/example/video.mp4"],
            "thumbnail": "https://cdninstagram.com/example/thumb.jpg",
            "audio": {
                "audio_asset_id": "audio-123",
                "original_audio_title": "Original sound",
            },
            "post_content": [
                {
                    "index": 0,
                    "type": "Video",
                    "url": "https://cdninstagram.com/example/video.mp4",
                }
            ],
            "latest_comments": [
                {
                    "comments": "Helpful video",
                    "user_commenting": "commenter_1",
                    "date_of_comment": "2026-03-18",
                }
            ],
        }
    ]
    (brightdata_dir / "brightdata-instagram-rich.json").write_text(
        json.dumps(brightdata_payload), encoding="utf-8"
    )

    output_file = output_dir / "ig-brightdata-rich.jsonl"
    corpus = syft_ingest.gather(
        "Syft Influencer Test",
        sources=["local"],
        local_dirs=[str(brightdata_dir)],
    )
    corpus.export("jsonl", output=str(output_file))

    lines = output_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    post_repr = record["metadata"]["post_representation"]
    assert post_repr["content_type"] == "Reel"
    assert post_repr["thumbnail_url"] == "https://cdninstagram.com/example/thumb.jpg"
    assert post_repr["audio"]["audio_asset_id"] == "audio-123"
    assert len(post_repr["content_items"]) == 1
    assert len(post_repr["latest_comments"]) == 1


def test_e2e_combined_gather(fb_export_path, ig_export_path, output_dir):
    if not fb_export_path.exists() or not ig_export_path.exists():
        pytest.skip("Test data not available")

    output_file = output_dir / "all.jsonl"
    corpus = syft_ingest.gather(
        "Syft Influencer Test",
        sources=["local"],
        local_dirs=[str(fb_export_path), str(ig_export_path)],
    )
    corpus.export("jsonl", output=str(output_file))

    lines = output_file.read_text().strip().splitlines()
    records = [json.loads(line) for line in lines]

    fb_records = [r for r in records if r["metadata"]["platform"] == "facebook"]
    ig_records = [r for r in records if r["metadata"]["platform"] == "instagram"]
    assert len(fb_records) > 0
    assert len(ig_records) > 0
    assert len(records) == len(fb_records) + len(ig_records)


def test_e2e_no_duplicate_urls_in_facebook(fb_export_path):
    if not fb_export_path.exists():
        pytest.skip("Test data not available")

    corpus = syft_ingest.gather(
        "Test", sources=["local"], local_dirs=[str(fb_export_path)]
    )
    urls = [item.url for item in corpus.all_items() if item.url]
    assert len(urls) == len(set(urls)), f"Duplicate URLs found: {urls}"


def test_e2e_no_bare_url_posts(fb_export_path, ig_export_path):
    if not fb_export_path.exists() or not ig_export_path.exists():
        pytest.skip("Test data not available")

    corpus = syft_ingest.gather(
        "Test",
        sources=["local"],
        local_dirs=[str(fb_export_path), str(ig_export_path)],
    )
    from syft_ingest.sources._meta_utils import is_bare_url

    for item in corpus.all_items():
        raw_text = item.text.split("\n\n", 1)[-1]
        assert not is_bare_url(raw_text), (
            f"Bare URL post slipped through: {raw_text[:80]}"
        )


def test_e2e_export_json(fb_export_path, output_dir):
    if not fb_export_path.exists():
        pytest.skip("Test data not available")

    output_file = output_dir / "fb.json"
    corpus = syft_ingest.gather(
        "Test", sources=["local"], local_dirs=[str(fb_export_path)]
    )
    corpus.export("json", output=str(output_file))

    data = json.loads(output_file.read_text())
    assert isinstance(data, list)
    assert len(data) == len(corpus.all_items())


def test_e2e_export_text(fb_export_path, output_dir):
    if not fb_export_path.exists():
        pytest.skip("Test data not available")

    text_dir = output_dir / "texts"
    corpus = syft_ingest.gather(
        "Test", sources=["local"], local_dirs=[str(fb_export_path)]
    )
    corpus.export("text", output_dir=str(text_dir))

    txt_files = list(text_dir.glob("*.txt"))
    assert len(txt_files) == len(corpus.all_items())
    # Filenames should not collide (indexed)
    assert len(txt_files) == len(set(f.name for f in txt_files))


def test_e2e_stable_ids_are_deterministic_and_unique(fb_export_path, output_dir):
    if not fb_export_path.exists():
        pytest.skip("Test data not available")

    # Export twice, IDs should be identical
    file1 = output_dir / "run1.jsonl"
    file2 = output_dir / "run2.jsonl"
    for f in [file1, file2]:
        corpus = syft_ingest.gather(
            "Test", sources=["local"], local_dirs=[str(fb_export_path)]
        )
        corpus.export("jsonl", output=str(f))

    ids1 = [json.loads(line)["id"] for line in file1.read_text().strip().splitlines()]
    ids2 = [json.loads(line)["id"] for line in file2.read_text().strip().splitlines()]
    assert ids1 == ids2, "IDs should be deterministic across runs"

    # All IDs should be unique
    assert len(ids1) == len(set(ids1)), "IDs should be unique"


def test_e2e_unknown_source_does_not_crash():
    corpus = syft_ingest.gather("Test", sources=["nonexistent"])
    assert len(corpus.all_items()) == 0


def test_e2e_empty_local_dirs():
    corpus = syft_ingest.gather(
        "Test", sources=["local"], local_dirs=["/nonexistent/path"]
    )
    assert len(corpus.all_items()) == 0
