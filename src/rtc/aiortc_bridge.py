"""Browser-shaped peer boundary around aiortc."""

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.sdp import candidate_from_sdp, candidate_to_sdp

from ..events import Event, EventTarget
from .audio import LocalAudioStream


def candidate_from_json(value: dict):
    text = value["candidate"]
    if text.startswith("candidate:"):
        text = text[len("candidate:"):]
    candidate = candidate_from_sdp(text)
    candidate.sdpMid = value.get("sdpMid")
    candidate.sdpMLineIndex = value.get("sdpMLineIndex")
    if candidate.sdpMid is None and candidate.sdpMLineIndex is None:
        raise ValueError("ICE candidate needs sdpMid or sdpMLineIndex")
    return candidate


def candidate_to_json(candidate) -> dict:
    return {
        "candidate": "candidate:" + candidate_to_sdp(candidate),
        "sdpMid": candidate.sdpMid,
        "sdpMLineIndex": candidate.sdpMLineIndex,
    }


class AiortcBridge(EventTarget):
    def __init__(self, ice_servers, *, peer_factory=None):
        super().__init__()
        servers = [RTCIceServer(
            urls=entry["urls"],
            username=entry.get("username"),
            credential=entry.get("credential"),
        ) for entry in ice_servers]
        factory = peer_factory or RTCPeerConnection
        self._peer = factory(RTCConfiguration(iceServers=servers))
        if hasattr(self._peer, "on"):
            self._peer.on("track", self._onTrack)
            # aiortc does not expose browser-style trickle events. Candidates
            # are included in its gathered localDescription instead.

    @property
    def localDescription(self) -> dict | None:
        description = getattr(self._peer, "localDescription", None)
        if description is None:
            return None
        return {"type": description.type, "sdp": description.sdp}

    def addTrack(self, track, stream=None) -> None:
        self._peer.addTrack(track)

    def localCandidates(self) -> list[dict]:
        """Expose gathered SDP candidates as browser-style signaling frames.

        aiortc gathers during setLocalDescription and doesn't emit the browser's
        icecandidate event. Keep its complete SDP and also send separate frames,
        as the original SDK does for candidate signaling.
        """
        description = self.localDescription
        if description is None:
            return []
        result = []
        mid = None
        index = -1
        candidates = []

        def flush():
            for text in candidates:
                result.append({"candidate": text, "sdpMid": mid, "sdpMLineIndex": index})

        for line in description["sdp"].splitlines():
            if line.startswith("m="):
                if index >= 0:
                    flush()
                index += 1
                mid = None
                candidates = []
            elif line.startswith("a=mid:"):
                mid = line[len("a=mid:"):]
            elif line.startswith("a=candidate:"):
                candidates.append(line[len("a="):])
        if index >= 0:
            flush()
        return result

    async def createOffer(self) -> dict:
        offer = await self._peer.createOffer()
        return {"type": offer.type, "sdp": offer.sdp}

    async def setLocalDescription(self, offer: dict) -> None:
        await self._peer.setLocalDescription(RTCSessionDescription(**offer))

    async def setRemoteDescription(self, answer: dict) -> None:
        await self._peer.setRemoteDescription(RTCSessionDescription(**answer))

    async def addIceCandidate(self, value: dict) -> None:
        if value is None or not value.get("candidate"):
            await self._peer.addIceCandidate(None)
        else:
            await self._peer.addIceCandidate(candidate_from_json(value))

    async def close(self) -> None:
        await self._peer.close()

    def _onTrack(self, track) -> None:
        # aiortc's track event has no MediaStream grouping; supply the one-track
        # stream shape consumed by the browser-facing CallsConnection event.
        self.dispatchEvent(Event("track", {"track": track, "streams": [LocalAudioStream(track)]}))

    async def getStats(self):
        return await self._peer.getStats()
