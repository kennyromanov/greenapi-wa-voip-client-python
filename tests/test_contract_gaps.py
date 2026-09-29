"""Previously uncovered signaling and startup races."""

import asyncio

import pytest

from tests.fakes import until


@pytest.mark.contract
@pytest.mark.asyncio
async def test_local_ice_candidate_is_sent_as_calls_rtc_frame(calls_harness):
    calls, socket, _, bridges, _ = calls_harness
    task = asyncio.create_task(calls.startAudioBridge())
    await until(lambda: len(bridges.bridges) == 1 and bool(socket.sent))
    candidate = {"candidate": "candidate:1 1 udp 1 192.0.2.1 5555 typ host", "sdpMid": "0"}
    await bridges.bridges[0].emit("icecandidate", {"candidate": candidate})
    await bridges.bridges[0].emit("icecandidate", {"candidate": None})
    assert socket.sent[-1] == {"type": "ice-candidate", "candidate": candidate}
    assert len(socket.sent) == 2
    await calls.close()
    with pytest.raises(RuntimeError, match="closed"):
        await task


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_close_while_audio_acquisition_is_pending_does_not_send_offer(calls_harness):
    calls, socket, _, bridges, audio = calls_harness
    release = asyncio.Event()
    original_factory = calls._audio_factory

    async def slow_audio():
        await release.wait()
        return await original_factory()

    calls._audio_factory = slow_audio
    task = asyncio.create_task(calls.startAudioBridge())
    await until(lambda: calls._pendingBridge is not None)
    await calls.close()
    release.set()
    with pytest.raises(RuntimeError, match="closed"):
        await task
    assert socket.sent == []
    assert bridges.bridges == []
    assert audio.streams[0].track.stopped is True
