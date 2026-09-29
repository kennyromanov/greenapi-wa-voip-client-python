"""Audio frame conversion without opening system devices."""

import asyncio

import pytest

from greenapi_wa_voip_client.rtc.audio import FRAME_SAMPLES, SAMPLE_RATE, MicrophoneTrack


class FakeInput:
    def __init__(self):
        self.payload = bytes(FRAME_SAMPLES * 2)

    def read(self, samples):
        assert samples == FRAME_SAMPLES
        return self.payload, False


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_microphone_track_yields_timed_pcm_frames(monkeypatch):
    async def direct(call, *args):
        return call(*args)

    # The sandbox may prohibit threads; this test concerns PCM and timestamps.
    monkeypatch.setattr(asyncio, "to_thread", direct)
    track = MicrophoneTrack(FakeInput())
    first = await track.recv()
    second = await track.recv()
    assert first.sample_rate == SAMPLE_RATE
    assert first.samples == FRAME_SAMPLES
    assert first.pts == 0
    assert second.pts == FRAME_SAMPLES
    assert bytes(first.planes[0]) == bytes(FRAME_SAMPLES * 2)
    track.stop()


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_disabled_microphone_track_emits_silence(monkeypatch):
    async def direct(call, *args):
        return call(*args)

    monkeypatch.setattr(asyncio, "to_thread", direct)
    source = FakeInput()
    source.payload = b"\x01\x00" * FRAME_SAMPLES
    track = MicrophoneTrack(source)
    track.enabled = False
    frame = await track.recv()
    assert bytes(frame.planes[0]) == bytes(FRAME_SAMPLES * 2)
    track.stop()
