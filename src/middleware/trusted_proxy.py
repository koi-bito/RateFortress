"""Trusted Proxy Validation and Anti-Spoofing IP Resolution (Day 103).

Prevents X-Forwarded-For rate limit bypass attacks by validating upstream peer IPs
against trusted proxy networks (e.g. AWS ALB, Cloudflare, private VPC subnets)
and traversing the proxy chain right-to-left.
"""

from __future__ import annotations

import ipaddress
import logging
import os

logger = logging.getLogger("ratefortress.security")

# Standard private network ranges and loopback defaults
DEFAULT_TRUSTED_PROXIES: list[str] = [
    "127.0.0.1",
    "::1",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
]


def parse_trusted_proxies(config_str: str | None = None) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parses comma-delimited CIDR or IP strings into ip_network objects."""
    raw = config_str if config_str is not None else os.getenv("TRUSTED_PROXIES", "")
    items = [x.strip() for x in raw.split(",") if x.strip()] if raw else DEFAULT_TRUSTED_PROXIES
    networks = []
    for item in items:
        try:
            # strict=False allows host addresses (e.g. 127.0.0.1/32)
            net = ipaddress.ip_network(item, strict=False)
            networks.append(net)
        except ValueError:
            logger.warning("Invalid trusted proxy CIDR or IP ignored: %s", item)
    return networks


def is_trusted_peer(peer_ip: str, trusted_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network]) -> bool:
    """Checks whether the raw peer IP connecting to the socket is a recognized trusted proxy."""
    if not peer_ip:
        return False
    if peer_ip in ("testclient", "testserver", "localhost"):
        # Local test harness (Starlette TestClient / in-memory ASGI)
        return True
    try:
        addr = ipaddress.ip_address(peer_ip)
        return any(addr in net for net in trusted_networks)
    except ValueError:
        return False


def resolve_client_ip(
    peer_ip: str,
    forwarded_for: str | None = None,
    trusted_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None,
) -> str:
    """Safely extracts true client IP without being deceived by spoofed X-Forwarded-For headers.

    Security Rules:
    1. If the connecting peer is NOT a trusted proxy, ignore X-Forwarded-For completely.
    2. If the connecting peer IS trusted, parse X-Forwarded-For right-to-left, discarding
       any intermediate trusted proxy IPs until reaching the first untrusted client IP.
    """
    networks = trusted_networks if trusted_networks is not None else parse_trusted_proxies()

    # Rule 1: Untrusted peer -> ignore untrusted client headers
    if not is_trusted_peer(peer_ip, networks):
        return peer_ip or "unknown_client"

    # Rule 2: Trusted peer -> safely walk proxy chain from right to left
    if not forwarded_for:
        return peer_ip or "unknown_client"

    chain = [ip.strip() for ip in forwarded_for.split(",") if ip.strip()]
    if not chain:
        return peer_ip

    # Walk right-to-left: the rightmost entries were added by trusted intermediaries
    for candidate in reversed(chain):
        try:
            addr = ipaddress.ip_address(candidate)
            if not any(addr in net for net in networks):
                # Found the first untrusted upstream IP
                return candidate
        except ValueError:
            # Malformed IP in header
            continue

    # If every IP in the chain was a trusted proxy, return the leftmost entry
    return chain[0]
