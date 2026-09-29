"""Local aiortc smoke test; no Green-API account or hardware is needed."""

import asyncio

import pytest
from aiortc import AudioStreamTrack

from greenapi_wa_voip_client.rtc.aiortc_bridge import AiortcBridge, candidate_from_json, candidate_to_json


@pytest.mark.adaptation
@pytest.mark.asyncio
async def test_two_real_peers_exchange_audio_offer_and_answer():
    caller = AiortcBridge([])
    callee = AiortcBridge([])
    caller.addTrack(AudioStreamTrack())
    callee.addTrack(AudioStreamTrack())
    try:
        offer = await caller.createOffer()
        try:
            await caller.setLocalDescription(offer)
        except PermissionError:
            pytest.skip("Sandbox does not allow aiortc to enumerate network interfaces")
        local_offer = caller.localDescription
        assert local_offer["type"] == "offer"
        assert "a=candidate:" in local_offer["sdp"]
        assert caller.localCandidates()
        assert all(item["candidate"].startswith("candidate:") for item in caller.localCandidates())
        await callee.setRemoteDescription(local_offer)
        answer = await callee._peer.createAnswer()
        await callee._peer.setLocalDescription(answer)
        await caller.setRemoteDescription(callee.localDescription)
        await asyncio.wait_for(_connected(caller, callee), 10)
    finally:
        await caller.close()
        await callee.close()


async def _connected(caller, callee):
    while caller._peer.connectionState != "connected" or callee._peer.connectionState != "connected":
        await asyncio.sleep(0.05)


@pytest.mark.adaptation
def test_browser_candidate_json_round_trips():
    source = {
        "candidate": "candidate:1 1 udp 2122260223 192.0.2.1 54000 typ host",
        "sdpMid": "0", "sdpMLineIndex": 0,
    }
    candidate = candidate_from_json(source)
    assert candidate_to_json(candidate) == source
