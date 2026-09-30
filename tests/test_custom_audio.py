"""Optional aiortc audio input and output without system devices."""

from fractions import Fraction
from aiortc import AudioStreamTrack
from aiortc.contrib.media import MediaPlayer
from aiortc.mediastreams import MediaStreamError
from av import AudioFrame
import asyncio
import importlib
import wave
import pytest

from tests.fakes import FakeBridgeFactory, FakeRest, FakeSocket, FakeTrack, until


class OneFrameTrack(AudioStreamTrack):
    def __init__(self):
        super().__init__()
        self.received = False

    async def recv(self):
        if self.received:
            self.stop()
            raise MediaStreamError

        self.received = True

        frame = AudioFrame(format="s16", layout="mono", samples=960)
        frame.planes[0].update(bytes(1920))
        frame.sample_rate = 48_000
        frame.time_base = Fraction(1, 48_000)
        frame.pts = 0

        return frame


@pytest.mark.adaptation
def test_custom_audio_adapters_are_public_exports():
    package = importlib.import_module("greenapi_wa_voip_client")

    assert {"TrackAudioDevice", "FrameAudioSink", "DiscardAudioSink"} <= set(package.__all__)

    assert all(hasattr(package, name) for name in (
        "TrackAudioDevice", "FrameAudioSink", "DiscardAudioSink",
    ))


