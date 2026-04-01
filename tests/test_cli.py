import json

from syft_ingest.cli import main


def test_cli_local_export_jsonl(tmp_path):
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
    output_file = tmp_path / "output.jsonl"

    exit_code = main(
        [
            "local-export",
            "--author",
            "Fallback Author",
            "--input-dir",
            str(brightdata_dir),
            "--format",
            "jsonl",
            "--output",
            str(output_file),
        ]
    )

    assert exit_code == 0
    lines = output_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["metadata"]["platform"] == "instagram"
    assert record["metadata"]["extractor"] == "brightdata"
