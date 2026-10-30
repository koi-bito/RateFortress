"""Validation tests for Week 22 System Design Capacity Planning and Math Invariants."""

import math
from pathlib import Path


def test_capacity_planning_doc_exists_and_consistent():
    """Validates that all Week 22 system design documents exist and contain required sections."""
    docs_dir = Path("docs")
    cap_doc = docs_dir / "capacity_planning.md"
    mock_single = docs_dir / "mock_interview_single_region.md"
    mock_multi = docs_dir / "mock_interview_multi_region.md"
    adr_doc = docs_dir / "ADR-001-algorithm-choice.md"

    for doc in (cap_doc, mock_single, mock_multi, adr_doc):
        assert doc.exists(), f"Expected {doc} to exist"
        content = doc.read_text(encoding="utf-8")
        assert len(content) > 1000, f"{doc} content too short"


def test_capacity_math_invariants():
    """Programmatically verifies the back-of-the-envelope capacity estimations."""
    peak_qps = 1_000_000
    active_keys = 10_000_000

    # 1. GCRA & Token Bucket memory estimations
    gcra_bytes_per_key = 124
    tb_bytes_per_key = 144
    swl_bytes_per_key = 96 + (100 * 72)  # 100 req/min at 72 bytes per ZSET entry

    gcra_total_gb = (active_keys * gcra_bytes_per_key) / (1024**3)
    tb_total_gb = (active_keys * tb_bytes_per_key) / (1024**3)
    swl_total_gb = (active_keys * swl_bytes_per_key) / (1024**3)

    # Invariants
    assert 1.1 < gcra_total_gb < 1.3  # ~1.15 - 1.25 GB
    assert 1.3 < tb_total_gb < 1.5  # ~1.34 - 1.45 GB
    assert 65.0 < swl_total_gb < 75.0  # ~68 GB (base without buffer)

    # SWL consumes > 45x more memory than Token Bucket
    assert swl_total_gb / tb_total_gb > 45.0

    # 2. Network bandwidth estimation
    bytes_per_transaction = 250
    total_bytes_per_sec = peak_qps * bytes_per_transaction
    bandwidth_gbps = (total_bytes_per_sec * 8) / 1_000_000_000
    assert 1.9 <= bandwidth_gbps <= 2.1  # Exactly 2.0 Gbps

    # 3. Redis node requirements
    node_capacity_ops = 50_000
    primary_shards_needed = math.ceil(peak_qps / node_capacity_ops)
    assert primary_shards_needed == 20
    total_nodes_with_replication = primary_shards_needed * 2
    assert total_nodes_with_replication == 40


def test_adr_contains_empirical_benchmark_evidence():
    """Ensures ADR-001 references our real benchmark figures."""
    adr_path = Path("docs") / "ADR-001-algorithm-choice.md"
    text = adr_path.read_text(encoding="utf-8")

    assert "3,303,492" in text  # GCRA Python throughput
    assert "2,169,380" in text  # Token Bucket Python throughput
    assert "6,695" in text  # GCRA Redis throughput
    assert "**Status:** Accepted" in text
