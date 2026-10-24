import pytest

from bellhop.adapters.memory_store import InMemoryStore
from bellhop.services.admin import (
    AdminService,
    Conflict,
    NurseNotFound,
    ResidentNotFound,
)


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def admin(store, clock, ids):
    return AdminService(store.residents, store.nurses, store.robots, store.calls, clock, ids)


def test_create_resident_generates_id_and_persists(admin, store):
    r = admin.create_resident(None, "Ada", "21", risk_flags=["falls"], birth_year=1940)
    assert r.id.startswith("res")
    assert store.residents.get(r.id).risk_flags == {"falls"}
    assert admin.get_resident(r.id).birth_year == 1940


def test_create_resident_keeps_given_id_and_lists(admin):
    admin.create_resident("res_a", "Ada", "21")
    admin.create_resident("res_b", "Bo", "22")
    assert {r.id for r in admin.list_residents()} == {"res_a", "res_b"}


def test_duplicate_id_is_conflict(admin):
    admin.create_resident("res_a", "Ada", "21")
    with pytest.raises(Conflict):
        admin.create_resident("res_a", "Other", "22")


def test_room_clash_is_conflict_with_clear_message(admin):
    admin.create_resident("res_a", "Ada", "21")
    with pytest.raises(Conflict, match="room 21"):
        admin.create_resident("res_b", "Bo", "21")


def test_conflict_is_a_value_error_and_not_found_is_lookup_error():
    assert issubclass(Conflict, ValueError)
    assert issubclass(ResidentNotFound, LookupError)
    assert issubclass(NurseNotFound, LookupError)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": ""},
        {"name": "x" * 81},
        {"room": ""},
        {"room": "r" * 33},
        {"id": "i" * 65},
        {"risk_flags": ["a"] * 11},
        {"risk_flags": [""]},
        {"risk_flags": ["f" * 33]},
    ],
)
def test_create_resident_validates(admin, kwargs):
    args = {"id": None, "name": "Ada", "room": "21", **kwargs}
    with pytest.raises(ValueError):
        admin.create_resident(**args)


def test_get_unknown_resident(admin):
    with pytest.raises(ResidentNotFound):
        admin.get_resident("nope")


def test_update_resident_fields(admin):
    admin.create_resident("res_a", "Ada", "21")
    r = admin.update_resident("res_a", name="Ada L", risk_flags=["dementia"], birth_year=1930)
    assert (r.name, r.risk_flags, r.birth_year) == ("Ada L", {"dementia"}, 1930)
    assert admin.get_resident("res_a").name == "Ada L"


def test_update_resident_room_move_and_same_room_ok(admin):
    admin.create_resident("res_a", "Ada", "21")
    admin.create_resident("res_b", "Bo", "22")
    assert admin.update_resident("res_a", room="21").room == "21"
    assert admin.update_resident("res_a", room="23").room == "23"
    with pytest.raises(Conflict):
        admin.update_resident("res_a", room="22")


def test_update_unknown_resident_or_field(admin):
    with pytest.raises(ResidentNotFound):
        admin.update_resident("nope", name="x")
    admin.create_resident("res_a", "Ada", "21")
    with pytest.raises(ValueError):
        admin.update_resident("res_a", id="other")
    with pytest.raises(ValueError):
        admin.update_resident("res_a", name="")


def test_nurses_create_update_list(admin):
    n = admin.create_nurse(None, "Priya")
    assert n.id.startswith("nurse") and n.on_shift
    admin.create_nurse("nurse_x", "Sam", on_shift=False)
    assert {x.id for x in admin.list_nurses()} == {n.id, "nurse_x"}
    with pytest.raises(Conflict):
        admin.create_nurse("nurse_x", "Dup")
    with pytest.raises(ValueError):
        admin.create_nurse(None, "")
    assert admin.update_nurse("nurse_x", name="Sam K", on_shift=True).on_shift
    with pytest.raises(NurseNotFound):
        admin.update_nurse("nope", on_shift=False)


def test_going_off_shift_never_changes_open_tasks(admin, store):
    nurse = admin.create_nurse("nurse_p", "Priya")
    nurse.open_tasks = 2
    store.nurses.save(nurse)
    off = admin.update_nurse("nurse_p", on_shift=False)
    assert off.on_shift is False and off.open_tasks == 2
    assert store.nurses.get("nurse_p").open_tasks == 2
