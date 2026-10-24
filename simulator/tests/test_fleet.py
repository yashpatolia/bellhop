from bellhop_sim.fleet import FULL_BATTERY, LOW_BATTERY, Fleet, SimRobot


def test_a_flat_robot_goes_to_charge_and_returns_when_full():
    fleet = Fleet([SimRobot("b1", LOW_BATTERY + 0.01)])
    fleet.finish_call("b1")
    assert fleet.snapshot()[0].status == "charging"
    for _ in range(100):
        fleet.tick()
    r = fleet.snapshot()[0]
    assert r.status == "idle" and r.battery >= FULL_BATTERY


def test_a_healthy_robot_stands_by_after_a_call():
    fleet = Fleet([SimRobot("b1", 0.9)])
    fleet.set("b1", status="busy", room="101")
    fleet.finish_call("b1")
    r = fleet.snapshot()[0]
    assert (r.status, r.room) == ("idle", "101")
