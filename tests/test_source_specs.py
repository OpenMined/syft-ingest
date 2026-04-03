import json

import pytest

import syft_ingest
from syft_ingest.core.source_specs import SocialProfileSource


def test_gather_supports_social_profile_source_spec(tmp_path):
    brightdata_dir = tmp_path / "brightdata-ig"
    brightdata_dir.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "url": "https://www.instagram.com/p/DIWPWGpsUQX/",
            "shortcode": "DIWPWGpsUQX",
            "user_posted": "paintedwildflower",
            "description": "Carousel caption #watercolor",
            "date_posted": "2025-04-12T13:03:14.000Z",
            "photos": ["https://cdninstagram.com/example/photo-1.jpg"],
        }
    ]
    (brightdata_dir / "brightdata-instagram.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    corpus = syft_ingest.gather(
        "Painted Wildflower",
        source_specs=[
            SocialProfileSource(
                platform="instagram",
                extractor="brightdata",
                handle="paintedwildflower",
                profile_url="https://www.instagram.com/paintedwildflower/",
                raw_dirs=[str(brightdata_dir)],
                start_date="2025-01-01",
                end_date="2025-12-31",
                external_account_id="ig_123",
            )
        ],
    )

    assert len(corpus.all_items()) == 1
    metadata = corpus.all_items()[0].metadata
    assert metadata["platform"] == "instagram"
    assert metadata["extractor"] == "brightdata"
    assert metadata["source_profile"]["handle"] == "paintedwildflower"
    assert (
        metadata["source_profile"]["profile_url"]
        == "https://www.instagram.com/paintedwildflower/"
    )
    assert metadata["source_profile"]["start_date"] == "2025-01-01"


def test_social_profile_source_requires_identity():
    with pytest.raises(ValueError, match="handle or profile_url"):
        SocialProfileSource(
            platform="instagram",
            raw_dirs=["/tmp/example"],
        )
