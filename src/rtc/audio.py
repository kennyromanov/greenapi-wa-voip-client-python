"""Microphone and speaker boundary for the aiortc audio track."""

import asyncio
from fractions import Fraction

from aiortc import AudioStreamTrack
from av import AudioFrame, AudioResampler

SAMPLE_RATE = 48_000
FRAME_SAMPLES = 960  # 20 ms, the usual Opus packet interval.


class LocalAudioStream:
    def __init__(self, track):
        self.track = track

    def getTracks(self):
        return [self.track]

    def getAudioTracks(self):
        return [self.track]


class MicrophoneTrack(AudioStreamTrack):
    def __init__(self, device):
        super().__init__()
        self._device = device
        self._pts = 0
        self.enabled = True

    async def recv(self):
        data, _overflow = await asyncio.to_thread(self._device.read, FRAME_SAMPLES)
        if not self.enabled:
            data = bytes(FRAME_SAMPLES * 2)
        frame = AudioFrame(format="s16", layout="mono", samples=FRAME_SAMPLES)
        frame.planes[0].update(bytes(data))
        frame.sample_rate = SAMPLE_RATE
        frame.time_base = Fraction(1, SAMPLE_RATE)
        frame.pts = self._pts
        self._pts += FRAME_SAMPLES
        return frame


class _SystemSource:
    def __init__(self):
        self._stream = None
        self._track = None

    async def acquire(self):
        import sounddevice as sd

        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE, blocksize=FRAME_SAMPLES,
            channels=1, dtype="int16",
        )
        self._stream.start()
        self._track = MicrophoneTrack(self._stream)
        return LocalAudioStream(self._track)

    async def close(self):
        if self._track is not None:
            self._track.stop()
        if self._stream is not None:
            self._stream.abort()
            self._stream.close()


class _SystemSink:
    def __init__(self):
        self._stream = None
        self._tasks = set()

    async def attach(self, track):
        if self._stream is None:
            import sounddevice as sd

            self._stream = sd.RawOutputStream(
                samplerate=SAMPLE_RATE, blocksize=FRAME_SAMPLES,
                channels=1, dtype="int16",
            )
            self._stream.start()
        task = asyncio.create_task(self._play(track))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _play(self, track):
        resampler = AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        try:
            while True:
                frame = await track.recv()
                for converted in resampler.resample(frame):
                    await asyncio.to_thread(self._stream.write, bytes(converted.planes[0]))
        except asyncio.CancelledError:
            raise
        except Exception:
            # Remote track can end when the bridge closes.
            return

    async def close(self):
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._stream is not None:
            self._stream.abort()
            self._stream.close()


class AudioDevice:
    def __init__(self, *, source_factory=None, sink_factory=None):
        self._source = (source_factory or _SystemSource)()
        self._sink = (sink_factory or _SystemSink)()

    async def acquireLocal(self):
        return await self._source.acquire()

    async def attachRemote(self, track):
        await self._sink.attach(track)

    async def close(self):
        await self._source.close()
        await self._sink.close()
