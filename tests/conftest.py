from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent.parent / "data" / "creators" / "syft-influencer-test"


@pytest.fixture
def fb_export_path():
    return DATA_DIR / "fb-page-2026-03-18"


@pytest.fixture
def ig_export_path():
    return DATA_DIR / "instagram-2026-03-18"
