"""Optional aiortc audio tracks and frame consumers for headless callers."""

from collections.abc import Callable
from aiortc import MediaStreamTrack
from aiortc.contrib.media import MediaBlackhole
from aiortc.mediastreams import MediaStreamError
from .audio import LocalAudioStream
import asyncio
import inspect
import logging

logger = logging.getLogger(__name__)


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


class TrackAudioDevice:
    """Create one local track and remote sink together for each audio bridge."""

    def __init__(self, track_factory: Callable[[], MediaStreamTrack], *, sink_factory=None):
        self._track_factory = track_factory
        self._sink_factory = sink_factory if sink_factory is not None else DiscardAudioSink
        self._stream = None
        self._sink = None
        self._closed = False
        self._lock = asyncio.Lock()

    def _ensure_initialized(self) -> None:
        if self._closed:
            raise RuntimeError("Audio device is closed")

        if self._stream is not None:
            return

        track = None

        try:
            track = self._track_factory()

            if not isinstance(track, MediaStreamTrack) or track.kind != "audio":
                raise ValueError("track_factory must return an audio MediaStreamTrack")

            sink = self._sink_factory()
        except BaseException:
            self._closed = True

            if track is not None and callable(getattr(track, "stop", None)):
                try:
                    track.stop()
                except Exception:
                    logger.exception("Could not stop audio track after initialization failed")

            raise

        self._stream = LocalAudioStream(track)
        self._sink = sink

    async def acquireLocal(self) -> LocalAudioStream:
        async with self._lock:
            self._ensure_initialized()
            return self._stream

    async def attachRemote(self, track: MediaStreamTrack) -> None:
        async with self._lock:
            self._ensure_initialized()
            await self._sink.attach(track)

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return

            self._closed = True
            stream, sink = self._stream, self._sink
            self._stream = None
            self._sink = None

            try:
                if stream is not None:
                    for track in stream.getTracks():
                        track.stop()
            finally:
                if sink is not None:
                    await sink.close()
