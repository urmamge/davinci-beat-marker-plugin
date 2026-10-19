"""Runs inside DaVinci Resolve (Workspace > Scripts). Standard library only, Python 3.6+.

Talks to Resolve, hands the UI and audio analysis to dialog.py in the plugin's venv.
"""
import datetime
import json
import os
import subprocess
import tempfile
import traceback

from . import beats

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "BeatMarkers")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LOG_PATH = os.path.join(DATA_DIR, "beatmarkers.log")
DIALOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dialog.py")
TAG = "beatmarker"  # customData prefix on every marker we create
NO_WINDOW = 0x08000000

DEFAULT_CONFIG = {
    "python": os.path.join(DATA_DIR, "venv", "Scripts", "pythonw.exe"),
    "engine": "librosa",
    # Where TimelineItem marker frame 0 sits: "source" = first frame of the media file,
    # "clip" = first visible frame of the clip. Flip this if markers land shifted by the head trim.
    "marker_origin": "source",
}


class BeatMarkerError(Exception):
    pass


def log(text):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


def load_config():
    config = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config.update(json.load(f))
    except (OSError, ValueError):
        pass
    return config


# ---------------------------------------------------------------- helper process

def message(config, title, text, wait=False):
    print("[Beat Markers] %s: %s" % (title, text))
    log("%s: %s" % (title, text))
    if not os.path.exists(config["python"]):
        log("Can't show popup, missing %s" % config["python"])
        return
    proc = subprocess.Popen([config["python"], DIALOG, "message", title, text], creationflags=NO_WINDOW)
    if wait:
        proc.wait()


def ask(config, request):
    if not os.path.exists(config["python"]):
        raise BeatMarkerError("The Beat Markers Python environment is missing:\n%s\n\nRe-run install.ps1." % config["python"])
    request["engine"] = config["engine"]
    tmp = tempfile.mkdtemp(prefix="beatmarkers_")
    req_path, resp_path = os.path.join(tmp, "request.json"), os.path.join(tmp, "response.json")
    with open(req_path, "w", encoding="utf-8") as f:
        json.dump(request, f)
    log("Opening dialog (%d songs)" % len(request["songs"]))
    code = subprocess.call([config["python"], DIALOG, "ask", req_path, resp_path], creationflags=NO_WINDOW)
    log("Dialog exited with code %s" % code)
    try:
        with open(resp_path, encoding="utf-8") as f:
            response = json.load(f)
    except (OSError, ValueError):
        raise BeatMarkerError("The Beat Markers dialog closed unexpectedly.")
    if "error" in response:
        raise BeatMarkerError("Analysis failed:\n" + response["error"])
    return None if response.get("cancelled") else response


# ---------------------------------------------------------------- timeline helpers

def parse_fps(value):
    try:
        return float(str(value).split()[0])
    except (ValueError, IndexError):
        return 0.0


def playhead_frame(timeline, fps):
    try:
        parts = [int(p) for p in timeline.GetCurrentTimecode().replace(";", ":").split(":")]
        h, m, s, f = parts
        return ((h * 60 + m) * 60 + s) * int(round(fps)) + f
    except (ValueError, AttributeError):
        return None


def source_start_seconds(item, fps):
    try:
        t = item.GetSourceStartTime()
        if t is not None:
            return float(t)
    except Exception:
        pass
    return item.GetLeftOffset() / fps


class Song:
    def __init__(self, item, track, fps):
        self.item = item
        self.track = track
        self.fps = fps
        self.start = item.GetStart()                # absolute timeline frame
        self.duration = item.GetDuration()          # timeline frames
        self.src0 = source_start_seconds(item, fps)  # seconds trimmed off the head of the file
        self.path = item.GetMediaPoolItem().GetClipProperty("File Path")

    def visible(self, t):
        rel = (t - self.src0) * self.fps
        return 0 <= rel < self.duration


def find_songs(timeline, fps):
    songs = []
    for track in range(1, timeline.GetTrackCount("audio") + 1):
        for item in timeline.GetItemListInTrack("audio", track) or []:
            mpi = item.GetMediaPoolItem()
            if mpi and mpi.GetClipProperty("File Path"):
                songs.append(Song(item, track, fps))
    return songs


