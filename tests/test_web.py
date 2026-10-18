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

    app_js = (web_dir / "app.js").read_text()

    # The Pipeline view embeds the architecture diagram.
    assert 'href="#pipeline"' in index_html
    assert 'src="architecture.html"' in app_js
    assert "<svg" in arch_html
    # The app loads every data file that the site stage writes.
    for name in ("pages", "drift", "cases"):
        assert name in app_js


def test_stage_site_transform_runner(tmp_path, monkeypatch):
    """Verify stages.site.run transforms artifacts into valid site JSON without touching the repository's web/."""
    from nemotron_challenge.config import Settings
    from nemotron_challenge.stages import site

    monkeypatch.setenv("SITE_WEB_DIR", str(tmp_path / "web"))
    monkeypatch.setenv("SITE_SCANS_DIR", str(tmp_path / "no-scans"))
    settings = Settings.from_env()
    result = site.run(settings, tmp_path)
    assert result["status"] == "ok"
    assert result["pages_transformed"] >= 3
    assert result["entries_count"] >= 5
    assert result["matches_count"] >= 5


def test_site_copies_compiled_pdfs_and_crops_under_extract_names(tmp_path):
    """Extract writes latex/<row:04d>.pdf and crops/<entry_id>.png; the site must find both."""
    import shutil

    from nemotron_challenge.stages.site import transform_artifacts_to_site_data

    fixtures = Path(__file__).parent / "fixtures" / "artifacts"
    work = tmp_path / "artifacts"
    shutil.copytree(fixtures, work)
    (work / "extract" / "latex").mkdir()
    (work / "extract" / "latex" / "0013.pdf").write_bytes(b"%PDF-1.4 test")
    crop = tmp_path / "artifacts" / "extract" / "crops" / "e0013-01.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"\x89PNG")
    web = tmp_path / "web"
    result = transform_artifacts_to_site_data(work_dir=work, raw_scans_dir=tmp_path / "no-scans", web_dir=web)
    assert result["status"] == "ok"
    pages = json.loads((web / "data" / "pages.json").read_text())
    page = next(p for p in pages if p["row_index"] == 13)
    assert page["latex_pdf_url"] == "latex/0013.pdf" and (web / "latex" / "0013.pdf").exists()
    assert page["image_url"] is None
    assert (web / "crops" / "e0013-01.png").exists()
