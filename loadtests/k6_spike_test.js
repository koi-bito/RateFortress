import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: __ENV.SPIKE_STAGE_1 || "10s", target: 10 },   // baseline
    { duration: __ENV.SPIKE_STAGE_2 || "5s", target: 1500 },  // sudden aggressive spike
    { duration: __ENV.SPIKE_STAGE_3 || "20s", target: 1500 }, // hold at peak load
    { duration: __ENV.SPIKE_STAGE_4 || "10s", target: 10 },   // drop back to baseline
    { duration: __ENV.SPIKE_STAGE_5 || "10s", target: 10 },   // recover & observe baseline
  ],
  thresholds: {
    checks: ["rate>0.95"],
  },
};

export default function () {
  const res = http.get("http://127.0.0.1:8000/api/test", {
    headers: { "X-API-Key": "key_free_abc" },
  });
  check(res, {
    "status is 200 or 429": (r) => r.status === 200 || r.status === 429,
  });
  sleep(0.1);
}
