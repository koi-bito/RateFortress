"""Tests for EndpointTrie prefix matching."""

from src.middleware.config import EndpointRule
from src.middleware.endpoint_trie import EndpointTrie


def test_root_and_default_rule():
    default_rule = EndpointRule(limit=100, window_seconds=60)
    trie = EndpointTrie(default_rule=default_rule)

    assert trie.match("/").limit == 100
    assert trie.match("/unknown/path").limit == 100


def test_exact_and_prefix_inheritance():
    trie = EndpointTrie()

    admin_rule = EndpointRule(limit=20, window_seconds=60, algorithm="fixed_window")
    trie.insert("/api/admin", admin_rule)

    # Exact match
    assert trie.match("/api/admin") == admin_rule

    # Nested children inherit parent rule
    assert trie.match("/api/admin/users") == admin_rule
    assert trie.match("/api/admin/settings") == admin_rule
    assert trie.match("/api/admin/users/42/roles") == admin_rule


def test_specific_child_overrides_parent():
    trie = EndpointTrie()

    parent_rule = EndpointRule(limit=50, window_seconds=60)
    strict_rule = EndpointRule(limit=5, window_seconds=60)

    trie.insert("/api/billing", parent_rule)
    trie.insert("/api/billing/charge", strict_rule)

    # General billing uses parent rule
    assert trie.match("/api/billing/invoices") == parent_rule

    # Sensitive charge route uses strict child rule
    assert trie.match("/api/billing/charge") == strict_rule
    assert trie.match("/api/billing/charge/confirm") == strict_rule


def test_wildcard_matching():
    trie = EndpointTrie()
    wildcard_rule = EndpointRule(limit=10, window_seconds=30)
    trie.insert("/api/v1/*", wildcard_rule)

    assert trie.match("/api/v1/anything") == wildcard_rule
