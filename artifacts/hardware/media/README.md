# Hardware media

Photos, clips and figures for the [main README](../../../README.md) and the
[hardware build log](../README.md).

## Here

| File | What it is |
|---|---|
| `bellhop-sketch.svg` | Isometric sketch of the robot, made with Claude |
| `bellhop-hero.gif` | `IMG_3412.mov`, square crop, first 6.5 s |
| `bellhop-hero.jpg` | The robot on the venue floor, eyes lit |
| `front-detail.jpg`, `side-view.jpg`, `back-view.jpg` | Front, side and back photos (back trimmed to leave out a bystander) |
| `ps2-receiver.jpg` | Crop of the back photo |
| `eyes.gif` | `IMG_3407.mov`, first 1.8 s |
| `bellhop-demo.mp4` | The 90 second demo, captions burned in |
| `demo-drive.gif`, `demo-feelings.gif`, `demo-games.gif`, `demo-stories.gif`, `demo-nurse.gif` | Clips from the demo at 0:03, 0:21, 0:54, 1:05 and 1:17 |
| `nav-card.gif` | Demo 0:05 to 0:07, square crop of the robot driving |
| `edge-ai.svg` | What runs on the Pi and in the cloud |
| `autonav.svg` | The four navigation stages, from the values in `rover/config.py` |
| `visual-turn-method.svg` | The turn controller, simulated with the real `_align_marker_heading` |

Dashboard screenshots are in [`artifacts/dashboard/`](../../dashboard), taken from
`scripts/dev.sh mock`. The Devpost video is on [YouTube](https://www.youtube.com/watch?v=vnsqGMfTnL8);
its thumbnail is `artifacts/devpost/video-thumbnail.jpg`.

## Worth shooting

| File | What to capture |
|---|---|
| `visual-turn.gif` | The turn pulses close up, ideally beside `tail -f ~/ml/runs/drive.log` |
| `head-scan.gif` | The head sweeping its 7 pans and 3 tilts |
| `door-marker.jpg` | A marker on a door frame, from the robot's height |
| `robot-internals.jpg` | Top off: the Pi, driver board, battery and wiring |
| `vision-overlay.jpg` | What the robot sees: `cd ml/pi && uv run python -m rover.vision --source 0 --show` |

## Adding a file

- Export iPhone photos as JPEG; this machine has no HEIC converter.
- Strip location data: `ffmpeg -i in.jpg -map_metadata -1 -vf "scale=-1:1600" -q:v 3 out.jpg`.
- No real residents, and no close-ups of people who did not agree to be filmed.
- Keep GIFs under 5 MB. The main GIF was cut like this:

```bash
ffmpeg -t 6.5 -i IMG_3412.mov \
  -vf "crop=1000:1000:260:230,hqdn3d=6:6:8:8,fps=10,scale=440:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -loop 0 bellhop-hero.gif
```

GitHub does not play a repo `.mp4` inline. For a player, drag the file into the README editor on
github.com.
