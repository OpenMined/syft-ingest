from syft_ingest.sources._meta_utils import (
    content_hash,
    derive_title,
    extract_hashtags,
    extract_mentions,
    fix_meta_encoding,
    fix_meta_encoding_recursive,
    is_bare_url,
    normalize_text,
)


def test_fix_meta_encoding_curly_apostrophe():
    # \u00e2\u0080\u0099 is Meta's encoding of right single quote '
    broken = "\u00e2\u0080\u0099"
    assert fix_meta_encoding(broken) == "\u2019"  # '


def test_fix_meta_encoding_pound_sign():
    # \u00c2\u00a3 is Meta's encoding of £
    broken = "\u00c2\u00a3"
    assert fix_meta_encoding(broken) == "£"


def test_fix_meta_encoding_em_dash():
    # \u00e2\u0080\u0094 is Meta's encoding of —
    broken = "\u00e2\u0080\u0094"
    assert fix_meta_encoding(broken) == "—"


def test_fix_meta_encoding_smart_quotes():
    broken = "\u00e2\u0080\u009c"  # left "
    assert fix_meta_encoding(broken) == "\u201c"


def test_fix_meta_encoding_emoji():
    # \u00f0\u009f\u008e\u00ae is Meta's encoding of 🎮
    broken = "\u00f0\u009f\u008e\u00ae"
    assert fix_meta_encoding(broken) == "🎮"


def test_fix_meta_encoding_ascii_passthrough():
    clean = "Hello, world!"
    assert fix_meta_encoding(clean) == clean


def test_fix_meta_encoding_fallback_for_invalid():
    # String that can't be encoded as Latin-1 should pass through
    already_utf8 = "Héllo wörld"
    assert fix_meta_encoding(already_utf8) == already_utf8


def test_fix_meta_encoding_recursive_dict():
    data = {"text": "\u00e2\u0080\u0099", "count": 5, "nested": {"val": "\u00c2\u00a3"}}
    result = fix_meta_encoding_recursive(data)
    assert result["text"] == "\u2019"
    assert result["count"] == 5
    assert result["nested"]["val"] == "£"


def test_fix_meta_encoding_recursive_list():
    data = ["\u00e2\u0080\u0099", "clean", 42]
    result = fix_meta_encoding_recursive(data)
    assert result[0] == "\u2019"
    assert result[1] == "clean"
    assert result[2] == 42


def test_extract_hashtags():
    text = "Hello #world #AI #world"  # #world appears twice
    tags = extract_hashtags(text)
    assert tags == ["world", "ai"]


def test_extract_hashtags_empty():
    assert extract_hashtags("No hashtags here") == []


def test_extract_mentions():
    text = "Thanks @alice and @bob and @alice"
    mentions = extract_mentions(text)
    assert mentions == ["alice", "bob"]


def test_normalize_text():
    text = "Check https://example.com #AI @user  lots   of   spaces"
    result = normalize_text(text)
    assert "https://" in result  # URLs are kept for dedup
    assert "#" not in result
    assert "@" not in result
    assert "  " not in result
    assert result == result.lower()


def test_content_hash_deterministic():
    text = "Same content #tag https://example.com"
    h1 = content_hash(text)
    h2 = content_hash(text)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_content_hash_ignores_tags_but_not_urls():
    text1 = "Same content #tag1 https://example.com"
    text2 = "Same content #tag2 https://example.com"
    assert content_hash(text1) == content_hash(text2)

    # Different URLs should produce different hashes
    text3 = "Same content #tag1 https://example1.com"
    text4 = "Same content #tag1 https://example2.com"
    assert content_hash(text3) != content_hash(text4)


def test_is_bare_url_true():
    assert is_bare_url("https://openmined.org/")
    assert is_bare_url("  https://example.com  ")


def test_is_bare_url_false():
    assert not is_bare_url("Blog post\nhttps://example.com")
    assert not is_bare_url("Hello world")


def test_derive_title_short():
    assert derive_title("Short title") == "Short title"


def test_derive_title_long():
    long_text = "A" * 100 + " continuation"
    title = derive_title(long_text, max_length=80)
    assert len(title) <= 83  # 80 + "..."
    assert title.endswith("...")


def test_derive_title_no_spaces():
    long_word = "A" * 100
    title = derive_title(long_word, max_length=80)
    assert len(title) == 80  # 77 + "..."
    assert title.endswith("...")
