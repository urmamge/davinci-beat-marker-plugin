"""Tests against a fake Resolve object model. Run: python -m unittest discover tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from beatmarkers import beats, resolve_side  # noqa: E402

FPS = 30.0
ANALYSIS = {  # 120 BPM, first beat at 0.5 s, downbeat on every 4th beat starting at 1.0 s
    "tempo": 120.0,
    "beats": [0.5 + 0.5 * i for i in range(60)],
    "downbeats": [1.0 + 2.0 * i for i in range(14)],
    "onsets": [0.5 + 0.25 * i for i in range(100)],
}


class FakeMPI:
    def __init__(self, name, kind="Audio", frames=None, fps=FPS, path=None):
        self.name = name
        self.props = {"Type": kind, "Frames": str(frames or ""), "FPS": str(fps),
                      "File Path": path if path is not None else "C:/media/%s" % name}

    def GetClipProperty(self, key=None):
        return self.props.get(key, "")

    def GetName(self):
        return self.name


class FakeItem:
    def __init__(self, mpi, start, duration, src_start_sec=0.0):
        self.mpi, self.start, self.duration, self.src = mpi, start, duration, src_start_sec
        self.markers = {}

    def GetMediaPoolItem(self): return self.mpi
    def GetName(self): return self.mpi.GetName()
    def GetStart(self): return self.start
    def GetDuration(self): return self.duration
    def GetSourceStartTime(self): return self.src
    def GetLeftOffset(self): return int(self.src * FPS)
    def GetMarkers(self): return {float(k): v for k, v in self.markers.items()}

    def AddMarker(self, frame, color, name, note, duration, custom=""):
        if frame in self.markers:
            return False
        self.markers[frame] = {"color": color, "name": name, "note": note,
                               "duration": duration, "customData": custom}
        return True

    def DeleteMarkerAtFrame(self, frame):
        return self.markers.pop(frame, None) is not None


class FakeTimeline:
    def __init__(self, audio_items):
        self.audio = {1: audio_items}
        self.video = {1: []}
        self.track_names = {}

    def GetSetting(self, key): return "30" if key == "timelineFrameRate" else ""
    def GetStartFrame(self): return 108000
    def GetCurrentTimecode(self): return "01:00:00:00"
    def GetTrackCount(self, kind): return len(self.audio if kind == "audio" else self.video)
    def GetItemListInTrack(self, kind, i): return (self.audio if kind == "audio" else self.video)[i]



class FakeResolve:
    def __init__(self, timeline):
        project = type("P", (), {"GetCurrentTimeline": lambda s: timeline})()
        self.pm = type("PM", (), {"GetCurrentProject": lambda s: project})()

    def GetProjectManager(self): return self.pm


def make_world(song_start=108000 + 60, src_trim=0.0):
    song = FakeItem(FakeMPI("song.mp3"), song_start, 20 * 30, src_trim)
    timeline = FakeTimeline([song])
    return FakeResolve(timeline), timeline, song


class StubAsk:
    def __init__(self, options):
        self.options, self.requests, self.messages = options, [], []

    def __enter__(self):
        self.old = resolve_side.ask, resolve_side.message
        resolve_side.ask = lambda config, req: self.requests.append(req) or {
            "options": dict(self.options), "analysis": ANALYSIS}
        resolve_side.message = lambda config, title, text, wait=False: self.messages.append(text)
        return self

    def __exit__(self, *exc):
        resolve_side.ask, resolve_side.message = self.old


CONFIG = dict(resolve_side.DEFAULT_CONFIG)


class BeatSelection(unittest.TestCase):
    def test_bars_hit_downbeats(self):
        bars = beats.select(ANALYSIS, "bar")
        self.assertEqual([b["t"] for b in bars[:3]], [1.0, 3.0, 5.0])
        self.assertEqual(bars[0]["name"], "Bar 1")
        self.assertTrue(all(b["down"] for b in bars))

    def test_every_two_bars_and_pickup(self):
        self.assertEqual([b["t"] for b in beats.select(ANALYSIS, "bar2")[:2]], [1.0, 5.0])
        every = beats.select(ANALYSIS, "beat")
        self.assertEqual(every[0]["name"], "Pickup 1")
        self.assertEqual(every[2]["name"], "1.2")

    def test_beat2_keeps_downbeats(self):
        times = [b["t"] for b in beats.select(ANALYSIS, "beat2")]
        self.assertIn(1.0, times)
        self.assertIn(3.0, times)
        self.assertNotIn(1.5, times)

    def test_tempo_modes(self):
        self.assertEqual(len(beats.select(ANALYSIS, "beat", "double")), 119)
        half = [b["t"] for b in beats.select(ANALYSIS, "beat", "half")]
        self.assertIn(1.0, half)
        self.assertEqual(half[1] - half[0], 1.0)

    def test_no_downbeats_falls_back_to_four_beat_bars(self):
        bars = beats.select(dict(ANALYSIS, downbeats=[]), "bar")
        self.assertEqual([b["t"] for b in bars[:2]], [0.5, 2.5])


class Markers(unittest.TestCase):
    OPTS = {"song_id": 0, "density": "bar", "tempo": "normal", "offset": 0,
            "beat_color": "Blue", "down_color": "Red"}

    def test_markers_on_song_clip(self):
        resolve, _, song = make_world()
        with StubAsk(self.OPTS) as stub:
            resolve_side.run_markers(resolve, CONFIG)
        frames = sorted(song.markers)
        self.assertEqual(frames[:3], [30, 90, 150])  # 1.0 s, 3.0 s, 5.0 s at 30 fps
        self.assertEqual(len(frames), 10)  # bars inside the 20 s clip
        self.assertEqual(song.markers[30]["color"], "Red")
        self.assertIn("120.0 BPM", song.markers[30]["note"])
        self.assertIn("Added 10 markers", stub.messages[0])

    def test_trimmed_song_skips_hidden_beats(self):
        resolve, _, song = make_world(src_trim=4.0)
        with StubAsk(self.OPTS):
            resolve_side.run_markers(resolve, CONFIG)
        self.assertEqual(min(song.markers), 150)  # first visible bar is 5.0 s into the file
        with StubAsk(self.OPTS):
            resolve_side.run_markers(resolve, dict(CONFIG, marker_origin="clip"))
        self.assertEqual(min(song.markers), 30)   # 1.0 s after the visible start

    def test_rerun_replaces_only_own_markers(self):
        resolve, timeline, song = make_world()
        song.AddMarker(7, "Green", "mine", "", 1, "")
        with StubAsk(self.OPTS):
            resolve_side.run_markers(resolve, CONFIG)
            resolve_side.run_markers(resolve, CONFIG)
        self.assertEqual(len(song.markers), 11)
        with StubAsk(self.OPTS) as stub:
            resolve_side.run_clear(resolve, CONFIG)
        self.assertEqual(list(song.markers), [7])
        self.assertIn("Removed 10", stub.messages[0])

    def test_nudge(self):
        resolve, _, song = make_world()
        with StubAsk(dict(self.OPTS, offset=-2)):
            resolve_side.run_markers(resolve, CONFIG)
        self.assertEqual(min(song.markers), 28)


if __name__ == "__main__":
    unittest.main()
