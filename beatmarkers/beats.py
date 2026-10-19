"""Pure beat-selection logic shared by the Resolve side and the dialog. Standard library only."""

DENSITIES = [
    ("beat", "Every beat"),
    ("beat2", "Every 2 beats"),
    ("bar", "Every bar (downbeats)"),
    ("bar2", "Every 2 bars"),
    ("bar4", "Every 4 bars"),
    ("onset", "Every hit (onsets)"),
]

TEMPOS = [
    ("normal", "Normal"),
    ("half", "Half time"),
    ("double", "Double time"),
]

MARKER_COLORS = [
    "Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", "Fuchsia",
    "Rose", "Lavender", "Sky", "Mint", "Lemon", "Sand", "Cocoa", "Cream",
]

_MATCH = 0.05  # seconds within which a downbeat counts as the same event as a beat


def _nearest_index(values, t):
    return min(range(len(values)), key=lambda i: abs(values[i] - t))


def apply_tempo(beats, downbeats, mode):
    beats = list(beats)
    downbeats = list(downbeats)
    if mode == "double" and len(beats) > 1:
        doubled = []
        for a, b in zip(beats, beats[1:]):
            doubled += [a, (a + b) / 2.0]
        doubled.append(beats[-1])
        return doubled, downbeats
    if mode == "half" and beats:
        phase = _nearest_index(beats, downbeats[0]) % 2 if downbeats else 0
        return beats[phase::2], downbeats[::2]
    return beats, downbeats


def label_beats(beats, downbeats):
    """Return [{t, bar, beat, down}] where bar 0 means pickup beats before the first downbeat."""
    if not downbeats:
        downbeats = beats[::4]
    down_set = set()
    for d in downbeats:
        if beats:
            i = _nearest_index(beats, d)
            if abs(beats[i] - d) <= _MATCH:
                down_set.add(i)
    out, bar, beat = [], 0, 0
    for i, t in enumerate(beats):
        if i in down_set:
            bar, beat = bar + 1, 1
        else:
            beat += 1
        out.append({"t": t, "bar": bar, "beat": beat, "down": i in down_set})
    return out


def select(analysis, density, tempo="normal"):
    """Pick the event times for a density setting. Returns [{t, name, down}] sorted by time."""
    if density == "onset":
        return [{"t": t, "name": "Hit %d" % (i + 1), "down": False}
                for i, t in enumerate(analysis.get("onsets", []))]

    beats, downbeats = apply_tempo(analysis.get("beats", []), analysis.get("downbeats", []), tempo)
    labeled = label_beats(beats, downbeats)
    first_down = next((i for i, b in enumerate(labeled) if b["down"]), 0)

    picked = []
    for i, b in enumerate(labeled):
        if density == "beat":
            keep = True
        elif density == "beat2":
            keep = (i - first_down) % 2 == 0
        elif density in ("bar", "bar2", "bar4"):
            every = {"bar": 1, "bar2": 2, "bar4": 4}[density]
            keep = b["down"] and (b["bar"] - 1) % every == 0
        else:
            raise ValueError("unknown density: %s" % density)
        if keep:
            name = "Bar %d" % b["bar"] if b["down"] else (
                "%d.%d" % (b["bar"], b["beat"]) if b["bar"] else "Pickup %d" % b["beat"])
            picked.append({"t": b["t"], "name": name, "down": b["down"]})
    return picked
