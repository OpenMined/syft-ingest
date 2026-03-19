import pytest

from syft_ingest.sources.local import fetch_local


def test_fetch_local_detects_facebook(fb_export_path):
    if not fb_export_path.exists():
        pytest.skip("Test data not available")

    items = fetch_local([str(fb_export_path)], author="Test Author")
    assert len(items) > 0
    assert all(item.author == "Test Author" for item in items)


def test_fetch_local_detects_instagram(ig_export_path):
    if not ig_export_path.exists():
        pytest.skip("Test data not available")

    items = fetch_local([str(ig_export_path)], author="Test Author")
    assert len(items) > 0
    assert all(item.metadata.get("platform") == "instagram" for item in items)


def test_fetch_local_nonexistent_dir():
    items = fetch_local(["/nonexistent/path"], author="Test")
    assert items == []


def test_fetch_local_unrecognized_dir(tmp_path):
    items = fetch_local([str(tmp_path)], author="Test")
    assert items == []


def test_fetch_local_multiple_dirs(fb_export_path, ig_export_path):
    if not fb_export_path.exists() or not ig_export_path.exists():
        pytest.skip("Test data not available")

    items = fetch_local(
        [str(fb_export_path), str(ig_export_path)],
        author="Test Author",
    )
    assert len(items) > 0

    platforms = {item.metadata.get("platform") for item in items}
    assert "facebook" in platforms
    assert "instagram" in platforms
