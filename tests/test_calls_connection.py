"""Translation of src/calls-connection.ts using fake signaling and RTC boundaries."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests.fakes import FakeRest, FakeSocket, until


FIXTURES = Path(__file__).parent / "fixtures" / "calls_rtc"


def frame(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


async def started_bridge(harness):
    calls, socket, _, bridges, _ = harness
    task = asyncio.create_task(calls.startAudioBridge())
    await until(lambda: any(item["type"] == "offer" for item in socket.sent))
    assert len(bridges.bridges) == 1
    return task


@pytest.mark.contract
@pytest.mark.asyncio
async def test_initial_state_and_incoming_event_order(calls_harness):
    calls, socket, *_ = calls_harness
    seen = []
    calls.addEventListener("state", lambda event: seen.append(("state", event.detail.state)))
    calls.addEventListener(
        "incoming-call", lambda event: seen.append(("incoming-call", event.detail.wid))
    )
    await socket.receive(frame("incoming"))
    await socket.receive(frame("incoming"))

    assert seen == [
        ("state", "inc-call"), ("incoming-call", "100@lid"), ("state", "inc-call"),
    ]
    assert calls.state.info.id == "call-1"
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_incoming_without_info_emits_state_only(calls_harness):
    calls, socket, *_ = calls_harness
    seen = []
    calls.addEventListener("state", lambda event: seen.append("state"))
    calls.addEventListener("incoming-call", lambda event: seen.append("incoming-call"))
    await socket.receive({"type": "state", "state": {"state": "inc-call"}})
    assert seen == ["state"]
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_remove_listener_stops_future_delivery(calls_harness):
    calls, socket, *_ = calls_harness
    seen = []
    listener = lambda event: seen.append(event.detail.state)
    calls.addEventListener("state", listener)
    await socket.receive({"type": "state", "state": {"state": "idle"}})
    calls.removeEventListener("state", listener)
    await socket.receive({"type": "state", "state": {"state": "out-call"}})
    assert seen == ["idle"]
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_socket_connect_and_disconnect_are_forwarded(calls_harness):
    calls, socket, *_ = calls_harness
    seen = []
    calls.addEventListener("connect", lambda event: seen.append(("connect", event.detail)))
    calls.addEventListener("disconnect", lambda event: seen.append(("disconnect", event.detail)))
    await socket.emit("connect")
    await socket.emit("disconnect", {"reason": "network lost", "code": 1006, "permanent": False})
    assert seen == [
        ("connect", None),
        ("disconnect", {"reason": "network lost", "code": 1006, "permanent": False}),
    ]
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_bridge_offer_waits_for_answer_and_buffers_early_candidate(calls_harness):
    calls, socket, rest, bridges, audio = calls_harness
    local_streams = []
    calls.addEventListener("local-stream-ready", lambda event: local_streams.append(event.detail))
    task = await started_bridge(calls_harness)

    assert calls.hasAudioBridge is True  # TS checks PeerConnection existence, not ICE.
    assert not task.done()
    assert local_streams == audio.streams
    assert ("GET", "callsGetIceServers") in rest.calls
    assert bridges.bridges[0].ice_servers == rest.ice_servers
    assert socket.sent[0] == {"type": "offer", "offer": bridges.bridges[0].offer}
    assert bridges.bridges[0].tracks[0][1] is audio.streams[0]

    candidate = frame("candidate")["candidate"]
    await socket.receive(frame("candidate"))
    assert ("addIceCandidate", candidate) not in bridges.bridges[0].calls

    await socket.receive(frame("answer"))
    await task
    calls_log = bridges.bridges[0].calls
    assert calls_log.index(("setRemoteDescription", frame("answer")["answer"])) < calls_log.index(
        ("addIceCandidate", candidate)
    )
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_candidate_after_answer_is_applied_immediately(calls_harness):
    calls, socket, _, bridges, _ = calls_harness
    task = await started_bridge(calls_harness)
    await socket.receive(frame("answer"))
    await task
    await socket.receive(frame("candidate"))
    assert ("addIceCandidate", frame("candidate")["candidate"]) in bridges.bridges[0].calls
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_second_bridge_is_rejected_while_starting_or_active(calls_harness):
    calls, socket, *_ = calls_harness
    task = await started_bridge(calls_harness)
    with pytest.raises(Exception, match="Audio bridge already starting or active"):
        await calls.startAudioBridge()
    await socket.receive(frame("answer"))
    await task
    with pytest.raises(Exception, match="Audio bridge already starting or active"):
        await calls.startAudioBridge()
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_server_error_rejects_pending_bridge_and_cleans_up(calls_harness):
    calls, socket, _, bridges, audio = calls_harness
    task = await started_bridge(calls_harness)
    await socket.receive({"type": "error", "message": "no active call"})
    with pytest.raises(Exception, match="no active call"):
        await task
    assert calls.hasAudioBridge is False
    assert bridges.bridges[0].closed is True
    assert audio.streams[0].track.stopped is True
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_server_error_without_pending_bridge_is_event(calls_harness):
    calls, socket, *_ = calls_harness
    errors = []
    calls.addEventListener("error", lambda event: errors.append(event.detail["message"]))
    await socket.receive({"type": "error", "message": "calls unavailable"})
    assert errors == ["calls unavailable"]
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_idle_state_stops_bridge_and_emits_server_cause(calls_harness):
    calls, socket, _, bridges, audio = calls_harness
    ended = []
    calls.addEventListener("end-call", lambda event: ended.append(event.detail))
    await socket.receive({"type": "state", "state": {"state": "on-call"}})
    task = await started_bridge(calls_harness)
    await socket.receive(frame("answer"))
    await task
    await socket.receive(frame("ended"))

    assert calls.state.state == "idle"
    assert socket.sent[-1] == {"type": "stop"}
    assert bridges.bridges[0].closed is True
    assert audio.streams[0].track.stopped is True
    assert ended == [{"reason": "call-ended", "cause": "hangup"}]
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_end_call_without_server_cause_has_no_cause_key(calls_harness):
    calls, socket, *_ = calls_harness
    ended = []
    calls.addEventListener("end-call", lambda event: ended.append(event.detail))
    await socket.receive({"type": "state", "state": {"state": "inc-call"}})
    await socket.receive({"type": "state", "state": {"state": "idle"}})
    assert ended == [{"reason": "call-ended"}]
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_stop_audio_bridge_keeps_server_call_state(calls_harness):
    calls, socket, _, bridges, audio = calls_harness
    await socket.receive({"type": "state", "state": {"state": "on-call"}})
    task = await started_bridge(calls_harness)
    await socket.receive(frame("answer"))
    await task
    await calls.stopAudioBridge()
    assert socket.sent[-1] == {"type": "stop"}
    assert calls.state.state == "on-call"
    assert calls.hasAudioBridge is False
    assert bridges.bridges[0].closed is True
    assert audio.streams[0].track.stopped is True
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_stop_without_peer_does_not_send_stop(calls_harness):
    calls, socket, *_ = calls_harness
    await calls.stopAudioBridge()
    assert socket.sent == []
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_close_does_not_send_stop_or_hang_up(calls_harness):
    calls, socket, rest, bridges, audio = calls_harness
    task = await started_bridge(calls_harness)
    await socket.receive(frame("answer"))
    await task
    await calls.close()
    assert {"type": "stop"} not in socket.sent
    assert not any(item[0] == "POST" for item in rest.calls)
    assert socket.closed is True
    assert bridges.bridges[0].closed is True
    assert audio.streams[0].track.stopped is True


@pytest.mark.contract
@pytest.mark.asyncio
async def test_temporary_disconnect_recreates_bridge_without_ending_call(calls_harness):
    calls, socket, _, bridges, audio = calls_harness
    ended = []
    calls.addEventListener("end-call", lambda event: ended.append(event.detail))
    await socket.receive({"type": "state", "state": {"state": "on-call"}})
    task = await started_bridge(calls_harness)
    await socket.receive(frame("answer"))
    await task

    await socket.emit("disconnect", {"reason": "network lost", "code": 1006, "permanent": False})
    assert ended == []
    assert bridges.bridges[0].closed is True
    assert audio.streams[0].track.stopped is True
    assert {"type": "stop"} not in socket.sent

    await socket.receive({"type": "state", "state": {"state": "on-call"}})
    await until(lambda: len(bridges.bridges) == 2 and len(socket.sent) == 2)
    assert socket.sent[-1]["type"] == "offer"
    assert audio.streams[1] is not audio.streams[0]
    await socket.receive(frame("answer"))
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_disconnect_without_bridge_reports_connection_lost(calls_harness):
    calls, socket, *_ = calls_harness
    ended = []
    calls.addEventListener("end-call", lambda event: ended.append(event.detail))
    await socket.receive({"type": "state", "state": {"state": "inc-call"}})
    await socket.emit("disconnect", {"reason": "network lost", "code": 1006, "permanent": False})
    assert calls.state is None
    assert ended == [{"reason": "connection-lost"}]
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_disconnect_during_negotiation_rejects_waiter(calls_harness):
    calls, socket, *_ = calls_harness
    await socket.receive({"type": "state", "state": {"state": "out-call"}})
    task = await started_bridge(calls_harness)
    await socket.emit("disconnect", {"reason": "network lost", "code": 1006, "permanent": False})
    with pytest.raises(Exception, match="Socket disconnected during negotiation"):
        await task
    assert calls.hasAudioBridge is False
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_permanent_refusal_reports_one_error_and_no_resume(calls_harness):
    calls, socket, _, bridges, _ = calls_harness
    errors, ended = [], []
    calls.addEventListener("error", lambda event: errors.append(event.detail["message"]))
    calls.addEventListener("end-call", lambda event: ended.append(event.detail))
    await socket.receive({"type": "state", "state": {"state": "out-call"}})
    task = await started_bridge(calls_harness)
    await socket.receive(frame("answer"))
    await task
    await socket.receive({"type": "error", "message": "calls disabled"})
    await socket.emit("disconnect", {"reason": "calls disabled", "code": 4001, "permanent": True})
    await socket.receive({"type": "state", "state": {"state": "out-call"}})

    assert errors == ["calls disabled"]
    assert ended == [{"reason": "connection-lost"}]
    assert len(bridges.bridges) == 1
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_permanent_refusal_without_error_frame_reports_reason(calls_harness):
    calls, socket, *_ = calls_harness
    errors = []
    calls.addEventListener("error", lambda event: errors.append(event.detail["message"]))
    await socket.emit("disconnect", {"reason": "plan disabled", "code": 4001, "permanent": True})
    assert errors == ["plan disabled"]
    await calls.close()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_remote_stream_event_exposes_peer_media(calls_harness):
    calls, socket, _, bridges, _ = calls_harness
    remote = object()
    seen = []
    calls.addEventListener("remote-stream-ready", lambda event: seen.append(event.detail))
    task = await started_bridge(calls_harness)
    await bridges.bridges[0].emit("track", {"streams": [remote]})
    assert seen == [remote]
    await socket.receive(frame("answer"))
    await task
    await calls.close()


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_close_settles_pending_negotiation_in_python(calls_harness):
    calls, socket, *_ = calls_harness
    task = await started_bridge(calls_harness)
    await calls.close()
    with pytest.raises(Exception, match="closed|cancelled"):
        await asyncio.wait_for(task, timeout=0.1)


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_stop_send_failure_does_not_leak_local_resources(calls_harness):
    calls, socket, _, bridges, audio = calls_harness
    task = await started_bridge(calls_harness)
    await socket.receive(frame("answer"))
    await task

    async def failing_send(message):
        if message.get("type") == "stop":
            raise ConnectionError("socket closed")
        socket.sent.append(message)

    socket.send = failing_send
    with pytest.raises(ConnectionError, match="socket closed"):
        await calls.stopAudioBridge()
    assert bridges.bridges[0].closed is True
    assert audio.streams[0].track.stopped is True
    await calls.close()
