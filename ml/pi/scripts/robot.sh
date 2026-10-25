#!/usr/bin/env bash
# Pi: the robot on its screen (eyes full screen, mic -> Claude -> Piper, games on touch).
# The Bellhop desktop icon runs "open". From SSH or the Pi Connect remote shell:
#   bash ~/ml/scripts/robot.sh open    # start the robot asleep: say "Hey Bellhop" to chat (wakes
#                                      # it if it is running), then, in a terminal, show the words
#   bash ~/ml/scripts/robot.sh close   # stop it (or swipe down from the top edge of the screen)
#   bash ~/ml/scripts/robot.sh words   # follow what each side says. Ctrl-X closes the robot too;
#                                      # Ctrl-C only stops watching
# A chat posts nothing to the backend and never drives. It goes back to sleep on goodbye or 20 s
# of quiet, never while a game is open. Asleep it waits for bells as usual, and a bell rung during
# a chat ends it. Asleep, Deepgram only hears the room while someone is talking.
# Everything it prints goes to ~/ml/runs/robot.log.
set -u
cd "$(dirname "$0")/.."
LOG=runs/robot.log
ROBOT="python.* -m rover\.speech"
mkdir -p runs

desktop_env() { # the Pi desktop's DISPLAY settings, read from its panel or desktop process
  local pid
  pid=$(pgrep -u "$(id -u)" -n 'wf-panel-pi|pcmanfm|lxpanel') || return 1
  tr '\0' '\n' <"/proc/$pid/environ" | grep -E '^(DISPLAY|WAYLAND_DISPLAY|XDG_RUNTIME_DIR)='
}

words() { # what each side says, from the last $1 lines of the log on
  echo "following $LOG (Ctrl-X: close the robot. Ctrl-C: stop watching, the robot keeps running)"
  # plus what goes wrong (fallbacks), games opening and closing, and Claude's tool calls
  tail -n "$1" -F "$LOG" |
    grep --line-buffered -E '^(resident|robot|wake|fallback): |^== |^games: [a-z_]+ (opened|closed)|^brain: tool ' &
  local view=$!
  trap 'pkill -P $$ -x tail 2>/dev/null' EXIT # only tail: the robot may be a child of this script
  if [[ ! -t 0 ]]; then
    wait "$view"
    return
  fi
  while IFS= read -rsn1 key; do # Ctrl-X is no signal, so read it as a key
    if [[ $key == $'\x18' ]]; then
      if pkill -TERM -f "$ROBOT"; then echo "closing the robot"; fi
      return
    fi
  done
}

case "${1:-open}" in
  open)
    if pkill -USR1 -f "$ROBOT"; then # running: wake it
      echo "woke the robot (nothing changes if it is already talking)"
      if [[ -t 1 ]]; then words 0; fi # in a terminal, not from the icon
      exit 0
    fi
    if [[ -z "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]]; then # a remote shell: use the Pi's own screen
      if settings=$(desktop_env); then
        # shellcheck disable=SC2046
        export $settings
      else
        echo "no desktop is running, so the eyes draw on the console screen"
      fi
    fi
    echo "== $(date '+%F %T') chat opened" >>"$LOG"
    setsid nohup .venv/bin/python -m rover.speech --chat >>"$LOG" 2>&1 </dev/null &
    echo 'opening: the eyes appear in a few seconds, then say "Hey Bellhop" to talk'
    if [[ -t 1 ]]; then words 0; fi # in a terminal, not from the icon
    ;;
  close)
    if pkill -TERM -f "$ROBOT"; then echo "closing"; else echo "the robot is not running"; fi
    ;;
  words)
    words 40
    ;;
  *)
    echo "usage: bash ~/ml/scripts/robot.sh open|close|words" >&2
    exit 2
    ;;
esac
