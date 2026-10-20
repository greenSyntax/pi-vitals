import subprocess

from app.collectors import health


def test_read_temperature(tmp_path):
    f = tmp_path / "temp"
    f.write_text("52345\n")
    assert health.read_temperature(str(f)) == 52.3


def test_read_temperature_missing_file(tmp_path):
    assert health.read_temperature(str(tmp_path / "nope")) is None


def test_read_temperature_garbage(tmp_path):
    f = tmp_path / "temp"
    f.write_text("hot")
    assert health.read_temperature(str(f)) is None


def test_parse_throttled_clean():
    result = health.parse_throttled("throttled=0x0\n")
    assert result["raw"] == "0x0"
    assert not any(v for k, v in result.items() if k != "raw")


def test_parse_throttled_flags():
    # bit 0 (under-voltage now) + bit 16 (under-voltage occurred) + bit 18 (throttled occurred)
    result = health.parse_throttled("throttled=0x50001\n")
    assert result["under_voltage"] is True
    assert result["under_voltage_occurred"] is True
    assert result["throttled_occurred"] is True
    assert result["throttled"] is False
    assert result["freq_capped"] is False


def test_parse_throttled_bad_output():
    assert health.parse_throttled("error") is None


def test_read_throttled_no_vcgencmd(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", boom)
    assert health.read_throttled() is None


def test_read_throttled_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="x"),
    )
    assert health.read_throttled() is None
