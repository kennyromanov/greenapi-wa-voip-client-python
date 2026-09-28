"""Application example checks; no credentials or network are needed."""

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.adaptation
def test_run_help_is_available_without_client_implementation():
    result = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "--help"],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0
    assert "--api-url" in result.stdout
    assert "--id-instance" in result.stdout
    assert "--dial" in result.stdout


@pytest.mark.adaptation
def test_run_parser_preserves_explicit_call_parameters():
    import run

    args = run.build_parser().parse_args([
        "--api-url", "https://example.test",
        "--id-instance", "123",
        "--api-token-instance", "secret",
        "--dial", "100@lid",
    ])
    assert (args.api_url, args.id_instance, args.api_token_instance, args.dial) == (
        "https://example.test", "123", "secret", "100@lid",
    )


@pytest.mark.adaptation
def test_run_requires_credentials_before_attempting_a_call():
    import run

    with pytest.raises(SystemExit) as exc:
        run.main(["--dial", "100@lid"])
    assert "credential" in str(exc.value).lower()
