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
