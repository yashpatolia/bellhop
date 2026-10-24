import importlib.util
import sys
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "doctor", Path(__file__).resolve().parents[1] / "pi" / "scripts" / "doctor.py"
)
doctor = importlib.util.module_from_spec(SPEC)
sys.modules["doctor"] = doctor  # dataclasses looks its module up here
SPEC.loader.exec_module(doctor)


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def date_now(offset_s=0.0):
    return format_datetime(datetime.now(UTC) + timedelta(seconds=offset_s), usegmt=True)


def test_python_version():
    assert doctor.check_python((3, 11, 4))[0] == doctor.OK
    assert doctor.check_python((3, 13, 5))[0] == doctor.OK
    for unsupported in ((3, 10, 12), (3, 12, 0)):
        status, detail = doctor.check_python(unsupported)
        assert status == doctor.FAIL and "3.11" in detail and "3.13" in detail


def test_packages_report_missing_and_versions():
    import importlib.metadata as md

    def version_of(dist):
        if dist == "nope":
            raise md.PackageNotFoundError(dist)
        return "1.2.3"

    assert doctor.check_packages({"a": "alpha", "b": "beta"}, version_of) == (
        doctor.OK,
        "alpha 1.2.3, beta 1.2.3",
    )
    status, detail = doctor.check_packages({"a": "alpha", "n": "nope"}, version_of)
    assert status == doctor.FAIL and "nope" in detail


def test_real_package_list_is_installed_here():
    assert doctor.check_packages()[0] == doctor.OK


def test_keys_are_reported_by_presence_only():
    secret = "sk-ant-very-secret-value"
    results = doctor.check_keys({"ANTHROPIC_API_KEY": secret, "DEEPGRAM_API_KEY": ""})
    by_name = {r.name: r for r in results}
    assert by_name["key ANTHROPIC_API_KEY"].status == doctor.OK
    assert by_name["key DEEPGRAM_API_KEY"].status == doctor.FAIL
    assert by_name["key TYPESAFE_API_KEY"].status == doctor.SKIPPED  # optional
    assert secret not in repr(results)


def test_clock_skew_from_the_date_header():
    now = datetime(2026, 10, 24, 12, 0, 30, tzinfo=UTC)
    header = format_datetime(datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC), usegmt=True)
    assert doctor.clock_skew_s(header, now) == 30.0
    assert doctor.clock_skew_s(header, now, rtt_s=2.0) == 29.0
    with pytest.raises(ValueError):
        doctor.clock_skew_s(None, now)
    assert doctor.skew_result(1.0)[0] == doctor.OK
    assert doctor.skew_result(-30.0)[0] == doctor.FAIL


def backend_handler(key=None):
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"}, headers={"date": date_now()})
        if key is not None and request.headers.get("x-api-key") != key:
            return httpx.Response(401, json={"detail": "missing or invalid X-API-Key"})
        return httpx.Response(200, json=[])

    return handler


def test_backend_with_a_valid_key():
    reach, auth, clock = doctor.check_backend(client(backend_handler("k")), "http://b", "k")
    assert (reach.status, auth.status, clock.status) == (doctor.OK,) * 3


def test_backend_rejects_a_wrong_or_missing_key():
    _, auth, _ = doctor.check_backend(client(backend_handler("k")), "http://b", "wrong")
    assert auth.status == doctor.FAIL and "wrong" in auth.detail
    _, auth, _ = doctor.check_backend(client(backend_handler("k")), "http://b", "")
    assert auth.status == doctor.FAIL and "not set" in auth.detail


def test_open_backend_needs_no_key():
    _, auth, _ = doctor.check_backend(client(backend_handler(None)), "http://b", "")
    assert auth.status == doctor.OK


def test_backend_clock_far_off_fails():
    def handler(request):
        return httpx.Response(200, json=[], headers={"date": date_now(-600)})

    _, _, clock = doctor.check_backend(client(handler), "http://b", "")
    assert clock.status == doctor.FAIL


def test_unreachable_backend_skips_the_dependent_checks():
    def handler(request):
        raise httpx.ConnectError("refused")

    reach, auth, clock = doctor.check_backend(client(handler), "http://b", "k")
    assert reach.status == doctor.FAIL
    assert auth.status == clock.status == doctor.SKIPPED


def test_pi_server_snapshot():
    snap = {"room": "lobby", "mode": "idle", "moving": False, "battery": 0.9, "led": "idle"}
    ok = doctor.check_pi_server(client(lambda r: httpx.Response(200, json=snap)), "http://pi")
    assert ok[0] == doctor.OK and "lobby" in ok[1]
    bad = doctor.check_pi_server(
        client(lambda r: httpx.Response(200, json={"room": "x"})), "http://pi"
    )
    assert bad[0] == doctor.FAIL and "battery" in bad[1]
    err = doctor.check_pi_server(client(lambda r: httpx.Response(500)), "http://pi")
    assert err[0] == doctor.FAIL

    def refuse(request):
        raise httpx.ConnectError("refused")

    assert doctor.check_pi_server(client(refuse), "http://pi")[0] == doctor.FAIL


def test_run_check_turns_crashes_and_hangs_into_fail(monkeypatch):
    def crash():
        raise RuntimeError("boom")

    result = doctor.run_check("x", crash)
    assert (result.name, result.status) == ("x", doctor.FAIL) and "boom" in result.detail
    monkeypatch.setattr(doctor, "DEVICE_TIMEOUT_S", 0.1)
    started = time.monotonic()
    hung = doctor.run_check("slow", lambda: time.sleep(2) or (doctor.OK, ""))
    assert hung.status == doctor.FAIL and time.monotonic() - started < 1.5


@pytest.mark.parametrize(
    "check",
    ["check_camera", "check_mic", "check_speaker", "check_adc", "check_ultrasonic"],
)
def test_hardware_checks_never_crash_without_hardware(check, monkeypatch):
    monkeypatch.setattr(doctor, "DEVICE_TIMEOUT_S", 20)
    result = doctor.run_check(check, getattr(doctor, check))
    assert result.status in (doctor.OK, doctor.FAIL, doctor.SKIPPED)
    assert "Traceback" not in result.detail
