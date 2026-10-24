import re
from datetime import UTC

from bellhop.adapters.system import SystemClock, UuidIds


def test_system_clock_is_timezone_aware_utc():
    assert SystemClock().now().tzinfo is UTC


def test_uuid_ids_use_prefix_and_8_hex():
    ids = UuidIds()
    first, second = ids.new_id("call"), ids.new_id("call")
    assert re.fullmatch(r"call_[0-9a-f]{8}", first)
    assert first != second