def describe_song(song, timeline_start, fps):
    secs = (song.start - timeline_start) / fps
    return "A%d  %s  (at %d:%02d, %ds long)" % (
        song.track, song.item.GetName(), secs // 60, secs % 60, song.duration / fps)


def default_song_index(songs, timeline, fps):
    head = playhead_frame(timeline, fps)
    if head is not None:
        for i, s in enumerate(songs):
            if s.start <= head < s.start + s.duration:
                return i
    return max(range(len(songs)), key=lambda i: songs[i].duration)


def current_context(resolve):
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project and project.GetCurrentTimeline()
    if not timeline:
        raise BeatMarkerError("Open a timeline first.")
    fps = parse_fps(timeline.GetSetting("timelineFrameRate"))
    if not fps:
        raise BeatMarkerError("Couldn't read the timeline frame rate.")
    return project, timeline, fps


def pick_song(resolve, config, mode, extra=None):
    project, timeline, fps = current_context(resolve)
    songs = find_songs(timeline, fps)
    if not songs:
        raise BeatMarkerError("Put the song on an audio track in this timeline first.")
    request = {
        "mode": mode,
        "songs": [{"id": i, "label": describe_song(s, timeline.GetStartFrame(), fps), "path": s.path}
                  for i, s in enumerate(songs)],
        "default_song": default_song_index(songs, timeline, fps),
    }
    request.update(extra or {})
    response = ask(config, request)
    if not response:
        return None
    return project, timeline, fps, songs[response["options"]["song_id"]], response


# ---------------------------------------------------------------- markers

def clear_markers(item):
    removed = 0
    for frame, info in list((item.GetMarkers() or {}).items()):
        if str(info.get("customData", "")).startswith(TAG):
            if item.DeleteMarkerAtFrame(int(frame)):
                removed += 1
    return removed


def marker_frame(song, t, origin, offset):
    base = t if origin == "source" else t - song.src0
    return int(round(base * song.fps)) + offset


def run_markers(resolve, config):
    picked = pick_song(resolve, config, "markers")
    if not picked:
        return
    _, _, fps, song, response = picked
    opts, analysis = response["options"], response["analysis"]

    clear_markers(song.item)
    events = [e for e in beats.select(analysis, opts["density"], opts["tempo"]) if song.visible(e["t"])]
    note = "%.1f BPM (Beat Markers)" % analysis["tempo"]
    added = 0
    for e in events:
        frame = marker_frame(song, e["t"], config["marker_origin"], opts["offset"])
        color = opts["down_color"] if e["down"] else opts["beat_color"]
        if song.item.AddMarker(frame, color, e["name"], note, 1, "%s:%s" % (TAG, e["name"])):
            added += 1

    message(config, "Beat Markers", "Added %d markers to %s\nTempo: %.1f BPM\n\nTip: turn on snapping (N) to cut on them."
            % (added, song.item.GetName(), analysis["tempo"]))


def run_clear(resolve, config):
    _, timeline, fps = current_context(resolve)
    removed = sum(clear_markers(s.item) for s in find_songs(timeline, fps))
    message(config, "Beat Markers", "Removed %d beat markers from this timeline." % removed)


# ---------------------------------------------------------------- entry point

def find_resolve(g):
    """The injected globals differ between Resolve versions/editions, so try every known handle."""
    if g.get("resolve") is not None:
        return g["resolve"], "resolve"
    for name in ("app", "fusion", "fu"):
        obj = g.get(name)
        if obj is not None:
            try:
                r = obj.GetResolve()
                if r is not None:
                    return r, name + ".GetResolve()"
            except Exception as exc:
                log("%s.GetResolve() failed: %r" % (name, exc))
    if g.get("bmd") is not None:
        try:
            r = g["bmd"].scriptapp("Resolve")
            if r is not None:
                return r, "bmd.scriptapp"
        except Exception as exc:
            log("bmd.scriptapp failed: %r" % exc)
    try:
        import DaVinciResolveScript as dvr
        return dvr.scriptapp("Resolve"), "DaVinciResolveScript"
    except Exception as exc:
        log("DaVinciResolveScript failed: %r" % exc)
    return None, None


def run(mode, script_globals):
    config = load_config()
    resolve, via = find_resolve(script_globals)
    log("Connected to Resolve via %s" % via)
    if resolve is None:
        message(config, "Beat Markers", "Couldn't connect to Resolve. Run this from Workspace > Scripts inside "
                "DaVinci Resolve.\n\nDetails: %s" % LOG_PATH)
        return
    try:
        {"markers": run_markers, "clear": run_clear}[mode](resolve, config)
    except BeatMarkerError as exc:
        message(config, "Beat Markers", str(exc))
    except Exception:
        message(config, "Beat Markers error", traceback.format_exc()[-1500:])
