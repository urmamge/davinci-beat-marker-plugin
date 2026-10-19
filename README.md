# DaVinci Beat Marker Plugin

Automatic beat markers for DaVinci Resolve. Pick a song on your timeline and the plugin detects its beats and bars, then places colour-coded markers **on the song clip itself**, so they move with the song if you slide it around. Turn on snapping and your cuts lock onto the beat.

- Markers on every beat, every 2 beats, every bar, every 2 or 4 bars, or every hit
- Downbeats (the "1" of each bar) get their own colour and are labelled `Bar 1`, `Bar 2`, … while other beats are labelled `3.2` (bar 3, beat 2)
- Half-time / double-time toggle, and a frame nudge for cutting slightly ahead of the beat
- Only touches its own markers: re-running replaces them, and **Clear Beat Markers** removes them without affecting yours
- Works in the **free** version of Resolve as well as Studio

Windows only for now.

---

## Setup

### 1. Install 64-bit Python

Resolve needs a 64-bit Python installed on the system to run Python scripts. If you don't have one, install Python 3.13 for all users. Either:

- run this in PowerShell (it will ask for admin permission):
  ```powershell
  winget install --id Python.Python.3.13 --scope machine --architecture x64
  ```
- or download the **Windows installer (64-bit)** from [python.org](https://www.python.org/downloads/windows/), and in the installer tick **"Use admin privileges"** and **"Add python.exe to PATH"**.

### 2. Download this plugin

Click **Code → Download ZIP** above and extract it anywhere, or clone it:

```powershell
git clone https://github.com/urmamge/davinci-beat-marker-plugin.git
```

### 3. Run the installer

Open PowerShell in the plugin folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

The installer:
- creates a private Python environment with the audio analysis library ([librosa](https://librosa.org)) in `%LOCALAPPDATA%\BeatMarkers`. It downloads about 150 MB and doesn't touch your other Python installs.
- adds the scripts to Resolve's menu (`%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\Beat Markers`)
- points Resolve at your 64-bit Python (sets the `PYTHON3HOME` user variable) if needed, so Resolve doesn't try to use a 32-bit or wrong Python

### 4. Restart Resolve

Close DaVinci Resolve completely and open it again. It only finds new scripts and settings at startup.

---

## How to use

### Add beat markers

1. Put your song on an audio track in your timeline.
2. Optionally, move the playhead over the song. If there are several audio clips, the one under the playhead is picked by default.
3. Go to **Workspace → Scripts → Beat Markers → Beat Markers**.
4. Choose your settings:

   | Setting | What it does |
   |---|---|
   | **Song** | Which audio clip on the timeline to analyse |
   | **Markers at** | Every beat · every 2 beats · every bar (downbeats) · every 2 bars · every 4 bars · every hit (drum hits and other transients) |
   | **Tempo feel** | *Half time* or *Double time*: use this if the markers come out twice as dense or twice as sparse as the song feels |
   | **Beat colour / Downbeat colour** | Marker colours |
   | **Nudge (frames)** | Shift every marker earlier (negative) or later. Cutting 1–2 frames early often feels tighter. |

5. Click **Add markers**. The first analysis of a song takes about 10–20 seconds, and after that it's cached and instant. A popup shows how many markers were added and the song's tempo (BPM).
6. Press **N** to turn on snapping. Clips and cuts now snap to the markers.

To try a different setting, just run it again. The old beat markers are replaced, and markers you added yourself are left alone. Your last-used settings are remembered.

### Remove beat markers

**Workspace → Scripts → Beat Markers → Clear Beat Markers** removes every marker the plugin added on the current timeline.

---

## Troubleshooting

All runs are logged to `%LOCALAPPDATA%\BeatMarkers\beatmarkers.log`. If something goes wrong, check there first.

| Problem | Fix |
|---|---|
| **Nothing happens when I click the script** | Resolve couldn't load a 64-bit Python. Make sure step 1 is done, re-run `install.ps1`, then fully restart Resolve. If it still does nothing, open **Workspace → Console**, click **Py3**, and look for an error. |
| **"Put the song on an audio track"** | The song must be in the *current* timeline on an audio track, as a normal clip (not inside a compound clip). |
| **Markers are shifted on a song I trimmed** | If every marker is off by exactly the amount you trimmed from the start, open `%LOCALAPPDATA%\BeatMarkers\config.json` and change `"marker_origin": "source"` to `"clip"`. |
| **Markers are twice as dense or sparse as the beat** | Use **Tempo feel → Half time / Double time**. |
| **Bars start on the wrong beat** | Downbeat detection is a heuristic based on kick drums. See *Better downbeats* below. |

### Better downbeats (optional)

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -BeatThis
```

This switches to [beat_this](https://github.com/CPJKU/beat_this), a neural beat and downbeat tracker. It's more accurate on difficult music but downloads PyTorch, about 1 GB.

### Uninstall

Delete `%LOCALAPPDATA%\BeatMarkers` and the `Beat Markers` folder in `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility`. If the installer set it, also remove the `PYTHON3HOME` user environment variable.

---

## How it works

```
Resolve (Scripts menu)              Plugin venv (%LOCALAPPDATA%\BeatMarkers\venv)
resolve_side.py  ── song list ──►  dialog.py   settings window
                                     └─► analyze.py   librosa: beats, downbeats, onsets (cached)
                 ◄── settings + beat times ──
adds markers to the song clip
```

- The code that runs inside Resolve uses only the Python standard library, so Resolve's Python needs nothing extra installed.
- The settings window is a small Tk window, because Resolve's built-in UI toolkit isn't available to scripts in the free version.
- Beat times are detected with librosa's beat tracker and then snapped onto the nearest detected attack, to within about 10 ms, well under a frame. Downbeats are picked as the bar position with the strongest low-frequency (kick) energy.
- Markers are converted from song time to frames using the clip's trim, so only beats inside the visible part of the clip get a marker.

## Development

```powershell
python -m unittest discover tests   # uses a fake Resolve object model, no Resolve needed
```

After editing, re-run `install.ps1` to copy your changes into Resolve. No restart is needed for code changes.

## License

MIT, see [LICENSE](LICENSE).
