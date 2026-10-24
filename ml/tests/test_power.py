import subprocess

import pytest

from rover import power

BITS = {
    0: "undervoltage_now",
    1: "freq_capped_now",
    2: "throttled_now",
    3: "soft_temp_limit_now",
    16: "undervoltage_since_boot",
    17: "freq_capped_since_boot",
    18: "throttled_since_boot",
    19: "soft_temp_limit_since_boot",
}


@pytest.mark.parametrize("bit,name", BITS.items())
def test_each_bit_sets_only_its_flag(bit, name):
    got = power.parse_throttled(f"throttled=0x{1 << bit:x}")
    assert got[name] is True
    assert [k for k, v in got.items() if v is True] == [name]


def test_zero_is_all_clear():
    got = power.parse_throttled("throttled=0x0\n")
    assert set(BITS.values()) <= set(got)
    assert not any(got[n] for n in BITS.values())


def test_combined_value():
    got = power.parse_throttled("throttled=0x50005")
    assert got["undervoltage_now"] and got["throttled_now"]
    assert got["undervoltage_since_boot"] and got["throttled_since_boot"]
    assert not got["freq_capped_now"]


@pytest.mark.parametrize("raw", ["", "junk", "throttled=", "throttled=0xZZ", None])
def test_junk_gives_empty(raw):
    assert power.parse_throttled(raw) == {}


def test_read_power_uses_runner():
    def runner(cmd):
        assert cmd[:2] == ["vcgencmd", "get_throttled"]
        return "throttled=0x1\n"

    got = power.read_power(runner=runner, wifi_runner=lambda cmd: None)
    assert got["undervoltage_now"] is True
    assert got["wifi_rssi_dbm"] is None


def test_read_power_missing_command_is_none():
    def runner(cmd):
        raise FileNotFoundError

    assert power.read_power(runner=runner) is None


@pytest.mark.parametrize("exc", [OSError("x"), subprocess.TimeoutExpired("v", 1), RuntimeError()])
def test_read_power_never_raises(exc):
    def runner(cmd):
        raise exc

    assert power.read_power(runner=runner) is None


def test_read_power_unparseable_is_none():
    assert power.read_power(runner=lambda cmd: "garbage") is None


IW = """Connected to aa:bb:cc:dd:ee:ff (on wlan0)
\tSSID: hotspot
\tfreq: 2437
\tsignal: -61 dBm
\ttx bitrate: 72.2 MBit/s
"""


def test_parse_rssi():
    assert power.parse_rssi(IW) == -61
    assert power.parse_rssi("Not connected.") is None
    assert power.parse_rssi("") is None


def test_read_power_includes_rssi():
    def wifi(cmd):
        assert cmd[:3] == ["iw", "dev", "wlan0"]
        return IW

    got = power.read_power(runner=lambda c: "throttled=0x0", wifi_runner=wifi)
    assert got["wifi_rssi_dbm"] == -61


def test_wifi_failure_is_none_not_error():
    def wifi(cmd):
        raise FileNotFoundError

    got = power.read_power(runner=lambda c: "throttled=0x0", wifi_runner=wifi)
    assert got["wifi_rssi_dbm"] is None


def test_power_health():
    assert power.power_health(None) == "ok"
    assert power.power_health(power.parse_throttled("throttled=0x0")) == "ok"
    assert power.power_health(power.parse_throttled("throttled=0x1")) == "fault"
    assert power.power_health(power.parse_throttled("throttled=0x10000")) == "warn"
    assert power.power_health(power.parse_throttled("throttled=0x20000")) == "warn"
    assert power.power_health(power.parse_throttled("throttled=0x2")) == "warn"
    assert power.power_health(power.parse_throttled("throttled=0x50005")) == "fault"
    assert power.power_health({}) == "ok"
