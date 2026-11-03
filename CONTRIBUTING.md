# Contributing to RateFortress

Thank you for your interest in contributing to RateFortress! We welcome contributions, bug fixes, algorithmic extensions, and documentation improvements.

---

## Architecture & Code Structure

RateFortress enforces a clean separation of concerns:

- `src/algorithms/`: Pure rate limiting algorithm logic. Each algorithm implements the standard interface:
  ```python
  class RateLimiter:
      def is_allowed(self, client_id: str) -> bool: ...
      def get_remaining(self, client_id: str) -> int: ...
      def get_reset_time(self, client_id: str) -> float: ...
  ```
- `src/storage/`: Redis client connection management and atomic Lua scripts (`EVALSHA`) for zero race-condition execution.
- `src/middleware/`: FastAPI ASGI middleware (`RateLimitMiddleware`), endpoint prefix matching (`EndpointTrie`), circuit breaking (`CircuitBreaker`), and API key lifecycle management (`APIKeyManager`).
- `src/api/`: FastAPI route handlers, admin REST API, and comparison engines.
- `tests/`: Automated pytest suite covering unit, concurrency, integration, and failure modes.

---

## How to Propose a New Algorithm

1. **Implement Core Algorithm:**
   Create your algorithm class in `src/algorithms/<your_algorithm>.py`. Ensure it implements `is_allowed(client_id: str) -> bool`.
2. **Add Atomic Redis Storage Backend (Optional):**
   If introducing a distributed variant, write an atomic Lua script in `src/algorithms/` to eliminate GET-then-SET race conditions, accompanied by a Python wrapper using `EVALSHA`.
3. **Register in Middleware Configuration:**
   Add the algorithm identifier to `src/middleware/config.py` and the factory switch in `src/middleware/rate_limit_middleware.py`.
4. **Write Tests:**
   Add unit and boundary tests in `tests/test_<your_algorithm>.py` asserting limit - 1, limit, limit + 1, and rollover behavior.

---

## Development Setup

```bash
# 1. Clone repository
git clone https://github.com/koi-bito/RateFortress.git
cd RateFortress

# 2. Create isolated virtual environment
python -m venv ratefortress_env
source ratefortress_env/bin/activate  # Windows: ratefortress_env\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run full test suite
pytest -v
```

---

## Code Quality Standards

- Maintain documentation integrity: all public classes and functions should include descriptive docstrings.
- Zero test regressions: all 200+ existing tests must pass before opening a Pull Request.
- Concurrency verification: changes touching stateful storage or rate checks must include multi-threaded concurrency assertions.

