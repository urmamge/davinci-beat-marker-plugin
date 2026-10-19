# Beat Markers launcher - installed into Resolve's Scripts menu by install.ps1
import os, subprocess, sys, time, traceback

DATA = os.path.join(os.environ.get("LOCALAPPDATA", ""), "BeatMarkers")
try:
    with open(os.path.join(DATA, "beatmarkers.log"), "a") as f:
        f.write("%s --- Beat Markers: Python %s (%s), globals %s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), sys.version.split()[0], sys.executable,
            sorted(k for k in globals() if not k.startswith("_"))))
except OSError:
    pass

try:
    import importlib
    sys.path.insert(0, os.path.join(DATA, "app"))
    import beatmarkers.beats, beatmarkers.resolve_side
    importlib.reload(beatmarkers.beats)
    importlib.reload(beatmarkers.resolve_side)
    beatmarkers.resolve_side.run("markers", globals())
except Exception:
    err = traceback.format_exc()
    print(err)
    try:
        with open(os.path.join(DATA, "beatmarkers.log"), "a") as f:
            f.write(err)
        subprocess.Popen([os.path.join(DATA, "venv", "Scripts", "pythonw.exe"),
                          os.path.join(DATA, "app", "beatmarkers", "dialog.py"), "message", "Beat Markers error", err[-1500:]])
    except Exception:
        pass
