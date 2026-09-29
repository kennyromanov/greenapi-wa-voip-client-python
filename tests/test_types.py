"""Translation of src/types.ts, including absent optional JSON fields."""

import pytest


@pytest.mark.contract
def test_call_data_shapes(target):
    types = target("types")
    info = types.CallInfo(id="call-1", wid="100@lid", name="Ada")
    state = types.CallState(state="inc-call", info=info)

    assert (info.id, info.wid, info.name) == ("call-1", "100@lid", "Ada")
    assert state.state == "inc-call"
    assert state.info is info
    assert state.reason is None


@pytest.mark.contract
def test_options_preserve_ts_field_names(target):
    types = target("types")
    options = types.GreenApiVoipClientOptions(
        idInstance="123",
        apiTokenInstance="secret",
        apiUrl="https://example.test",
    )
    assert (options.idInstance, options.apiTokenInstance, options.apiUrl) == (
        "123", "secret", "https://example.test",
    )


@pytest.mark.contract
def test_call_state_kind_has_exact_protocol_values(target):
    from typing import get_args

    types = target("types")
    assert set(get_args(types.CallStateKind)) == {
        "idle", "inc-call", "out-call", "on-call",
    }


@pytest.mark.contract
def test_idle_reason_keeps_unknown_server_word(target):
    types = target("types")
    state = types.CallState(state="idle", reason="rejected:custom-reason")
    assert state.reason == "rejected:custom-reason"


@pytest.mark.contract
def test_server_can_extend_call_info_without_breaking_known_fields(target):
    types = target("types")
    state = types.call_state_from_json({
        "state": "inc-call",
        "info": {"id": "call-1", "wid": "100@lid", "name": "Ada", "newServerField": "value"},
    })
    assert (state.info.id, state.info.wid, state.info.name) == ("call-1", "100@lid", "Ada")
