# RateFortress — Adversary Simulation & Abuse Report

These are my notes from running attack simulation scripts against RateFortress to test how it handles header spoofing, key rotation, and bot traffic.

---

## 1. Attack Vectors Evaluated

### Vector 1: X-Forwarded-For Header Spoofing
An attacker injects fake IP addresses in HTTP request headers:
`X-Forwarded-For: 185.199.108.153`

Before Day 103, my middleware split X-Forwarded-For and trusted the first IP. In my test script, sending 30 requests with randomized headers resulted in all 30 requests passing through, completely bypassing the 10-request IP limit.

To fix this, I wrote `src/middleware/trusted_proxy.py` on Day 103. The middleware only reads X-Forwarded-For if the immediate connection comes from a known trusted proxy CIDR. It then walks the chain from right to left to find the first untrusted client IP. Retesting with the fix blocked 20 of the 30 requests, anchoring limits to the socket IP.

---

### Vector 2: Free-Tier Account Cycling
An attacker scripts the creation of disposable accounts and rotates API keys every few requests.

Because rate limiters isolate quotas per key, account cycling bots easily stay under per-key limits while flooding backend services.

On Day 104, I added `BehavioralShield` in `src/middleware/behavioral_shield.py`. It tracks inter-arrival timing variance: bots usually dispatch requests with near-zero timing jitter (coefficient of variation under 0.05). When detected, the shield temporarily downgrades the client to a 0.2x multiplier rather than hard-blocking, avoiding false positives on real users.

---

### Vector 3: Distributed Residential Proxy Networks
Attackers route requests through residential proxy pools where millions of consumer IP addresses each send only one or two requests.

This neutralizes IP-based rate limiting because every request comes from a different IP address.

An application-layer rate limiter cannot solve distributed proxy pools alone. Stopping them requires edge WAF rules, ASN filtering to block known hosting providers, and requiring verified payment or phone identities before issuing API keys.

---

## 2. Before & After Summary

| Attack Vector | Pre-Remediation Outcome | Post-Remediation Outcome | Defense Mechanism | Residual Risk Level |
| :--- | :--- | :--- | :--- | :--- |
| Vanilla IP Burst | 10 Allowed / 20 Blocked | 10 Allowed / 20 Blocked | Token Bucket / GCRA | Negligible |
| X-Forwarded-For Spoofing | 30 Allowed / 0 Blocked (66.7% bypass) | 10 Allowed / 20 Blocked (0.0% bypass) | Trusted Proxy CIDR & Reverse Traversal | Negligible |
| Scripted Loop Timing | Permitted full quota | Flagged (CV < 0.05), downgraded to 0.2x | BehavioralShield timing variance | Low |
| Distributed Proxy Pools | Bypasses IP limits | Throttled if API keys required; IP bypass remains | WAF / TLS fingerprinting (External) | Medium (Requires Edge WAF) |
| Free-Trial Key Cycling | Bypasses per-key limits | Mitigated by signup throttling & behavioral scoring | Payment auth / Turnstile (External) | Medium (Requires Auth Gate) |

---

## 3. Takeaways

1. Never trust HTTP headers from untrusted networks: headers like X-Forwarded-For are client-controlled strings unless verified against known private proxy subnets.
2. Prefer graceful tier degradation over immediate hard drops: when heuristics detect automation, temporarily constraining quota protects real users from false-positive lockouts while blunting bot spikes.
3. Use defense in depth: an effective architecture pairs edge WAF rules for volumetric floods with application rate limiters for per-tenant business logic.
