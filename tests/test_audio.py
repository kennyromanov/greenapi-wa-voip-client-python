"""Future local audio boundary; hardware is always replaced by a fake."""

import pytest

from tests.fakes import FakeStream, FakeTrack


class FakeSource:
    def __init__(self):
        self.stream = FakeStream()
        self.closed = False

    async def acquire(self):
        return self.stream

    async def close(self):
        self.closed = True
        self.stream.track.stop()


class FakeSink:
    def __init__(self):
        self.tracks = []
        self.closed = False

    async def attach(self, track):
        self.tracks.append(track)

    async def close(self):
        self.closed = True


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_audio_device_returns_live_local_stream(target):
    module = target("rtc.audio")
    source, sink = FakeSource(), FakeSink()
    audio = module.AudioDevice(source_factory=lambda: source, sink_factory=lambda: sink)
    stream = await audio.acquireLocal()
    assert stream is source.stream
    assert stream.getAudioTracks()[0].readyState == "live"
    await audio.close()


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_remote_track_is_attached_to_sink(target):
    module = target("rtc.audio")
    sink = FakeSink()
    audio = module.AudioDevice(source_factory=FakeSource, sink_factory=lambda: sink)
    remote_track = FakeTrack()
    await audio.attachRemote(remote_track)
    assert sink.tracks == [remote_track]
    await audio.close()


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_audio_device_close_stops_source_and_sink(target):
    module = target("rtc.audio")
    source, sink = FakeSource(), FakeSink()
    audio = module.AudioDevice(source_factory=lambda: source, sink_factory=lambda: sink)
    await audio.acquireLocal()
    await audio.close()
    assert source.closed is True
    assert source.stream.track.stopped is True
    assert sink.closed is True
