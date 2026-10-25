#!/usr/bin/env python3
"""Read the GPIO-wired Yahboom PS2 receiver without touching rover motors.

Run on the Pi after wiring CLK/CMD/ATT/DAT to GPIO11/10/8/9 and disabling kernel SPI:
    .venv/bin/python scripts/test_ps2.py
"""

from __future__ import annotations

import time

from rover import config


def main() -> None:
    import board
    from ps2controller import PS2Controller

    ps2 = PS2Controller(
        clk=getattr(board, config.PS2_CLK_PIN),
        cmd=getattr(board, config.PS2_CMD_PIN),
        att=getattr(board, config.PS2_ATT_PIN),
        dat=getattr(board, config.PS2_DAT_PIN),
    )
    print("PS2 input test only: no motors are opened. Ctrl-C to stop.")
    linked: bool | None = None
    last_sticks: tuple[int, ...] | None = None
    try:
        while True:
            events = ps2.update()
            connected = events is not None
            if connected != linked:
                print("PS2 connected" if connected else "PS2 link down (receiver LED should be solid)")
                linked = connected
            if connected:
                for event in events:
                    edge = "pressed" if event.pressed else "released"
                    print(f"{event.name}: {edge}")
                sticks = tuple(ps2.analog_left() + ps2.analog_right())
                if last_sticks is None or max(abs(a - b) for a, b in zip(sticks, last_sticks)) > 8:
                    last_sticks = sticks
                    print(f"sticks L={sticks[:2]} R={sticks[2:]}")
            time.sleep(config.PS2_POLL_S)
    except KeyboardInterrupt:
        print("PS2 input test stopped; no motors were started.")


if __name__ == "__main__":
    main()
