"""Tests for Week 15: Documentation, Architecture Diagram, Demo Script, and Interview Defense."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_architecture_diagram_exists_and_valid():
    """Validates docs/architecture.svg exists and renders key system components."""
    svg_path = PROJECT_ROOT / "docs" / "architecture.svg"
    assert svg_path.exists(), "docs/architecture.svg must exist"

    content = svg_path.read_text(encoding="utf-8")
    assert "<svg" in content
    assert "</svg>" in content
    assert "FastAPI Gateway" in content
    assert "Endpoint Trie" in content
    assert "CircuitBreaker" in content
    assert "Redis 7" in content
    assert "Prometheus" in content
    assert "Grafana" in content


def test_readme_portfolio_quality():
    """Validates README.md structure, badges, benchmark table, and resume bullets."""
    readme_path = PROJECT_ROOT / "README.md"
    assert readme_path.exists(), "README.md must exist"

    content = readme_path.read_text(encoding="utf-8")
    assert "docs/architecture.svg" in content
    assert "Empirical Benchmarks & Performance Matrix" in content
    assert "Fixed Window Counter" in content
    assert "Sliding Window Log" in content
    assert "Sliding Window Counter" in content
    assert "Token Bucket" in content
    assert "Leaky Bucket" in content
    assert "Resume Bullet Points" in content
    assert "docker-compose up -d" in content


def test_demo_script_and_walkthrough():
    """Validates docs/demo_script_and_walkthrough.md structure and content."""
    demo_path = PROJECT_ROOT / "docs" / "demo_script_and_walkthrough.md"
    assert demo_path.exists(), "docs/demo_script_and_walkthrough.md must exist"

    content = demo_path.read_text(encoding="utf-8")
    assert "Video Demo Script" in content
    assert "0:00" in content
    assert "/compare" in content
    assert "Grafana" in content
    assert "LinkedIn & Technical Community Launch Post" in content


def test_interview_prep_guide():
    """Validates docs/interview_prep_and_defense.md covers system design defense."""
    guide_path = PROJECT_ROOT / "docs" / "interview_prep_and_defense.md"
    assert guide_path.exists(), "docs/interview_prep_and_defense.md must exist"

    content = guide_path.read_text(encoding="utf-8")
    assert "60-Second Elevator Pitch" in content
    assert "concurrency race conditions" in content.lower()
    assert "Circuit Breaker" in content
    assert "Token Bucket" in content
    assert "Sliding Window Counter" in content
    assert "multi-region" in content.lower() or "consistent hashing" in content.lower()

