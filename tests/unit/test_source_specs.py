import pytest

from syft_ingest.core.source_specs import SocialProfileSource


def test_social_profile_source_requires_identity():
    with pytest.raises(ValueError, match="handle or profile_url"):
        SocialProfileSource(
            platform="instagram",
            raw_dirs=["/tmp/example"],
        )
