"""Verify that all internal links, resources, and views in web/ resolve properly."""
import json
from pathlib import Path
import re


def test_web_static_assets_exist():
    web_dir = Path(__file__).parent.parent / "web"
    assert (web_dir / "index.html").exists()
    assert (web_dir / "app.js").exists()
    assert (web_dir / "architecture.html").exists()
    assert (web_dir / "data" / "pages.json").exists()
    assert (web_dir / "data" / "drift.json").exists()
    assert (web_dir / "data" / "cases.json").exists()


def test_web_data_json_validity():
    web_dir = Path(__file__).parent.parent / "web"
    
    with (web_dir / "data" / "pages.json").open() as f:
        pages = json.load(f)
        assert isinstance(pages, list)
        assert len(pages) >= 3
        for page in pages:
            assert "page_id" in page
            assert "entries" in page
            for entry in page["entries"]:
                assert "entry_id" in entry
                assert "blocks" in entry

    with (web_dir / "data" / "drift.json").open() as f:
        drift = json.load(f)
        assert "terms" in drift
        assert len(drift["terms"]) >= 1

    with (web_dir / "data" / "cases.json").open() as f:
        cases = json.load(f)
        assert isinstance(cases, list)
        assert len(cases) >= 2


def test_internal_links_resolve():
    web_dir = Path(__file__).parent.parent / "web"
    index_html = (web_dir / "index.html").read_text()
    arch_html = (web_dir / "architecture.html").read_text()

    # Verify link from index.html to architecture.html
    assert 'href="architecture.html"' in index_html
    # Verify return link from architecture.html to index.html
    assert 'href="index.html"' in arch_html


def test_stage_site_transform_runner(tmp_path):
    """Verify stages.site.run transforms artifacts into valid site JSON."""
    from nemotron_challenge.config import Settings
    from nemotron_challenge.stages import site

    settings = Settings.from_env()
    result = site.run(settings, tmp_path)
    assert result["status"] == "ok"
    assert result["pages_transformed"] >= 3
    assert result["entries_count"] >= 5
    assert result["matches_count"] >= 5
