import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

export const options = {
  vus: 20,
  duration: '15s',
};

const BASE = __ENV.BASE_URL || 'http://localhost:8000';

export default function () {
  const eventId = uuidv4();
  const payload = JSON.stringify({
    event_id: eventId,
    call_id: `k6-${uuidv4()}`,
    type: 'ringing',
    metadata: {},
  });
  const res = http.post(`${BASE}/webhooks/provider/mock_a`, payload, {
    headers: { 'Content-Type': 'application/json' },
  });
  check(res, { 'status 200': (r) => r.status === 200 });
  // duplicate
  const res2 = http.post(`${BASE}/webhooks/provider/mock_a`, payload, {
    headers: { 'Content-Type': 'application/json' },
  });
  check(res2, { 'dup 200': (r) => r.status === 200 });
  sleep(0.05);
}
