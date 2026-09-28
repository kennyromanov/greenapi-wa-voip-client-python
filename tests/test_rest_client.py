"""Translation of src/rest-client.ts: URL, method, body, response, error."""

import pytest

from tests.fakes import FakeHttpTransport, FakeResponse


def make_rest(target, *responses):
    module = target("rest_client")
    transport = FakeHttpTransport(*responses)
    rest = module.GreenApiRestClient(
        {"idInstance": "123", "apiTokenInstance": "secret", "apiUrl": "https://host.test///"},
        transport=transport,
    )
    return rest, transport


@pytest.mark.contract
def test_rest_and_websocket_urls_match_ts(target):
    rest, _ = make_rest(target)
    assert rest.buildUrl("callsDial") == (
        "https://host.test/waInstance123/callsDial/secret"
    )
    assert rest.buildWsUrl("callsRtc") == (
        "wss://host.test/waInstance123/callsRtc/secret"
    )


@pytest.mark.contract
@pytest.mark.parametrize("api_url, expected", [
    ("http://host.test", "ws://host.test/waInstance123/callsRtc/secret"),
    ("https://host.test", "wss://host.test/waInstance123/callsRtc/secret"),
])
def test_build_ws_url_changes_only_scheme(target, api_url, expected):
    module = target("rest_client")
    rest = module.GreenApiRestClient({
        "idInstance": "123", "apiTokenInstance": "secret", "apiUrl": api_url,
    }, transport=FakeHttpTransport())
    assert rest.buildWsUrl("callsRtc") == expected


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_parses_json_response(target):
    rest, transport = make_rest(target, FakeResponse(text='{"state":"idle"}'))
    assert await rest.get("callsState") == {"state": "idle"}
    assert transport.requests[0]["method"] == "GET"
    assert transport.requests[0]["url"].endswith("/callsState/secret")


@pytest.mark.contract
@pytest.mark.asyncio
async def test_post_with_body_sends_json_and_content_type(target):
    rest, transport = make_rest(target, FakeResponse(text='{"callId":"ignored"}'))
    await rest.post("callsDial", {"chatId": "100@lid"})
    request = transport.requests[0]
    assert request["method"] == "POST"
    assert request["url"].endswith("/callsDial/secret")
    assert request["headers"]["Content-Type"] == "application/json"
    assert request["json"] == {"chatId": "100@lid"}


@pytest.mark.contract
@pytest.mark.asyncio
async def test_post_without_body_has_no_json_header_or_body(target):
    rest, transport = make_rest(target, FakeResponse(status_code=204))
    assert await rest.post("callsAccept") is None
    request = transport.requests[0]
    assert request["method"] == "POST"
    assert "json" not in request
    assert "Content-Type" not in request.get("headers", {})


@pytest.mark.contract
@pytest.mark.asyncio
async def test_explicit_null_body_differs_from_omitted_body(target):
    rest, transport = make_rest(target, FakeResponse(status_code=204))
    await rest.post("callsExample", None)
    request = transport.requests[0]
    assert "json" in request and request["json"] is None
    assert request["headers"]["Content-Type"] == "application/json"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_empty_success_response_returns_none(target):
    rest, _ = make_rest(target, FakeResponse(status_code=200, text=""))
    assert await rest.get("callsState") is None


@pytest.mark.contract
@pytest.mark.asyncio
async def test_http_error_keeps_method_status_and_body(target):
    rest, _ = make_rest(target, FakeResponse(status_code=403, text="forbidden"))
    with pytest.raises(Exception, match=r"callsDial failed: 403 forbidden"):
        await rest.post("callsDial", {"chatId": "100@lid"})


@pytest.mark.contract
@pytest.mark.asyncio
async def test_invalid_json_is_not_silently_accepted(target):
    rest, _ = make_rest(target, FakeResponse(text="not-json"))
    with pytest.raises(ValueError):
        await rest.get("callsState")
