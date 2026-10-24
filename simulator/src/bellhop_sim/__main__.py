"""bellhop-sim: seed a backend with the fictional home, then ring its bells.

bellhop-sim seed                    # staff, robots, residents and 14 days of history
bellhop-sim run --seed-home         # seed (if needed), then ring bells until Ctrl+C
bellhop-sim run --scene busy        # start with an emergency, nurse calls and a chat
bellhop-sim bell 104 --category fall
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys

from bellhop_sim import seeding
from bellhop_sim.client import Backend
from bellhop_sim.live import SCENES, Home, new_fleet, pick_scenario
from bellhop_sim.visit import Pace, VisitOptions


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bellhop-sim", description=__doc__.split("\n")[0])
    p.add_argument("--base-url", default=os.environ.get("BELLHOP_API", "http://127.0.0.1:8000"))
    p.add_argument("--api-key", default=os.environ.get("BELLHOP_API_KEY"))
    sub = p.add_subparsers(dest="cmd", required=True)

    seed = sub.add_parser("seed", help="fill the backend with the fictional home")
    seed.add_argument("--no-history", action="store_true", help="skip the past calls")

    run = sub.add_parser("run", help="ring bells and play the robot until stopped")
    run.add_argument("--seed-home", action="store_true", help="seed first (safe to repeat)")
    run.add_argument("--rate", type=float, default=1.5, help="bell presses per minute (0 = none)")
    run.add_argument(
        "--speed", type=float, default=1.0, help="1 is realistic, 5 is five times faster"
    )
    run.add_argument("--scene", choices=sorted(SCENES), help="start with a burst of calls")
    run.add_argument(
        "--nurse-delay",
        type=float,
        default=240.0,
        help="seconds before a nurse acknowledges; 0 leaves it to the dashboard",
    )
    run.add_argument("--duration", type=float, help="stop after this many seconds")
    run.add_argument("--random-seed", type=int, help="repeat the same run")

    bell = sub.add_parser("bell", help="ring one bell and play that visit")
    bell.add_argument("room", help="room number or resident id")
    bell.add_argument("--category", help="chat, pain, fall, ... (default: random)")
    bell.add_argument("--speed", type=float, default=1.0)
    bell.add_argument("--nurse-delay", type=float, default=240.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s sim: %(message)s", datefmt="%H:%M:%S"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    api = Backend(args.base_url, args.api_key)
    api.wait_ready()

    if args.cmd == "seed":
        done = seeding.seed_home(api, history=not args.no_history)
        print(f"seeded {done['residents']} residents and {done['calls']} past calls")
        return 0

    rng = random.Random(getattr(args, "random_seed", None))
    opts = VisitOptions(nurse_delay_s=args.nurse_delay)
    home = Home(api, Pace(args.speed), rng, new_fleet(), opts)

    if args.cmd == "bell":
        resident = home.resident(args.room)
        home.start()
        home.press(resident, pick_scenario(rng, args.category))
        home.join(timeout=3600)
        home.stop()
        home.heartbeat()  # report the robot idle again
        return 0

    if args.seed_home:
        done = seeding.seed_home(api)
        print(f"seeded {done['residents']} residents and {done['calls']} past calls")
    home.start()
    if args.scene:
        home.scene(args.scene)
    print(f"ringing bells, {args.rate}/min at speed {args.speed}. Ctrl+C to stop.")
    home.run(args.rate, args.duration)
    home.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
