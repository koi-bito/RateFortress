# RateFortress — Red Team Adversary & Abuse Simulation Report

**Executive Summary:** An empirical adversarial audit evaluating real-world rate limiting bypass techniques against RateFortress, documenting attack vectors, empirical results before and after hardening, and residual infrastructure risks.

---

## 1. Adversarial Attack Vectors Evaluated

### Vector 1: `X-Forwarded-For` Header Spoofing
- **Mechanism:** An attacker injects randomized IP addresses in HTTP request headers:
  `X-Forwarded-For: 185.199.108.153`
- **Pre-Fix Vulnerability:** In naive implementations (and RateFortress before Day 103), the middleware blindly split `X-Forwarded-For` and used the first IP.
- **Empirical Measurement Before Fix:**
  - Standard Single-IP Limit: 10 requests allowed, 20 blocked (0% leak).
  - Spoofed `X-Forwarded-For`: **30 / 30 requests permitted** (a **200% quota leak / 66.7% bypass rate**).
- **Remediation Implemented (Day 103):**
  - Built `src/middleware/trusted_proxy.py`: Only requests whose raw OS socket peer (`request.client.host`) resides within a configured `TRUSTED_PROXIES` CIDR network (e.g., VPC private load balancers, Cloudflare IP ranges) are permitted to supply `X-Forwarded-For`.
  - Implemented reverse-chain traversal: Walks `X-Forwarded-For` right-to-left, discarding intermediate trusted proxies and isolating the first untrusted upstream IP.
- **Empirical Measurement After Fix:**
  - Spoofed `X-Forwarded-For` from untrusted client: **10 allowed, 20 blocked** (Bypass Rate: **0.0%**). All spoofed attempts are securely anchored to the raw peer socket IP.

---

### Vector 2: Free-Tier Account Cycling ("Sybil Attack")
- **Mechanism:** Rather than hammering a single API key or IP, an attacker scripts the automatic creation of thousands of disposable free accounts (e.g. using temporary email services or automated signup scripts) and rotates API keys every $N$ requests.
- **Vulnerability:** Application-layer rate limiters inherently isolate state by client identifier (`user_id` or `api_key`). Because each key is legitimate and isolated, a distributed account-cycling bot easily stays under per-key limits while flooding backend services.
- **Defense-in-Depth Layer (Day 104):**
  - Implemented `BehavioralShield` (`src/middleware/behavioral_shield.py`).
  - Analyzes inter-arrival timing variance: Bots typically dispatch requests with rigid, near-zero timing jitter (Coefficient of Variation $CV < 0.05$).
  - Evaluates account age vs. immediate request velocity.
  - Dynamically penalizes suspicious automation, downgrading clients from full quota to a restricted tier (0.2x multiplier) rather than a hard block, and logging high-risk signals for human audit.

---

### Vector 3: Distributed Residential Proxy Pools
- **Mechanism:** Modern credential-stuffing and scraping operations route requests through residential proxy networks (e.g. BrightData, Oxylabs, Tor, or mobile botnets) where millions of real, distinct consumer IP addresses each send only 1 or 2 requests.
- **System Impact:** Completely neutralizes IP-based rate limiting because every single request originates from a genuinely different IP address.
- **Honest Residual Risk Assessment:**
  - No application-level rate limiter running on a backend server can defeat distributed residential proxy networks alone.
  - Mitigating residential proxy pools requires a multi-layered edge security perimeter:
    1. **Edge Web Application Firewall (WAF) / CDN (e.g. Cloudflare / AWS CloudFront):** IP reputation databases, ASN blocking (flagging known hosting provider ASNs like Hetzner/OVH/DigitalOcean), and JA3/JA4 TLS fingerprinting.
    2. **Proof-of-Work / Managed Challenges:** Cloudflare Turnstile or invisible CAPTCHAs before free-tier API credentials can be generated.
    3. **Credit Card or Phone Verification:** Enforcing verified billing identities to prevent unthrottled free-trial farming.

---

## 2. Red Team Before & After Summary Matrix

| Attack Vector | Pre-Remediation Outcome | Post-Remediation Outcome | Defense Mechanism | Residual Risk Level |
| :--- | :--- | :--- | :--- | :--- |
| **Vanilla IP Burst** | 10 Allowed / 20 Blocked | 10 Allowed / 20 Blocked | Token Bucket / GCRA | Negligible |
| **X-Forwarded-For Spoofing** | **30 Allowed / 0 Blocked** (66.7% bypass) | **10 Allowed / 20 Blocked** (0.0% bypass) | Trusted Proxy CIDR & Reverse Traversal | Negligible |
| **Scripted Loop Timing** | Permitted full quota | Flagged ($CV < 0.05$), downgraded to 0.2x | BehavioralShield timing variance | Low |
| **Distributed Proxy Pools** | Bypasses IP limits | Throttled if API keys required; IP bypass remains | WAF / TLS fingerprinting (External) | Medium (Requires Edge WAF) |
| **Free-Trial Key Cycling** | Bypasses per-key limits | Mitigated by signup throttling & behavioral scoring | Payment auth / Turnstile (External) | Medium (Requires Auth Gate) |

---

## 3. Key Architectural Takeaways

1. **Never trust HTTP headers from untrusted networks:** Headers like `X-Forwarded-For` are client-controlled strings unless verified against private VPC or edge proxy subnets.
2. **Prefer graceful tier degradation over immediate hard drops:** When behavioral heuristics detect automation, temporarily constraining quota protects legitimate power users from false-positive lockouts while neutralizing bot swarms.
3. **Defense in Depth is an operational requirement:** A robust systems architecture combines edge WAFs, application-level distributed rate limiters (RateFortress), and verified identity lifecycles.

