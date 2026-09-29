"""Call signaling and bridge lifecycle, translated from calls-connection.ts."""

import asyncio
from typing import Any, TypedDict

from .events import Event, EventTarget
from .reconnecting_socket import ReconnectingSocket
from .types import CallState, call_state_from_json

CALL_STATE_KINDS = frozenset(("inc-call", "out-call", "on-call"))


def isCallState(kind: str) -> bool:
    return kind in CALL_STATE_KINDS


CallsConnectionEventMap = TypedDict("CallsConnectionEventMap", {
    "connect": Event,
    "disconnect": Event,
    "state": Event,
    "incoming-call": Event,
    "end-call": Event,
    "local-stream-ready": Event,
    "remote-stream-ready": Event,
    "error": Event,
})


class CallsConnection(EventTarget):
    def __init__(self, rest, *, socket=None, bridge_factory=None, audio_factory=None):
        super().__init__()
        self._rest = rest
        self._socket = socket if socket is not None else ReconnectingSocket(rest.buildWsUrl("callsRtc"))
        self._bridge_factory = bridge_factory
        self._audio_factory = audio_factory
        self._state: CallState | None = None
        self._peerConnection = None
        self._localStream = None
        self._audioDevice = None
        self._pendingRemoteCandidates: list[dict] = []
        self._remoteDescriptionSet = False
        self._pendingBridge: asyncio.Future | None = None
        self._resumePending = False
        self._refusalReported = False
        self._closed = False
        self._resumeTask: asyncio.Task | None = None
        self._bridgeGeneration = 0
        self._socket.addEventListener("connect", lambda event: self.dispatchEvent(Event("connect")))
        self._socket.addEventListener("disconnect", lambda event: self._onSocketDisconnect(**event.detail))
        self._socket.addEventListener("message", lambda event: self._onMessage(event.detail))

    @property
    def state(self) -> CallState | None:
        return self._state

    @property
    def hasAudioBridge(self) -> bool:
        return self._peerConnection is not None

    async def startAudioBridge(self) -> None:
        if self._peerConnection is not None or self._pendingBridge is not None:
            raise RuntimeError("Audio bridge already starting or active")
        if self._closed:
            raise RuntimeError("CallsConnection is closed")
        self._pendingBridge = asyncio.get_running_loop().create_future()
        pending = self._pendingBridge
        try:
            await self._startAudioBridgeInternal(self._bridgeGeneration)
        except Exception as exc:
            if self._pendingBridge is pending:
                self._pendingBridge = None
                await self._teardownBridge(False)
                if not pending.done():
                    pending.set_exception(exc)
            # The pending Future is the single error channel for startup errors.
        await pending

    async def stopAudioBridge(self) -> None:
        self._resumePending = False
        self._rejectPending(RuntimeError("Audio bridge stopped"))
        await self._teardownBridge(True)

    async def close(self) -> None:
        self._closed = True
        self._resumePending = False
        self._rejectPending(RuntimeError("CallsConnection closed"))
        await self._teardownBridge(False)
        await self._socket.close()

    async def _startAudioBridgeInternal(self, generation: int) -> None:
        if self._audio_factory is None:
            from .rtc.audio import AudioDevice
            self._audioDevice = AudioDevice()
            localStream = await self._audioDevice.acquireLocal()
        else:
            localStream = await self._audio_factory()
        if generation != self._bridgeGeneration:
            for track in localStream.getTracks():
                track.stop()
            if self._audioDevice is not None:
                await self._audioDevice.close()
            return
        self._localStream = localStream
        self.dispatchEvent(Event("local-stream-ready", localStream))

        iceServers = await self._rest.get("callsGetIceServers")
        if generation != self._bridgeGeneration:
            return
        if self._bridge_factory is None:
            from .rtc.aiortc_bridge import AiortcBridge
            pc = AiortcBridge(iceServers)
        else:
            pc = self._bridge_factory(iceServers)
        self._peerConnection = pc
        self._remoteDescriptionSet = False
        self._pendingRemoteCandidates = []

        for track in localStream.getTracks():
            pc.addTrack(track, localStream)
        pc.addEventListener("icecandidate", self._onLocalCandidate)
        pc.addEventListener("track", self._onRemoteTrack)

        offer = await pc.createOffer()
        if generation != self._bridgeGeneration:
            return
        await pc.setLocalDescription(offer)
        if generation != self._bridgeGeneration:
            return
        # aiortc gathers in setLocalDescription; its current SDP is authoritative.
        if self._bridge_factory is None:
            offer = pc.localDescription or offer
        await self._socket.send({"type": "offer", "offer": offer})
        if self._bridge_factory is None:
            for candidate in pc.localCandidates():
                await self._socket.send({"type": "ice-candidate", "candidate": candidate})

    def _onLocalCandidate(self, event) -> Any:
        candidate = event.detail
        if isinstance(candidate, dict) and "candidate" in candidate:
            candidate = candidate["candidate"]
        if not candidate:
            return None
        if hasattr(candidate, "toJSON"):
            candidate = candidate.toJSON()
        return self._socket.send({"type": "ice-candidate", "candidate": candidate})

    def _onRemoteTrack(self, event) -> Any:
        value = event.detail
        stream = value.get("streams", [None])[0] if isinstance(value, dict) else value
        self.dispatchEvent(Event("remote-stream-ready", stream))
        if self._audioDevice is not None:
            track = value.get("track") if isinstance(value, dict) else None
            if track is not None:
                return self._audioDevice.attachRemote(track)
        return None

    async def _teardownBridge(self, notifyServer: bool) -> None:
        self._bridgeGeneration += 1
        pc, stream, audio = self._peerConnection, self._localStream, self._audioDevice
        self._peerConnection = None
        self._localStream = None
        self._audioDevice = None
        self._pendingRemoteCandidates = []
        self._remoteDescriptionSet = False
        try:
            if notifyServer and pc is not None:
                await self._socket.send({"type": "stop"})
        finally:
            if pc is not None:
                await pc.close()
            if stream is not None:
                for track in stream.getTracks():
                    track.stop()
            if audio is not None:
                await audio.close()

    def _rejectPending(self, exc: Exception) -> None:
        pending = self._pendingBridge
        self._pendingBridge = None
        if pending is not None and not pending.done():
            pending.set_exception(exc)

    async def _onMessage(self, message: dict) -> None:
        kind = message.get("type") if isinstance(message, dict) else None
        if kind == "state":
            await self._onState(call_state_from_json(message["state"]))
        elif kind == "answer":
            pc = self._peerConnection
            if pc is None:
                return
            try:
                await pc.setRemoteDescription(message["answer"])
                self._remoteDescriptionSet = True
                for candidate in self._pendingRemoteCandidates:
                    await pc.addIceCandidate(candidate)
                self._pendingRemoteCandidates = []
            except Exception as exc:
                self._rejectPending(exc)
                await self._teardownBridge(False)
                return
            pending = self._pendingBridge
            self._pendingBridge = None
            if pending is not None and not pending.done():
                pending.set_result(None)
        elif kind == "ice-candidate":
            if self._remoteDescriptionSet:
                if self._peerConnection is not None:
                    await self._peerConnection.addIceCandidate(message["candidate"])
            else:
                self._pendingRemoteCandidates.append(message["candidate"])
        elif kind == "error":
            if self._pendingBridge is not None:
                self._rejectPending(RuntimeError(message["message"]))
                await self._teardownBridge(False)
            else:
                self._refusalReported = True
                self.dispatchEvent(Event("error", {"message": message["message"]}))

    async def _onState(self, state: CallState) -> None:
        prevKind = self._state.state if self._state else None
        self._state = state
        self.dispatchEvent(Event("state", state))
        if state.state == "inc-call" and prevKind != "inc-call" and state.info is not None:
            self.dispatchEvent(Event("incoming-call", state.info))
            return
        if prevKind and isCallState(prevKind) and not isCallState(state.state):
            self._resumePending = False
            self._rejectPending(RuntimeError("Call ended during negotiation"))
            await self._teardownBridge(True)
            detail = {"reason": "call-ended"}
            if state.reason:
                detail["cause"] = state.reason
            self.dispatchEvent(Event("end-call", detail))
            return
        if self._resumePending and isCallState(state.state) and not self._peerConnection and not self._pendingBridge:
            self._resumePending = False
            self._resumeTask = asyncio.create_task(self._resumeAudioBridge())

    async def _resumeAudioBridge(self) -> None:
        try:
            await self.startAudioBridge()
        except Exception as exc:
            self.dispatchEvent(Event("error", {"message": str(exc)}))

    async def _onSocketDisconnect(self, reason: str, code: int | None = None, permanent: bool = False) -> None:
        prevKind = self._state.state if self._state else None
        if prevKind and isCallState(prevKind):
            self._resumePending = self._peerConnection is not None
            self._rejectPending(RuntimeError("Socket disconnected during negotiation"))
            await self._teardownBridge(False)
            if permanent:
                self._resumePending = False
            if not self._resumePending:
                self._state = None
                self.dispatchEvent(Event("end-call", {"reason": "connection-lost"}))
        else:
            self._state = None
        if permanent and not self._refusalReported:
            self.dispatchEvent(Event("error", {"message": reason}))
        self._refusalReported = False
        self.dispatchEvent(Event("disconnect", {"reason": reason, "code": code, "permanent": permanent}))
