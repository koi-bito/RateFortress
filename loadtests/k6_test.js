import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: __ENV.STAGE_1 || "15s", target: 100 },
    { duration: __ENV.STAGE_2 || "25s", target: 500 },
    { duration: __ENV.STAGE_3 || "10s", target: 0 },
  ],
  thresholds: {
    checks: ["rate>0.98"],
    http_req_duration: ["p(95)<1500"],
  },
};

export default function () {
  const res = http.get("http://127.0.0.1:8000/api/test", {
    headers: { "X-API-Key": "key_free_abc" },
  });
  check(res, {
    "status is 200 or 429": (r) => r.status === 200 || r.status === 429,
  });
  sleep(0.2);
}
