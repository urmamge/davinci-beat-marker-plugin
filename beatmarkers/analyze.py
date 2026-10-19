"""Beat analysis for the Beat Markers plugin. Runs in its own venv (needs librosa), never inside Resolve.

Usage: python analyze.py <audio file> [--engine librosa|beat_this]
Prints JSON: {"duration", "tempo", "beats", "downbeats", "onsets", "engine"} (all times in seconds).
"""
import argparse
import json
import sys

import numpy as np


def analyze_librosa(path):
    import librosa

    y, sr = librosa.load(path, sr=22050, mono=True)
    hop = 512
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=env, sr=sr, hop_length=hop)
    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)
    onsets = librosa.onset.onset_detect(
        onset_envelope=env, sr=sr, hop_length=hop, units="time", backtrack=True
    )

    # The beat tracker lands a hop or two after the attack; pull each beat back
    # onto the nearest real onset when one is close enough.
    if len(onsets):
        idx = np.clip(np.searchsorted(onsets, beats), 1, len(onsets) - 1)
        nearest = np.where(
            np.abs(onsets[idx - 1] - beats) < np.abs(onsets[idx] - beats), onsets[idx - 1], onsets[idx]
        )
        beats = np.where(np.abs(nearest - beats) <= 0.06, nearest, beats)
    if len(beats) > 1:
        tempo = 60.0 / np.polyfit(np.arange(len(beats)), beats, 1)[0]

    # Downbeats: kicks usually land on the "1", so score each of the 4 possible
    # bar phases by low-frequency onset strength and keep the strongest.
    low = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop, fmax=200, n_mels=32)
    downbeats = []
    if len(beat_frames) >= 8:
        strength = low[np.clip(beat_frames, 0, len(low) - 1)]
        scores = [strength[p::4].mean() for p in range(4)]
        phase = int(np.argmax(scores))
        downbeats = beats[phase::4]

    return {
        "duration": float(len(y) / sr),
        "tempo": float(np.atleast_1d(tempo)[0]),
        "beats": [round(float(t), 4) for t in beats],
        "downbeats": [round(float(t), 4) for t in downbeats],
        "onsets": [round(float(t), 4) for t in onsets],
    }


def analyze_beat_this(path):
    # Optional neural tracker: pip install beat_this (pulls in PyTorch)
    from beat_this.inference import File2Beats

    beats, downbeats = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)(path)
    base = analyze_librosa(path)  # still used for duration and onsets
    intervals = np.diff(beats)
    base["tempo"] = float(60.0 / np.median(intervals)) if len(intervals) else base["tempo"]
    base["beats"] = [round(float(t), 4) for t in beats]
    base["downbeats"] = [round(float(t), 4) for t in downbeats]
    return base


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--engine", default="librosa", choices=["librosa", "beat_this"])
    args = parser.parse_args()

    engine = args.engine
    if engine == "beat_this":
        try:
            result = analyze_beat_this(args.path)
        except ImportError:
            engine = "librosa"
    if engine == "librosa":
        result = analyze_librosa(args.path)
    result["engine"] = engine
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # report errors as JSON so Resolve can show them
        json.dump({"error": f"{type(exc).__name__}: {exc}"}, sys.stdout)
        sys.exit(1)
