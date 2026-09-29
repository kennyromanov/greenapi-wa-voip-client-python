"""WebSocket signaling with the retry policy of reconnecting-socket.ts."""

import asyncio
import json

from websockets.asyncio.client import connect

from .events import Event, EventTarget

INITIAL_BACKOFF_MS = 500
MAX_BACKOFF_MS = 10_000
PERMANENT_CLOSE_MIN = 4000
PERMANENT_CLOSE_MAX = 4999


class ReconnectingSocket(EventTarget):
    def __init__(self, url: str, *, socket_factory=None, sleep=None):
        super().__init__()
        self._url = url
        self._socket_factory = socket_factory or connect
        self._sleep = sleep or asyncio.sleep
        self._socket = None
        self._closedByUser = False
        self._refusedByServer = False
        self._backoffMs = INITIAL_BACKOFF_MS
        self._task = asyncio.get_running_loop().create_task(self._connect())

    @property
    def refused(self) -> bool:
        return self._refusedByServer

    async def send(self, data) -> None:
        if self._socket is None:
            raise RuntimeError("ReconnectingSocket is not connected")
        await self._socket.send(json.dumps(data, separators=(",", ":")))

    async def close(self) -> None:
        self._closedByUser = True
        if self._socket is not None:
            await self._socket.close()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._socket = None

    async def _connect(self) -> None:
        while not self._closedByUser:
            try:
                socket = await self._socket_factory(self._url)
                if self._closedByUser:
                    await socket.close()
                    return
                self._socket = socket
                self._backoffMs = INITIAL_BACKOFF_MS
                self.dispatchEvent(Event("connect"))
                while not self._closedByUser:
                    try:
                        raw = await socket.recv()
                    except Exception as exc:
                        code = getattr(exc, "code", None)
                        if code is None:
                            frame = getattr(exc, "rcvd", None)
                            code = getattr(frame, "code", 1006)
                            reason = getattr(frame, "reason", "")
                        else:
                            reason = getattr(exc, "reason", "")
                        self._socket = None
                        if self._closedByUser:
                            return
                        permanent = PERMANENT_CLOSE_MIN <= code <= PERMANENT_CLOSE_MAX
                        self._refusedByServer |= permanent
                        await self._dispatchEventInOrder(Event("disconnect", {
                            "reason": reason or "connection closed", "code": code,
                            "permanent": permanent,
                        }))
                        if permanent:
                            return
                        break
                    try:
                        parsed = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
                    await self._dispatchEventInOrder(Event("message", parsed))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._closedByUser:
                    return
                self._socket = None
                await self._dispatchEventInOrder(Event("disconnect", {
                    # Connection errors may include the URL and its API token.
                    "reason": f"{type(exc).__name__}: connection failed", "code": 1006,
                    "permanent": False,
                }))
            if not self._closedByUser:
                await self._scheduleReconnect()

    async def _scheduleReconnect(self) -> None:
        delay = self._backoffMs
        self._backoffMs = min(self._backoffMs * 2, MAX_BACKOFF_MS)
        await self._sleep(delay / 1000)
