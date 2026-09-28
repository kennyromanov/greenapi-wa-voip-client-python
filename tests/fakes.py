"""Deterministic boundary fakes; no fake implements the SDK's call state machine."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    type: str
    detail: Any = None


@dataclass
class FakeResponse:
    status_code: int = 200
    text: str = ""

    def json(self) -> Any:
        return json.loads(self.text)


class FakeHttpTransport:
    def __init__(self, *responses: FakeResponse):
        self.responses = deque(responses)
        self.requests: list[dict[str, Any]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        return self.responses.popleft()


class FakeRest:
    def __init__(self, ice_servers: list[dict[str, Any]] | None = None):
        self.calls: list[tuple[str, Any]] = []
        self.ice_servers = ice_servers if ice_servers is not None else [{"urls": "stun:example.test"}]

    def buildWsUrl(self, method: str) -> str:
        self.calls.append(("buildWsUrl", method))
        return f"wss://example.test/{method}"

    async def get(self, method: str) -> Any:
        self.calls.append(("GET", method))
        if method == "callsGetIceServers":
            return self.ice_servers
        if method == "callsState":
            return {"state": "idle"}
        raise AssertionError(f"Unexpected GET: {method}")

    async def post(self, method: str, body: Any = None) -> None:
        self.calls.append(("POST", method, body))


class FakeSocket:
    """Already-connected high-level socket for CallsConnection unit tests."""

    def __init__(self):
        self.listeners: dict[str, list[Any]] = defaultdict(list)
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def addEventListener(self, name: str, callback: Any) -> None:
        self.listeners[name].append(callback)

    def removeEventListener(self, name: str, callback: Any) -> None:
        self.listeners[name].remove(callback)

    async def send(self, frame: dict[str, Any]) -> None:
        self.sent.append(frame)

    async def close(self) -> None:
        self.closed = True

    async def emit(self, name: str, detail: Any = None) -> None:
        for callback in list(self.listeners[name]):
            result = callback(Event(name, detail))
            if inspect.isawaitable(result):
                await result
        await asyncio.sleep(0)

    async def receive(self, frame: dict[str, Any]) -> None:
        await self.emit("message", frame)


class FakeTrack:
    def __init__(self):
        self.kind = "audio"
        self.enabled = True
        self.readyState = "live"
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True
        self.readyState = "ended"


class FakeStream:
    def __init__(self):
        self.track = FakeTrack()

    def getTracks(self) -> list[FakeTrack]:
        return [self.track]

    def getAudioTracks(self) -> list[FakeTrack]:
        return [self.track]


class FakeAudioFactory:
    def __init__(self):
        self.streams: list[FakeStream] = []

    async def __call__(self) -> FakeStream:
        stream = FakeStream()
        self.streams.append(stream)
        return stream


class FakeBridge:
    """Browser-shaped peer boundary; deliberately no ICE or RTP simulation."""

    def __init__(self, ice_servers: Any = None):
        self.ice_servers = ice_servers
        self.events: dict[str, Any] = {}
        self.tracks: list[tuple[FakeTrack, FakeStream]] = []
        self.calls: list[tuple[str, Any]] = []
        self.offer = {"type": "offer", "sdp": "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"}
        self.closed = False

    def addTrack(self, track: FakeTrack, stream: FakeStream) -> None:
        self.tracks.append((track, stream))
        self.calls.append(("addTrack", track))

    def addEventListener(self, name: str, callback: Any) -> None:
        self.events[name] = callback

    async def createOffer(self) -> dict[str, str]:
        self.calls.append(("createOffer", None))
        return self.offer

    async def setLocalDescription(self, offer: dict[str, str]) -> None:
        self.calls.append(("setLocalDescription", offer))

    async def setRemoteDescription(self, answer: dict[str, str]) -> None:
        self.calls.append(("setRemoteDescription", answer))

    async def addIceCandidate(self, candidate: dict[str, Any]) -> None:
        self.calls.append(("addIceCandidate", candidate))

    async def close(self) -> None:
        self.calls.append(("close", None))
        self.closed = True

    async def emit(self, name: str, detail: Any) -> None:
        callback = self.events[name]
        result = callback(Event(name, detail))
        if inspect.isawaitable(result):
            await result


class FakeBridgeFactory:
    def __init__(self):
        self.bridges: list[FakeBridge] = []

    def __call__(self, ice_servers: Any) -> FakeBridge:
        bridge = FakeBridge(ice_servers)
        self.bridges.append(bridge)
        return bridge


@dataclass
class FakeClock:
    delays: list[float] = field(default_factory=list)
    pending: deque[asyncio.Future[None]] = field(default_factory=deque)

    async def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        future = asyncio.get_running_loop().create_future()
        self.pending.append(future)
        await future

    def advance(self) -> None:
        self.pending.popleft().set_result(None)


class FakeClosed(Exception):
    def __init__(self, code: int, reason: str = ""):
        super().__init__(reason)
        self.code = code
        self.reason = reason


class FakeRawWebSocket:
    """Low-level recv/send transport for ReconnectingSocket tests."""

    def __init__(self):
        self.incoming: asyncio.Queue[str | FakeClosed] = asyncio.Queue()
        self.sent: list[str] = []
        self.closed = False

    async def recv(self) -> str:
        item = await self.incoming.get()
        if isinstance(item, FakeClosed):
            raise item
        return item

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def close(self) -> None:
        self.closed = True

    def feed(self, text: str) -> None:
        self.incoming.put_nowait(text)

    def disconnect(self, code: int, reason: str = "") -> None:
        self.incoming.put_nowait(FakeClosed(code, reason))


class FakeRawSocketFactory:
    def __init__(self):
        self.sockets: list[FakeRawWebSocket] = []
        self.urls: list[str] = []

    async def __call__(self, url: str) -> FakeRawWebSocket:
        self.urls.append(url)
        socket = FakeRawWebSocket()
        self.sockets.append(socket)
        return socket


async def until(predicate: Any, *, turns: int = 30) -> None:
    """Advance scheduled tasks without wall-clock sleeps; fail if no progress."""
    for _ in range(turns):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("Expected async state was not reached")
