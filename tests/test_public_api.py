"""Package root exports and GreenApiVoipClient commands."""

import importlib

import pytest

from tests.fakes import FakeRest


@pytest.mark.contract
def test_package_root_exports_only_the_ts_entrypoint():
    package = importlib.import_module("greenapi_wa_voip_client")
    expected = {
        "CallInfo", "CallState", "CallStateKind", "GreenApiVoipClientOptions",
        "GreenApiVoipClient", "CallsConnection", "CallsConnectionEventMap",
    }
    assert expected <= set(package.__all__)
    assert all(hasattr(package, name) for name in expected)
    assert "GreenApiRestClient" not in package.__all__
    assert "ReconnectingSocket" not in package.__all__


@pytest.mark.contract
@pytest.mark.asyncio
async def test_client_maps_every_rest_command(target, monkeypatch):
    module = target("green_api_voip_client")
    rest = FakeRest()
    monkeypatch.setattr(module, "GreenApiRestClient", lambda options: rest)
    client = module.GreenApiVoipClient({
        "idInstance": "123", "apiTokenInstance": "secret", "apiUrl": "https://example.test",
    })

    assert (await client.getCallState()).state == "idle"
    assert await client.getIceServers() == [{"urls": "stun:example.test"}]
    await client.dial("79991234567")
    await client.dial("100@lid")
    await client.accept()
    await client.reject()
    await client.hangUp()

    assert rest.calls == [
        ("GET", "callsState"),
        ("GET", "callsGetIceServers"),
        ("POST", "callsDial", {"chatId": "79991234567@c.us"}),
        ("POST", "callsDial", {"chatId": "100@lid"}),
        ("POST", "callsAccept", None),
        ("POST", "callsReject", None),
        ("POST", "callsHangUp", None),
    ]


@pytest.mark.contract
@pytest.mark.asyncio
async def test_dial_does_not_rewrite_any_target_containing_at(target, monkeypatch):
    module = target("green_api_voip_client")
    rest = FakeRest()
    monkeypatch.setattr(module, "GreenApiRestClient", lambda options: rest)
    client = module.GreenApiVoipClient({
        "idInstance": "123", "apiTokenInstance": "secret", "apiUrl": "https://example.test",
    })
    await client.dial("100@unexpected")
    assert rest.calls == [("POST", "callsDial", {"chatId": "100@unexpected"})]


@pytest.mark.contract
def test_connect_calls_creates_a_new_connection_each_time(target, monkeypatch):
    module = target("green_api_voip_client")
    rest = FakeRest()
    made = []
    monkeypatch.setattr(module, "GreenApiRestClient", lambda options: rest)

    def make_connection(argument):
        made.append(argument)
        return object()

    monkeypatch.setattr(module, "CallsConnection", make_connection)
    client = module.GreenApiVoipClient({
        "idInstance": "123", "apiTokenInstance": "secret", "apiUrl": "https://example.test",
    })
    first, second = client.connectCalls(), client.connectCalls()
    assert first is not second
    assert made == [rest, rest]
