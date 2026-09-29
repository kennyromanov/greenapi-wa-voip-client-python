"""Optional aiortc audio tracks and frame consumers for headless callers."""

from collections.abc import Callable
from aiortc import MediaStreamTrack
from aiortc.contrib.media import MediaBlackhole
from aiortc.mediastreams import MediaStreamError
from .audio import AudioDevice, LocalAudioStream
import asyncio
import inspect
import logging

logger = logging.getLogger(__name__)


class _TrackSource:
    def __init__(self, track_factory: Callable[[], MediaStreamTrack]):
        self._track_factory = track_factory
        self._track = None

    async def acquire(self) -> LocalAudioStream:
        track = self._track_factory()
        self._track = track

        if not isinstance(track, MediaStreamTrack) or track.kind != "audio":
            raise ValueError("track_factory must return an audio MediaStreamTrack")

        return LocalAudioStream(track)

    async def close(self) -> None:
        if self._track is not None:
            self._track.stop()
            self._track = None


class DiscardAudioSink:
    """Consume incoming audio without opening a system output device."""

    def __init__(self):
        self._sink = MediaBlackhole()
        self._closed = False

    async def attach(self, track: MediaStreamTrack) -> None:
        if self._closed:
            raise RuntimeError("Audio sink is closed")

        self._sink.addTrack(track)
        await self._sink.start()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._sink.stop()


class FrameAudioSink:
    """Pass each decoded remote PyAV AudioFrame to a sync or async callback."""

    def __init__(self, on_frame: Callable):
        self._on_frame = on_frame
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    async def attach(self, track: MediaStreamTrack) -> None:
        if self._closed:
            raise RuntimeError("Audio sink is closed")

        if getattr(track, "kind", None) != "audio":
            raise ValueError("Expected a remote audio track")

        task = asyncio.create_task(self._consume(track))

        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _consume(self, track: MediaStreamTrack) -> None:
        try:
            while True:
                frame = await track.recv()
                result = self._on_frame(frame)

                if inspect.isawaitable(result):
                    await result
        except MediaStreamError:
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Remote audio frame consumer failed")

    async def close(self) -> None:
        if self._closed:
            return

        self._closed = True

        tasks = tuple(self._tasks)

        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._tasks.clear()


class TrackAudioDevice(AudioDevice):
    """Use a fresh aiortc audio track and a custom remote audio sink per bridge."""

    def __init__(self, track_factory: Callable[[], MediaStreamTrack], *, sink_factory=None):
        super().__init__(
            source_factory=lambda: _TrackSource(track_factory),
            sink_factory=sink_factory or DiscardAudioSink,
        )

    async def close(self) -> None:
        try:
            await self._source.close()
        finally:
            await self._sink.close()
