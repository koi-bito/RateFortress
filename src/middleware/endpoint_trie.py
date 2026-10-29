"""Endpoint Trie for hierarchical route prefix matching.

Provides O(K) lookup where K is the number of path segments, rather than O(N * M)
regex or string scans over N routes. Enables inherited rate limit rules, e.g.
a rule on '/api/admin' automatically governs '/api/admin/users' and '/api/admin/settings'.
"""

from src.middleware.config import EndpointRule


class TrieNode:
    """A single node representing a URL path segment in the EndpointTrie."""

    def __init__(self):
        self.children: dict[str, TrieNode] = {}
        self.rule: EndpointRule | None = None
        self.pattern: str | None = None


class EndpointTrie:
    """Trie structure optimized for URL path segment prefix matching."""

    def __init__(self, default_rule: EndpointRule | None = None):
        self.root = TrieNode()
        self.default_rule = default_rule or EndpointRule(
            limit=100, window_seconds=60, algorithm="token_bucket"
        )
        self.root.rule = self.default_rule
        self.root.pattern = "default"

    def _split_path(self, path: str) -> list[str]:
        cleaned = path.strip("/")
        if not cleaned:
            return []
        return cleaned.split("/")

    def insert(self, path: str, rule: EndpointRule) -> None:
        """Inserts or updates a rate limiting rule at a given URL path.

        Args:
            path: Target route pattern (e.g. '/' or '/api/admin' or '/api/v1/auth').
            rule: EndpointRule configuration instance.
        """
        segments = self._split_path(path)
        node = self.root

        for segment in segments:
            if segment not in node.children:
                node.children[segment] = TrieNode()
            node = node.children[segment]

        node.rule = rule
        node.pattern = path

    def match_with_pattern(self, path: str) -> tuple[EndpointRule, str]:
        """Finds the most specific rule and its matched pattern for path.

        Returns:
            Tuple of (EndpointRule, matched_pattern).
        """
        segments = self._split_path(path)
        node = self.root
        best_rule = self.root.rule or self.default_rule
        best_pattern = self.root.pattern or "default"

        for segment in segments:
            # Check for exact segment match
            if segment in node.children:
                node = node.children[segment]
                if node.rule is not None:
                    best_rule = node.rule
                    best_pattern = node.pattern or path
            elif "*" in node.children:
                node = node.children["*"]
                if node.rule is not None:
                    best_rule = node.rule
                    best_pattern = node.pattern or path
            else:
                break

        return best_rule, best_pattern

    def match(self, path: str) -> EndpointRule:
        """Finds the most specific (longest-prefix) rule matching the given path.

        Falls back to ancestor rules or root default rule if no exact match exists.

        Args:
            path: Target HTTP request URL path.

        Returns:
            The most specific EndpointRule found.
        """
        rule, _ = self.match_with_pattern(path)
        return rule
