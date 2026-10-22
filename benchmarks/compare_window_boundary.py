"""Boundary burst comparison between Fixed Window Counter and Sliding Window Log.

Demonstrates the classic 'Window Boundary Problem':
Given a limit of 5 requests per 10-second window:
- 5 requests are sent at the end of Window 1 (e.g. t = 8.0, 8.5, 9.0, 9.5, 9.9)
- 5 requests are sent at the start of Window 2 (e.g. t = 10.1, 10.2, 10.3, 10.4, 10.5)

In any 10-second rolling interval spanning t=8.0 to t=11.0, 10 requests occur:
- Fixed Window Counter ALLOWS ALL 10 requests (2x over the limit!) because it resets at t=10.0.
- Sliding Window Log ALLOWS 5 and BLOCKS the remaining 5, maintaining strict rate integrity.
"""

import sys
from pathlib import Path
from unittest import mock

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.algorithms.fixed_window import FixedWindowCounter
from src.algorithms.sliding_window_log import SlidingWindowLog


def simulate_burst_scenario():
    limit = 5
    window_seconds = 10

    fixed_limiter = FixedWindowCounter(limit=limit, window_seconds=window_seconds)
    sliding_limiter = SlidingWindowLog(limit=limit, window_seconds=window_seconds)

    # Simulated timestamps:
    # 5 requests at the end of the first 10s window (current_window = 0)
    # 5 requests at the beginning of the second 10s window (current_window = 1)
    timestamps = [
        # Window 1 (t in [0, 10)):
        8.0,
        8.5,
        9.0,
        9.5,
        9.9,
        # Window 2 (t in [10, 20)):
        10.1,
        10.2,
        10.3,
        10.4,
        10.5,
    ]

    print("=======================================================================")
    print("      RateFortress: Window Boundary Burst Phenomenon Demonstration     ")
    print(f"      Configuration: Limit = {limit} reqs / {window_seconds}s window")
    print("=======================================================================\n")
    print(
        f"{'Request':<8} | {'Timestamp':<10} | {'Fixed Window':<15} | {'Sliding Window Log':<18}"
    )
    print("-" * 65)

    fixed_results = []
    sliding_results = []

    user_id = "target_user"

    for i, t in enumerate(timestamps, start=1):
        with mock.patch("time.time", return_value=t):
            fw_res = fixed_limiter.is_allowed(user_id)
            sw_res = sliding_limiter.is_allowed(user_id)

            fixed_results.append(fw_res)
            sliding_results.append(sw_res)

            fw_status = "ALLOWED (✓)" if fw_res else "BLOCKED (✗)"
            sw_status = "ALLOWED (✓)" if sw_res else "BLOCKED (✗)"

            print(f"#{i:<7} | t={t:<8.1f} | {fw_status:<15} | {sw_status:<18}")

    print("\n" + "=" * 65)
    print("Summary:")
    print(
        f"  Fixed Window Counter Allowed   : {sum(fixed_results)} / {len(timestamps)} requests (BURST LEAK DETECTED: 2x limit)"
    )
    print(
        f"  Sliding Window Log Allowed     : {sum(sliding_results)} / {len(timestamps)} requests (STRICT RATE ENFORCED)"
    )
    print("=======================================================================")


if __name__ == "__main__":
    simulate_burst_scenario()
