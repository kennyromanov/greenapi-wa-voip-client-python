"""src/lib/logger.ts behavior translated onto Python logging."""

import json
import logging

import pytest


@pytest.mark.contract
def test_j_serializes_json_and_falls_back_on_cycle(target):
    module = target("lib.logger")
    assert json.loads(module.j({"type": "state", "state": "idle"})) == {
        "type": "state", "state": "idle",
    }
    recursive = []
    recursive.append(recursive)
    assert isinstance(module.j(recursive), str)


@pytest.mark.adaptation
def test_debug_switch_uses_environment_instead_of_browser_local_storage(target, monkeypatch):
    module = target("lib.logger")
    monkeypatch.setenv("WA_LOG_DEBUG", "1")
    assert module.isDebugLogEnabled() is True
    monkeypatch.setenv("WA_LOG_DEBUG", "0")
    assert module.isDebugLogEnabled() is False


@pytest.mark.contract
def test_debug_message_factory_is_lazy_when_disabled(target, monkeypatch):
    module = target("lib.logger")
    monkeypatch.setenv("WA_LOG_DEBUG", "0")
    invoked = []
    logger = module.Logger("calls")
    logger.logDebugIfEnabled(lambda: invoked.append(True) or "secret")
    assert invoked == []


@pytest.mark.adaptation
def test_child_logger_keeps_prefix_and_uses_standard_logging(target, caplog):
    module = target("lib.logger")
    logger = module.Logger("calls").child("rtc")
    with caplog.at_level(logging.INFO):
        logger.info("connected")
    assert any("calls" in record.message and "rtc" in record.message
               and "connected" in record.message for record in caplog.records)


@pytest.mark.contract
def test_log_alias_and_debug_property_exist(target, monkeypatch):
    module = target("lib.logger")
    monkeypatch.setenv("WA_LOG_DEBUG", "1")
    logger = module.Logger("calls")
    assert logger.isDebugEnabled is True
    assert callable(logger.log)
    assert callable(logger.warn)
    assert callable(logger.error)
    assert callable(logger.debug)
