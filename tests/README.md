# Test-first contract

The Python implementation follows the TypeScript SDK. Most tests inject fake
network and media boundaries; `test_rtc_local.py` exercises two real aiortc
peers without a Green-API account.

## Origin labels

- `contract`: behavior present in `.docs/whatsapp-api-calls-client-js-master/src/`.
- `adaptation`: deliberate Python semantics or cleanup safety beyond the TS source.
- `integration`: future opt-in external-service checks; never required for unit CI.

The TS source is the contract for event names, REST methods, JSON frames, ordering,
reconnect delays, and call-state transitions. Do not turn an incidental source bug
into an undocumented public promise. The `adaptation` tests call out decisions such
as awaiting `close()` and settling pending negotiations on explicit close.

## Test seams reserved for implementation

The following keyword-only constructor arguments are internal injection points, not
new public exports:

- `GreenApiRestClient(options, transport=...)`: `transport.request(method, url,
  headers=None, json=MISSING)` returns a response with `status_code`, `text`, and
  optional `json()` behavior.
- `ReconnectingSocket(url, socket_factory=..., sleep=...)`: factory is awaitable and
  yields a WebSocket-like object with `recv()`, `send(text)`, `close()`; `sleep` is an
  awaitable taking seconds. Connection close exceptions expose `code` and `reason`.
- `CallsConnection(rest, socket=..., bridge_factory=..., audio_factory=...)`:
  a test socket has EventTarget-style listeners and async `send`/`close`; its
  `message` event has parsed JSON in `detail`. Bridge and audio fakes are in
  `tests/fakes.py`. The normal user path remains `client.connectCalls()`.
- `AiortcBridge(ice_servers, peer_factory=...)`: fake peer mirrors the small subset
  of aiortc required by the SDK; detailed RTC compatibility is outside these tests.
- `rtc.audio.AudioDevice(source_factory=..., sink_factory=...)`: local acquisition,
  remote-track attachment, and cleanup can be tested without hardware.

These seams keep the production flow readable. If implementation uses equivalent
constructor names, adjust only the fixture plumbing, not the asserted behavior.

## Test workflow

1. `python -m pytest -q`: run the contract, adaptation, and local RTC tests.
2. Keep `contract` and `adaptation` expectations distinguishable in reviews.
3. A live Green-API test must independently verify ICE, DTLS, RTP, and audio.

Fixtures in `tests/fixtures/calls_rtc/` contain synthetic identifiers. Real HAR,
SDP, tokens, phone numbers, TURN credentials, and media must never be checked in.
