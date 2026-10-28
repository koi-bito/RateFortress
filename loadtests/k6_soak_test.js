import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: 120,
  duration: "30s",
};

export default function () {
  const res = http.get("http://127.0.0.1:8000/api/test", {
    headers: { "X-API-Key": "key_paid_xyz" },
  });
  check(res, {
    "status is 200 or 429": (r) => r.status === 200 || r.status === 429,
  });
  sleep(0.1);
}
