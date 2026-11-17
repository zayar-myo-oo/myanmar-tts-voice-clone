from myanmar_voice_studio.doctor import Check, Report, command_check


def test_optional_desktop_dependencies_do_not_block_ml_gate():
    report = Report(timestamp="test", platform="test", checks=[
        Check(name="cpu", passed=True, detail="ok"),
        Check(name="rust", passed=False, detail="missing", required=False),
    ])
    assert report.passed
    report.checks.append(Check(name="audio", passed=False, detail="broken"))
    assert not report.passed


def test_missing_executable_is_reported(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    check = command_check("missing", ["--version"])
    assert not check.passed
    assert check.detail == "Not on PATH"
