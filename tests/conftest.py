from __future__ import annotations

import importlib

import pytest

from tests.fakes import FakeAudioFactory, FakeBridgeFactory, FakeRest, FakeSocket


@pytest.fixture
def target():
    """Import on test execution so the intentionally red suite still collects."""

    def load(module: str):
        return importlib.import_module(f"greenapi_wa_voip_client.{module}")

    return load


@pytest.fixture
def calls_harness(target):
    class LazyHarness:
        """Create the target inside the test body, yielding a useful red failure."""

        values = None

        def __iter__(self):
            if self.values is None:
                module = target("calls_connection")
                socket = FakeSocket()
                rest = FakeRest()
                bridges = FakeBridgeFactory()
                audio = FakeAudioFactory()
                calls = module.CallsConnection(
                    rest,
                    socket=socket,
                    bridge_factory=bridges,
                    audio_factory=audio,
                )
                self.values = (calls, socket, rest, bridges, audio)
            return iter(self.values)

    return LazyHarness()
