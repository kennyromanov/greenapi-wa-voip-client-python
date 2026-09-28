"""Small future seam for aiortc; protocol compatibility gets separate tests later."""

import pytest


class FakePeer:
    def __init__(self, configuration):
        self.configuration = configuration
        self.calls = []
        self.closed = False

    def addTrack(self, track):
        self.calls.append(("addTrack", track))

    async def createOffer(self):
        self.calls.append(("createOffer", None))
        return type("Description", (), {"type": "offer", "sdp": "v=0\r\n"})()

    async def setLocalDescription(self, description):
        self.calls.append(("setLocalDescription", description))

    async def setRemoteDescription(self, description):
        self.calls.append(("setRemoteDescription", description))

    async def addIceCandidate(self, candidate):
        self.calls.append(("addIceCandidate", candidate))

    async def close(self):
        self.calls.append(("close", None))
        self.closed = True


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_bridge_creates_peer_from_returned_ice_servers(target):
    module = target("rtc.aiortc_bridge")
    peers = []

    def make_peer(configuration):
        peer = FakePeer(configuration)
        peers.append(peer)
        return peer

    bridge = module.AiortcBridge(
        [{"urls": ["stun:one.test", "turn:two.test"], "username": "u", "credential": "p"}],
        peer_factory=make_peer,
    )
    assert len(peers) == 1
    servers = peers[0].configuration.iceServers
    assert len(servers) == 1
    assert servers[0].urls == ["stun:one.test", "turn:two.test"]
    assert servers[0].username == "u"
    assert servers[0].credential == "p"
    await bridge.close()


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_offer_and_answer_cross_json_boundary(target):
    module = target("rtc.aiortc_bridge")
    peers = []

    def make_peer(configuration):
        peer = FakePeer(configuration)
        peers.append(peer)
        return peer

    bridge = module.AiortcBridge([], peer_factory=make_peer)
    offer = await bridge.createOffer()
    await bridge.setLocalDescription(offer)
    await bridge.setRemoteDescription({"type": "answer", "sdp": "v=0\r\n"})

    assert offer == {"type": "offer", "sdp": "v=0\r\n"}
    assert peers[0].calls[0][0] == "createOffer"
    assert peers[0].calls[1][1].type == "offer"
    assert peers[0].calls[2][1].type == "answer"
    await bridge.close()
    assert peers[0].closed is True


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_track_is_forwarded_to_peer_without_media_transformation(target):
    module = target("rtc.aiortc_bridge")
    peer = FakePeer(configuration=None)
    bridge = module.AiortcBridge([], peer_factory=lambda configuration: peer)
    track = object()
    bridge.addTrack(track, stream=None)
    assert ("addTrack", track) in peer.calls
    await bridge.close()
