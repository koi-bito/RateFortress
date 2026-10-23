"""Verification script for Redis connectivity (Day 34).

Verifies setting and getting a key in Redis from Python, confirming both single-client
operations and multi-client shared state synchronization.
"""

import sys
from pathlib import Path

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage.redis_client import get_redis_client


def main():
    print("=== RateFortress Day 34: Redis Connectivity Check ===")

    # 1. Acquire Redis client
    client = get_redis_client()
    backend_type = type(client).__name__
    print(f"[*] Redis client initialized ({backend_type}).")

    # 2. Set and Get a key
    test_key = "ratefortress:test_key"
    test_value = "hello_distributed_world"

    client.set(test_key, test_value)
    read_val = client.get(test_key)
    print(f"[*] SET '{test_key}' -> '{test_value}'")
    print(f"[*] GET '{test_key}' -> '{read_val}'")
    assert read_val == test_value, f"Expected {test_value}, got {read_val}"

    # 3. Simulate multi-instance shared state
    client_b = get_redis_client()
    shared_read = client_b.get(test_key)
    print(f"[*] Secondary Client GET '{test_key}' -> '{shared_read}'")
    assert shared_read == test_value, "Secondary client failed to read shared state!"

    # 4. Clean up test key
    client.delete(test_key)
    print(f"[*] Cleaned up '{test_key}'.")
    print(
        "[+] Day 34 Checkpoint Passed: Set and get a key in Redis from Python successfully!"
    )


if __name__ == "__main__":
    main()
