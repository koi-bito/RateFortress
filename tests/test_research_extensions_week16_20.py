"""Validation tests for Weeks 16–20 Research Layer & Advanced Extensions."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_research_publications_exist():
    """Validates existence and key sections of technical publications."""
    article = PROJECT_ROOT / "docs" / "comparative_benchmark_article.md"
    assert article.exists()
    content = article.read_text(encoding="utf-8")
    assert "Which Rate Limiting Algorithm Should You Actually Use" in content
    assert "GCRA" in content
    assert "Token Bucket" in content
    assert "Sliding Window Counter" in content

    devto = PROJECT_ROOT / "docs" / "devto_article.md"
    assert devto.exists()

    showcase = PROJECT_ROOT / "docs" / "community_showcase_and_defense.md"
    assert showcase.exists()
    sc_content = showcase.read_text(encoding="utf-8")
    assert "Show HN" in sc_content

    followup = PROJECT_ROOT / "docs" / "lessons_learned_followup.md"
    assert followup.exists()


def test_scaling_and_cluster_docs():
    """Validates docs/scaling.md covers hash slots, Lua CROSSSLOT constraints, and multi-region."""
    scaling = PROJECT_ROOT / "docs" / "scaling.md"
    assert scaling.exists()
    content = scaling.read_text(encoding="utf-8")
    assert "16,384" in content or "16384" in content
    assert "CROSSSLOT" in content
    assert "Multi-Region" in content


def test_package_configuration():
    """Validates pyproject.toml configuration and packaging guide."""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    assert pyproject.exists()
    content = pyproject.read_text(encoding="utf-8")
    assert 'name = "ratefortress"' in content

    guide = PROJECT_ROOT / "docs" / "package_guide.md"
    assert guide.exists()


def test_capstone_artifacts():
    """Validates peer review and capstone walkthrough script."""
    review = PROJECT_ROOT / "docs" / "peer_review.md"
    assert review.exists()

    script = PROJECT_ROOT / "docs" / "capstone_deep_dive_script.md"
    assert script.exists()
    content = script.read_text(encoding="utf-8")
    assert "Capstone Deep Dive" in content