@pytest.mark.adaptation
def test_public_connection_forwards_only_explicit_audio_override(target, monkeypatch):
    module = target("green_api_voip_client")
    rest = FakeRest()
    calls = []

    monkeypatch.setattr(module, "GreenApiRestClient", lambda options: rest)
    monkeypatch.setattr(module, "CallsConnection", lambda *args, **kwargs: calls.append((args, kwargs)))

    client = module.GreenApiVoipClient({})
    factory = lambda: None

    client.connectCalls()
    client.connectCalls(audio_device_factory=factory)

    assert calls == [((rest,), {}), ((rest,), {"audio_device_factory": factory})]


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_custom_audio_receives_remote_track_and_recreates_device_on_reconnect(target):
    connection = target("calls_connection")

    socket, rest, bridges = FakeSocket(), FakeRest(), FakeBridgeFactory()

    devices = []

    class Device:
        def __init__(self):
            self.track = FakeTrack()
            self.remote = []
            self.closed = False

        async def acquireLocal(self):
            from greenapi_wa_voip_client.rtc.audio import LocalAudioStream
            return LocalAudioStream(self.track)

        async def attachRemote(self, track):
            self.remote.append(track)

        async def close(self):
            self.closed = True

    def make_device():
        device = Device()
        devices.append(device)

        return device

    calls = connection.CallsConnection(
        rest, socket=socket, bridge_factory=bridges,
        audio_device_factory=make_device,
    )

    await socket.receive({"type": "state", "state": {"state": "on-call"}})

    first = asyncio.create_task(calls.startAudioBridge())

    await until(lambda: bool(socket.sent))
    assert bridges.bridges[0].tracks[0][0] is devices[0].track

    remote = FakeTrack()

    await bridges.bridges[0].emit("track", {"track": remote, "streams": [object()]})
    assert devices[0].remote == [remote]
    await socket.receive({"type": "answer", "answer": {"type": "answer", "sdp": "v=0"}})

    await first

    await socket.emit("disconnect", {"reason": "lost", "code": 1006, "permanent": False})
    assert devices[0].closed and devices[0].track.stopped
    await socket.receive({"type": "state", "state": {"state": "on-call"}})
    await until(lambda: len(bridges.bridges) == 2 and len(socket.sent) == 2)
    assert devices[1] is not devices[0]
    assert bridges.bridges[1].tracks[0][0] is devices[1].track
    await bridges.bridges[0].emit("track", {"track": FakeTrack(), "streams": [object()]})
    assert devices[1].remote == []
    await socket.receive({"type": "answer", "answer": {"type": "answer", "sdp": "v=0"}})
    await calls.close()
    assert devices[1].closed and devices[1].track.stopped


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_no_override_uses_existing_audio_device_path(target, monkeypatch):
    connection = target("calls_connection")
    audio_module = target("rtc.audio")

    socket, rest, bridges = FakeSocket(), FakeRest(), FakeBridgeFactory()

    devices = []

    class DefaultDevice:
        def __init__(self):
            self.track = FakeTrack()
            self.remote = []
            self.closed = False

            devices.append(self)

        async def acquireLocal(self):
            return audio_module.LocalAudioStream(self.track)

        async def attachRemote(self, track):
            self.remote.append(track)

        async def close(self):
            self.closed = True

    monkeypatch.setattr(audio_module, "AudioDevice", DefaultDevice)

    calls = connection.CallsConnection(rest, socket=socket, bridge_factory=bridges)
    task = asyncio.create_task(calls.startAudioBridge())

    await until(lambda: bool(socket.sent))
    assert bridges.bridges[0].tracks[0][0] is devices[0].track

    remote = FakeTrack()

    await bridges.bridges[0].emit("track", {"track": remote, "streams": [object()]})
    assert devices[0].remote == [remote]
    await socket.receive({"type": "answer", "answer": {"type": "answer", "sdp": "v=0"}})
    await task
    await calls.close()
    assert devices[0].closed and devices[0].track.stopped


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_track_device_and_frame_sink_use_aiortc_frames_without_hardware(target):
    custom = target("rtc.custom_audio")
    local, remote = OneFrameTrack(), OneFrameTrack()
    received = []
    device = custom.TrackAudioDevice(
        lambda: local,
        sink_factory=lambda: custom.FrameAudioSink(received.append),
    )
    stream = await device.acquireLocal()
    assert stream.getAudioTracks() == [local]
    await device.attachRemote(remote)
    await until(lambda: len(received) == 1)
    assert isinstance(received[0], AudioFrame)
    await device.close()
    assert local.readyState == "ended"


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_track_device_creates_one_generation_pair_in_track_then_sink_order(target):
    custom = target("rtc.custom_audio")
    generation = 0
    created = []
    tracks = []
    sinks = []

    class Sink:
        def __init__(self, value):
            self.generation = value
            self.remote = []
            self.closes = 0

        async def attach(self, track):
            self.remote.append(track)

        async def close(self):
            self.closes += 1

    def make_track():
        nonlocal generation

        generation += 1
        created.append(("track", generation))

        track = OneFrameTrack()

        tracks.append(track)

        return track

    def make_sink():
        created.append(("sink", generation))

        sink = Sink(generation)

        sinks.append(sink)

        return sink

    device = custom.TrackAudioDevice(make_track, sink_factory=make_sink)

    assert created == []

    # Direct users may attach a remote track before requesting the local one.
    remote = OneFrameTrack()

    await device.attachRemote(remote)

    first = await device.acquireLocal()
    second = await device.acquireLocal()

    assert created == [("track", 1), ("sink", 1)]
    assert first is second
    assert first.getAudioTracks() == tracks
    assert sinks[0].generation == generation == 1
    assert sinks[0].remote == [remote]

    await device.close()
    await device.close()

    assert tracks[0].readyState == "ended"
    assert sinks[0].closes == 1


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_track_device_close_before_acquisition_does_not_call_factories(target):
    custom = target("rtc.custom_audio")
    created = []

    device = custom.TrackAudioDevice(
        lambda: created.append("track") or OneFrameTrack(),
        sink_factory=lambda: created.append("sink") or custom.DiscardAudioSink(),
    )

    await device.close()
    await device.close()

    assert created == []

    with pytest.raises(RuntimeError, match="closed"):
        await device.acquireLocal()

    with pytest.raises(RuntimeError, match="closed"):
        await device.attachRemote(OneFrameTrack())

    assert created == []


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_track_device_stops_new_track_when_sink_factory_fails(target):
    custom = target("rtc.custom_audio")
    track = OneFrameTrack()

    def fail_sink():
        raise ValueError("sink unavailable")

    device = custom.TrackAudioDevice(lambda: track, sink_factory=fail_sink)

    with pytest.raises(ValueError, match="sink unavailable"):
        await device.acquireLocal()

    assert track.readyState == "ended"

    await device.close()

    with pytest.raises(RuntimeError, match="closed"):
        await device.acquireLocal()


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_track_device_close_waits_for_remote_attachment(target):
    custom = target("rtc.custom_audio")
    attached = asyncio.Event()
    release = asyncio.Event()
    track = OneFrameTrack()
    closed = []

    class SlowSink:
        async def attach(self, remote):
            attached.set()
            await release.wait()

        async def close(self):
            closed.append(True)

    device = custom.TrackAudioDevice(lambda: track, sink_factory=SlowSink)
    attaching = asyncio.create_task(device.attachRemote(OneFrameTrack()))

    await attached.wait()

    closing = asyncio.create_task(device.close())

    await asyncio.sleep(0)
    assert not closing.done()

    release.set()
    await asyncio.gather(attaching, closing)

    assert closed == [True]
    assert track.readyState == "ended"


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_track_device_pairs_new_generations_after_reconnect(target):
    connection = target("calls_connection")
    custom = target("rtc.custom_audio")
    socket, rest, bridges = FakeSocket(), FakeRest(), FakeBridgeFactory()
    generation = 0
    made = []

    class Sink:
        def __init__(self, value):
            self.generation = value
            self.remote = []
            self.frames = 0

        async def attach(self, track):
            self.remote.append(track)

            if self.generation == generation:
                await track.recv()
                self.frames += 1

        async def close(self):
            pass

    def make_audio_device():
        def make_track():
            nonlocal generation

            generation += 1

            return OneFrameTrack()

        def make_sink():
            sink = Sink(generation)

            made.append(sink)

            return sink

        return custom.TrackAudioDevice(make_track, sink_factory=make_sink)

    calls = connection.CallsConnection(
        rest, socket=socket, bridge_factory=bridges,
        audio_device_factory=make_audio_device,
    )

    await socket.receive({"type": "state", "state": {"state": "on-call"}})

    first = asyncio.create_task(calls.startAudioBridge())

    await until(lambda: bool(socket.sent))
    await bridges.bridges[0].emit("track", {"track": OneFrameTrack(), "streams": [object()]})
    await socket.receive({"type": "answer", "answer": {"type": "answer", "sdp": "v=0"}})

    await first

    assert made[0].generation == 1
    assert len(made[0].remote) == 1
    assert made[0].frames == 1

    await socket.emit("disconnect", {"reason": "lost", "code": 1006, "permanent": False})
    await socket.receive({"type": "state", "state": {"state": "on-call"}})
    await until(lambda: len(bridges.bridges) == 2 and len(socket.sent) == 2)
    await bridges.bridges[1].emit("track", {"track": OneFrameTrack(), "streams": [object()]})
    await socket.receive({"type": "answer", "answer": {"type": "answer", "sdp": "v=0"}})
    assert [sink.generation for sink in made] == [1, 2]
    assert all(len(sink.remote) == 1 for sink in made)
    assert [sink.frames for sink in made] == [1, 1]
    await calls.close()


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_frame_sink_closes_while_remote_recv_is_pending(target):
    custom = target("rtc.custom_audio")
    pending = asyncio.Event()

    class BlockingTrack(AudioStreamTrack):
        async def recv(self):
            await pending.wait()
            raise MediaStreamError

    sink = custom.FrameAudioSink(lambda frame: None)
    await sink.attach(BlockingTrack())
    await asyncio.wait_for(sink.close(), timeout=0.5)


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_frame_sink_awaits_async_frame_callback(target):
    custom = target("rtc.custom_audio")
    received = []

    async def on_frame(frame):
        await asyncio.sleep(0)
        received.append(frame)

    sink = custom.FrameAudioSink(on_frame)
    await sink.attach(OneFrameTrack())
    await until(lambda: len(received) == 1)
    await sink.close()
    assert isinstance(received[0], AudioFrame)


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_track_device_rejects_non_audio_track_and_can_close(target):
    custom = target("rtc.custom_audio")
    track = FakeTrack()
    track.kind = "video"
    device = custom.TrackAudioDevice(lambda: track)
    with pytest.raises(ValueError, match="audio"):
        await device.acquireLocal()
    await device.close()
    assert track.stopped


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_wav_player_is_a_supported_custom_audio_source(target, tmp_path):
    custom = target("rtc.custom_audio")
    path = tmp_path / "sample.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(bytes(48_000 * 2 // 10))

    player = MediaPlayer(str(path))
    device = custom.TrackAudioDevice(lambda: player.audio)
    try:
        track = (await device.acquireLocal()).getAudioTracks()[0]
        read = asyncio.create_task(track.recv())
        # Keep the loop active while MediaPlayer's worker schedules its frames.
        for _ in range(300):
            if read.done():
                break
            await asyncio.sleep(0.01)
        assert read.done()
        frame = await read
        assert isinstance(frame, AudioFrame)
        assert frame.sample_rate == 48_000
    finally:
        await device.close()
    assert track.readyState == "ended"


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_custom_device_delivers_remote_frames_via_connection(target):
    connection = target("calls_connection")
    socket, rest, bridges = FakeSocket(), FakeRest(), FakeBridgeFactory()
    received = []
    custom = target("rtc.custom_audio")
    calls = connection.CallsConnection(
        rest, socket=socket, bridge_factory=bridges,
        audio_device_factory=lambda: custom.TrackAudioDevice(
            OneFrameTrack,
            sink_factory=lambda: custom.FrameAudioSink(received.append),
        ),
    )
    task = asyncio.create_task(calls.startAudioBridge())
    await until(lambda: bool(socket.sent))
    await bridges.bridges[0].emit(
        "track", {"track": OneFrameTrack(), "streams": [object()]},
    )
    await until(lambda: len(received) == 1)
    await socket.receive({"type": "answer", "answer": {"type": "answer", "sdp": "v=0"}})
    await task
    await calls.close()
    assert isinstance(received[0], AudioFrame)
