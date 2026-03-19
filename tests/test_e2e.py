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


def test_e2e_unknown_source_does_not_crash():
    corpus = syft_ingest.gather("Test", sources=["nonexistent"])
    assert len(corpus.all_items()) == 0


def test_e2e_empty_local_dirs():
    corpus = syft_ingest.gather(
        "Test", sources=["local"], local_dirs=["/nonexistent/path"]
    )
    assert len(corpus.all_items()) == 0
