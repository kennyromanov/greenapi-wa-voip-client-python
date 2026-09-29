"""Ordering checks through the production WebSocket event dispatch path."""

import asyncio
import json

import pytest

from greenapi_wa_voip_client.calls_connection import CallsConnection
from greenapi_wa_voip_client.reconnecting_socket import ReconnectingSocket
from tests.fakes import FakeAudioFactory, FakeBridgeFactory, FakeRawSocketFactory, FakeRest, until


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_idle_finishes_before_next_incoming_call_with_slow_stop():
    factory = FakeRawSocketFactory()
    socket = ReconnectingSocket("wss://example.test/callsRtc", socket_factory=factory)
    calls = CallsConnection(
        FakeRest(), socket=socket,
        bridge_factory=FakeBridgeFactory(), audio_factory=FakeAudioFactory(),
    )
    events = []
    calls.addEventListener("state", lambda event: events.append(("state", event.detail.state)))
    calls.addEventListener("end-call", lambda event: events.append(("end-call", event.detail["reason"])))
    calls.addEventListener("incoming-call", lambda event: events.append(("incoming-call", event.detail.wid)))

    stop_started = asyncio.Event()
    release_stop = asyncio.Event()
    try:
        await until(lambda: bool(factory.sockets))
        raw = factory.sockets[0]
        original_send = raw.send

        async def slow_stop(text):
            if json.loads(text).get("type") == "stop":
                stop_started.set()
                await release_stop.wait()
            await original_send(text)

        raw.send = slow_stop
        raw.feed(json.dumps({"type": "state", "state": {"state": "on-call"}}))
        await until(lambda: calls.state is not None and calls.state.state == "on-call")
        bridge_task = asyncio.create_task(calls.startAudioBridge())
        await until(lambda: any(json.loads(item).get("type") == "offer" for item in raw.sent))
        raw.feed(json.dumps({"type": "answer", "answer": {"type": "answer", "sdp": "v=0"}}))
        await bridge_task

        raw.feed(json.dumps({"type": "state", "state": {"state": "idle", "reason": "hangup"}}))
        raw.feed(json.dumps({"type": "state", "state": {
            "state": "inc-call", "info": {"id": "next", "wid": "200@lid", "name": "Next"},
        }}))
        await asyncio.wait_for(stop_started.wait(), timeout=1)
        await asyncio.sleep(0)
        assert events == [("state", "on-call"), ("state", "idle")]

        release_stop.set()
        await until(lambda: len(events) == 5)
        assert events == [
            ("state", "on-call"), ("state", "idle"), ("end-call", "call-ended"),
            ("state", "inc-call"), ("incoming-call", "200@lid"),
        ]
    finally:
        release_stop.set()
        await calls.close()
