"""Translation of src/reconnecting-socket.ts with a fake network and clock."""

import asyncio
import json

import pytest

from tests.fakes import FakeClock, FakeRawSocketFactory, until


@pytest.mark.contract
@pytest.mark.asyncio
async def test_connect_json_messages_and_send(target):
    module = target("reconnecting_socket")
    factory = FakeRawSocketFactory()
    socket = module.ReconnectingSocket("wss://example.test/callsRtc", socket_factory=factory)
    events = []
    socket.addEventListener("connect", lambda event: events.append("connect"))
    socket.addEventListener("message", lambda event: events.append(event.detail))

    await until(lambda: len(factory.sockets) == 1)
    raw = factory.sockets[0]
    raw.feed("not json")
    raw.feed('{"type":"state","state":{"state":"idle"}}')
    await until(lambda: len(events) == 2)
    await socket.send({"type": "offer", "offer": {"type": "offer", "sdp": "v=0"}})

    assert events == ["connect", {"type": "state", "state": {"state": "idle"}}]
    assert json.loads(raw.sent[0]) == {"type": "offer", "offer": {"type": "offer", "sdp": "v=0"}}
    await socket.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_send_before_connect_raises_without_queueing(target):
    module = target("reconnecting_socket")
    gate = asyncio.Event()
    factory = FakeRawSocketFactory()

    async def blocked_factory(url):
        await gate.wait()
        return await factory(url)

    socket = module.ReconnectingSocket("wss://example.test", socket_factory=blocked_factory)
    with pytest.raises(Exception, match="ReconnectingSocket is not connected"):
        await socket.send({"type": "stop"})
    gate.set()
    await until(lambda: len(factory.sockets) == 1)
    await socket.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_successful_reconnect_starts_backoff_again_at_500ms(target):
    module = target("reconnecting_socket")
    factory = FakeRawSocketFactory()
    clock = FakeClock()
    socket = module.ReconnectingSocket(
        "wss://example.test", socket_factory=factory, sleep=clock.sleep,
    )
    await until(lambda: len(factory.sockets) == 1)

    for index in range(3):
        factory.sockets[index].disconnect(1006, "network lost")
        await until(lambda: len(clock.delays) == index + 1)
        assert clock.delays[-1] == 0.5
        clock.advance()
        await until(lambda: len(factory.sockets) == index + 2)

    await socket.close()


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_consecutive_failed_connects_double_backoff_up_to_10_seconds(target):
    module = target("reconnecting_socket")
    clock = FakeClock()
    attempts = []

    async def failing_factory(url):
        attempts.append(url)
        raise OSError("network unavailable")

    socket = module.ReconnectingSocket(
        "wss://example.test", socket_factory=failing_factory, sleep=clock.sleep,
    )
    for index, delay in enumerate([0.5, 1, 2, 4, 8, 10, 10]):
        await until(lambda: len(clock.delays) == index + 1)
        assert clock.delays[-1] == delay
        clock.advance()
    await socket.close()


@pytest.mark.contract
@pytest.mark.parametrize("code", [4000, 4500, 4999])
@pytest.mark.asyncio
async def test_server_refusal_stops_reconnect(target, code):
    module = target("reconnecting_socket")
    factory = FakeRawSocketFactory()
    clock = FakeClock()
    socket = module.ReconnectingSocket(
        "wss://example.test", socket_factory=factory, sleep=clock.sleep,
    )
    details = []
    socket.addEventListener("disconnect", lambda event: details.append(event.detail))
    await until(lambda: len(factory.sockets) == 1)
    factory.sockets[0].disconnect(code, "calls unavailable")
    await until(lambda: len(details) == 1)

    assert details[0] == {"reason": "calls unavailable", "code": code, "permanent": True}
    assert socket.refused is True
    assert clock.delays == []
    await socket.close()


@pytest.mark.contract
@pytest.mark.parametrize("code", [3999, 5000])
@pytest.mark.asyncio
async def test_codes_outside_refusal_range_do_retry(target, code):
    module = target("reconnecting_socket")
    factory = FakeRawSocketFactory()
    clock = FakeClock()
    socket = module.ReconnectingSocket(
        "wss://example.test", socket_factory=factory, sleep=clock.sleep,
    )
    await until(lambda: len(factory.sockets) == 1)
    factory.sockets[0].disconnect(code)
    await until(lambda: bool(clock.delays))
    assert clock.delays == [0.5]
    assert socket.refused is False
    await socket.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_explicit_close_cancels_reconnect_without_disconnect_event(target):
    module = target("reconnecting_socket")
    factory = FakeRawSocketFactory()
    clock = FakeClock()
    socket = module.ReconnectingSocket(
        "wss://example.test", socket_factory=factory, sleep=clock.sleep,
    )
    details = []
    socket.addEventListener("disconnect", lambda event: details.append(event.detail))
    await until(lambda: len(factory.sockets) == 1)
    await socket.close()
    assert factory.sockets[0].closed is True
    assert clock.delays == []
    assert details == []


@pytest.mark.contract
@pytest.mark.asyncio
async def test_empty_close_reason_gets_default_text(target):
    module = target("reconnecting_socket")
    factory = FakeRawSocketFactory()
    clock = FakeClock()
    socket = module.ReconnectingSocket(
        "wss://example.test", socket_factory=factory, sleep=clock.sleep,
    )
    details = []
    socket.addEventListener("disconnect", lambda event: details.append(event.detail))
    await until(lambda: len(factory.sockets) == 1)
    factory.sockets[0].disconnect(1006, "")
    await until(lambda: len(details) == 1)
    assert details[0]["reason"] == "connection closed"
    await socket.close()
