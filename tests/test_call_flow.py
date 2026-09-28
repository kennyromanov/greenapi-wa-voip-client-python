"""Cross-module call stories based on the vanilla and React examples."""

import asyncio

import pytest

from tests.fakes import FakeAudioFactory, FakeBridgeFactory, FakeRest, FakeSocket, until


@pytest.mark.contract
@pytest.mark.asyncio
async def test_outbound_dial_precedes_offer_and_server_idle_ends_call(target, monkeypatch):
    client_module = target("green_api_voip_client")
    connection_module = target("calls_connection")
    timeline = []

    class TimelineRest(FakeRest):
        async def post(self, method, body=None):
            timeline.append(("REST", method))
            await super().post(method, body)

    class TimelineSocket(FakeSocket):
        async def send(self, frame):
            timeline.append(("WS", frame["type"]))
            await super().send(frame)

    rest = TimelineRest()
    socket = TimelineSocket()
    bridges = FakeBridgeFactory()
    audio = FakeAudioFactory()
    monkeypatch.setattr(client_module, "GreenApiRestClient", lambda options: rest)
    monkeypatch.setattr(
        client_module,
        "CallsConnection",
        lambda value: connection_module.CallsConnection(
            value, socket=socket, bridge_factory=bridges, audio_factory=audio,
        ),
    )
    client = client_module.GreenApiVoipClient({
        "idInstance": "123", "apiTokenInstance": "secret", "apiUrl": "https://example.test",
    })
    calls = client.connectCalls()
    ended = []
    calls.addEventListener("end-call", lambda event: ended.append(event.detail))
    await socket.receive({"type": "state", "state": {"state": "idle"}})

    await client.dial("79991234567")
    task = asyncio.create_task(calls.startAudioBridge())
    await until(lambda: any(item["type"] == "offer" for item in socket.sent))
    assert timeline[:2] == [("REST", "callsDial"), ("WS", "offer")]
    await socket.receive({"type": "answer", "answer": {"type": "answer", "sdp": "v=0"}})
    await task
    await socket.receive({"type": "state", "state": {"state": "on-call"}})
    await socket.receive({"type": "state", "state": {"state": "idle", "reason": "hangup"}})

    assert ended == [{"reason": "call-ended", "cause": "hangup"}]
    assert timeline[-1] == ("WS", "stop")
    assert audio.streams[0].track.stopped is True
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_incoming_accept_uses_rest_before_bridge(target, monkeypatch):
    client_module = target("green_api_voip_client")
    connection_module = target("calls_connection")
    timeline = []

    class TimelineRest(FakeRest):
        async def post(self, method, body=None):
            timeline.append(("REST", method))
            await super().post(method, body)

    class TimelineSocket(FakeSocket):
        async def send(self, frame):
            timeline.append(("WS", frame["type"]))
            await super().send(frame)

    rest, socket = TimelineRest(), TimelineSocket()
    bridges, audio = FakeBridgeFactory(), FakeAudioFactory()
    monkeypatch.setattr(client_module, "GreenApiRestClient", lambda options: rest)
    monkeypatch.setattr(
        client_module,
        "CallsConnection",
        lambda value: connection_module.CallsConnection(
            value, socket=socket, bridge_factory=bridges, audio_factory=audio,
        ),
    )
    client = client_module.GreenApiVoipClient({
        "idInstance": "123", "apiTokenInstance": "secret", "apiUrl": "https://example.test",
    })
    calls = client.connectCalls()
    incoming = []
    calls.addEventListener("incoming-call", lambda event: incoming.append(event.detail.wid))
    await socket.receive({
        "type": "state",
        "state": {"state": "inc-call", "info": {"id": "c1", "wid": "100@lid", "name": "Ada"}},
    })
    assert incoming == ["100@lid"]

    await client.accept()
    task = asyncio.create_task(calls.startAudioBridge())
    await until(lambda: any(item["type"] == "offer" for item in socket.sent))
    assert timeline[:2] == [("REST", "callsAccept"), ("WS", "offer")]
    assert socket.sent[0]["type"] == "offer"
    await socket.receive({"type": "answer", "answer": {"type": "answer", "sdp": "v=0"}})
    await task
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_reject_does_not_create_media_bridge(target, monkeypatch):
    client_module = target("green_api_voip_client")
    rest = FakeRest()
    monkeypatch.setattr(client_module, "GreenApiRestClient", lambda options: rest)
    client = client_module.GreenApiVoipClient({
        "idInstance": "123", "apiTokenInstance": "secret", "apiUrl": "https://example.test",
    })
    await client.reject()
    assert rest.calls == [("POST", "callsReject", None)]
