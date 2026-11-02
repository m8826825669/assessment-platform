"""Guard against false acceptance and accidental use of production configuration."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
spec = importlib.util.spec_from_file_location("assessment_verify", SCRIPTS / "verify.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


@pytest.mark.parametrize(
    "attributes",
    [
        'tests="0" failures="0" errors="0" skipped="0"',
        'tests="2" failures="0" errors="0" skipped="1"',
        'tests="2" failures="1" errors="0" skipped="0"',
        'tests="2" failures="0" errors="1" skipped="0"',
    ],
)
def test_gate_rejects_empty_incomplete_or_failed_results(tmp_path, attributes):
    junit = tmp_path / "junit.xml"
    junit.write_text(f"<testsuites><testsuite {attributes}/></testsuites>", encoding="utf-8")
    with pytest.raises(ValueError):
        verify.test_counts(junit)


def test_gate_aggregates_all_test_suites(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite tests="2"/><testsuite tests="3"/></testsuites>', encoding="utf-8"
    )
    assert verify.test_counts(junit) == {"tests": 5, "failures": 0, "errors": 0, "skipped": 0}


def test_full_gate_requires_explicit_database_creation_consent(monkeypatch):
    monkeypatch.delenv("ASSESSMENT_ALLOW_TEST_DATABASE_CREATION", raising=False)
    with pytest.raises(ValueError, match="ASSESSMENT_ALLOW_TEST_DATABASE_CREATION"):
        verify.test_environment(False, False)


def test_full_gate_requires_admin_url(monkeypatch):
    monkeypatch.setenv("ASSESSMENT_ALLOW_TEST_DATABASE_CREATION", "1")
    monkeypatch.delenv("ASSESSMENT_TEST_ADMIN_URL", raising=False)
    with pytest.raises(ValueError, match="ASSESSMENT_TEST_ADMIN_URL"):
        verify.test_environment(False, False)


def test_failure_report_does_not_contain_configuration_secrets(tmp_path, monkeypatch, capsys):
    (tmp_path / "backend").mkdir()
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    monkeypatch.setattr(verify, "BACKEND", tmp_path / "backend")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(verify.sys, "argv", ["verify.py"])

    def invalid_settings(*args):
        raise ValueError("postgresql://user:secret-password@private-db/assessment")

    monkeypatch.setattr(verify, "test_environment", invalid_settings)
    assert verify.main() == 1
    report = (tmp_path / "artifacts/verification.json").read_text()
    assert json.loads(report)["status"] == "failed"
    assert "secret-password" not in report + capsys.readouterr().out


def test_gate_stops_on_a_failed_stage(tmp_path, monkeypatch):
    (tmp_path / "backend").mkdir()
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    monkeypatch.setattr(verify, "BACKEND", tmp_path / "backend")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(verify.sys, "argv", ["verify.py", "--unit-only"])
    calls = []

    def fail(command, **kwargs):
        from types import SimpleNamespace

        calls.append(command)
        return SimpleNamespace(returncode=9)

    monkeypatch.setattr(verify.subprocess, "run", fail)
    assert verify.main() == 1
    assert len(calls) == 1
    report = json.loads((tmp_path / "artifacts/verification.json").read_text())
    assert report["stages"] == [{"name": "dependency-compatibility", "exit_code": 9}]
    assert report["status"] == "failed"
