import pytest

from syft_ingest.core.source_specs import SocialProfileSource


def test_gather_supports_social_profile_source_spec(tmp_path):
    # Skipped: source_specs API removed in favor of simplified gather(platform, urls) API
    pytest.skip("gather() source_specs API has been removed")


def test_social_profile_source_requires_identity():
    with pytest.raises(ValueError, match="handle or profile_url"):
        SocialProfileSource(
            platform="instagram",
            raw_dirs=["/tmp/example"],
        )


def test_gather_rejects_platform_mismatch_in_source_spec(monkeypatch):
    # Skipped: source_specs API removed in favor of simplified gather(platform, urls) API
    pytest.skip("gather() source_specs API has been removed")
