"""Settings dialog + analysis runner. Runs in the plugin's venv (has tkinter and librosa), launched by resolve_side.

    pythonw dialog.py ask <request.json> <response.json>
    pythonw dialog.py message <title> <text>
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from beatmarkers import beats  # noqa: E402

ANALYZER_VERSION = "1"
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "BeatMarkers")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
PREFS_PATH = os.path.join(DATA_DIR, "last_options.json")


def analyze(path, engine):
    st = os.stat(path)
    key = hashlib.sha1(("%s|%d|%d|%s|%s" % (path, st.st_size, int(st.st_mtime), engine,
                                            ANALYZER_VERSION)).encode("utf-8")).hexdigest()
    cached = os.path.join(CACHE_DIR, key + ".json")
    if os.path.exists(cached):
        with open(cached, encoding="utf-8") as f:
            return json.load(f)

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analyze.py")
    proc = subprocess.run([sys.executable, script, path, "--engine", engine],
                          capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        raise RuntimeError("Analyzer crashed:\n" + (proc.stderr or proc.stdout)[-2000:])
    if "error" in result:
        raise RuntimeError(result["error"])

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cached, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return result


def load_prefs():
    try:
        with open(PREFS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_prefs(prefs):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PREFS_PATH, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)


def make_root(title):
    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    root.resizable(False, False)
    return root


def center(root):
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    root.geometry("+%d+%d" % ((root.winfo_screenwidth() - w) // 2, (root.winfo_screenheight() - h) // 3))
    root.lift()
    root.focus_force()


class Dialog:
    def __init__(self, request):
        self.request = request
        self.result = {"cancelled": True}
        self.prefs = load_prefs().get("markers", {})

        self.root = make_root("Beat Markers")
        frame = ttk.Frame(self.root, padding=14)
        frame.grid(sticky="nsew")
        self.frame = frame
        self.row = 0
        self.widgets = []

        songs = request["songs"]
        self.song = self.combo("Song", [s["label"] for s in songs], request.get("default_song", 0), width=48)
        self.density = self.choice("Markers at", beats.DENSITIES, "density", "beat")
        self.tempo = self.choice("Tempo feel", beats.TEMPOS, "tempo", "normal")
        colors = [(c, c) for c in beats.MARKER_COLORS]
        self.beat_color = self.choice("Beat colour", colors, "beat_color", "Blue")
        self.down_color = self.choice("Downbeat colour", colors, "down_color", "Red")

        self.offset = self.spin("Nudge (frames)", -30, 30, self.prefs.get("offset", 0))
        ttk.Label(frame, text="Negative nudge = earlier. Cutting 1-2 frames early often feels tighter.",
                  foreground="#666").grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.row += 1

        self.status = ttk.Label(frame, text="", foreground="#06c")
        self.status.grid(row=self.row, column=0, columnspan=2, sticky="w")
        self.row += 1

        buttons = ttk.Frame(frame)
        buttons.grid(row=self.row, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self.ok_btn = ttk.Button(buttons, text="Add markers", command=self.on_ok)
        self.ok_btn.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.root.destroy).pack(side="right", padx=(0, 6))
        self.root.bind("<Return>", lambda e: self.on_ok())
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        center(self.root)

    def _label(self, text):
        ttk.Label(self.frame, text=text).grid(row=self.row, column=0, sticky="w", padx=(0, 10), pady=3)

    def combo(self, label, values, index, width=28):
        self._label(label)
        box = ttk.Combobox(self.frame, values=values, state="readonly", width=width)
        if values:
            box.current(min(index, len(values) - 1))
        box.grid(row=self.row, column=1, sticky="we", pady=3)
        self.row += 1
        self.widgets.append(box)
        return box

    def choice(self, label, pairs, pref_key, default):
        keys = [k for k, _ in pairs]
        current = self.prefs.get(pref_key, default)
        box = self.combo(label, [v for _, v in pairs], keys.index(current) if current in keys else 0)
        box.keys = keys
        return box

    def spin(self, label, lo, hi, value):
        self._label(label)
        var = tk.IntVar(value=value)
        box = ttk.Spinbox(self.frame, from_=lo, to=hi, textvariable=var, width=8)
        box.grid(row=self.row, column=1, sticky="w", pady=3)
        box.var = var
        self.row += 1
        self.widgets.append(box)
        return box

    @staticmethod
    def key(box):
        return box.keys[box.current()]

    def on_ok(self):
        if str(self.ok_btn["state"]) == "disabled":
            return
        try:
            options = {"density": self.key(self.density), "tempo": self.key(self.tempo),
                       "offset": int(self.offset.var.get()),
                       "beat_color": self.key(self.beat_color), "down_color": self.key(self.down_color)}
        except (tk.TclError, ValueError):
            self.status.config(text="Nudge must be a whole number.", foreground="#c00")
            return

        song = self.request["songs"][self.song.current()]
        options["song_id"] = song["id"]

        all_prefs = load_prefs()
        all_prefs["markers"] = {k: v for k, v in options.items() if k != "song_id"}
        save_prefs(all_prefs)

        for w in self.widgets:
            w.config(state="disabled")
        self.ok_btn.config(state="disabled")
        self.status.config(text="Analysing %s ... (first run can take ~20 s)" % os.path.basename(song["path"]),
                           foreground="#06c")

        def work():
            try:
                analysis = analyze(song["path"], self.request.get("engine", "librosa"))
                self.result = {"options": options, "analysis": analysis}
            except Exception as exc:  # shown in Resolve-side message
                self.result = {"error": str(exc)}
            self.root.after(0, self.root.destroy)

        threading.Thread(target=work, daemon=True).start()

    def run(self):
        self.root.mainloop()
        return self.result


def main():
    if sys.argv[1] == "message":
        root = make_root(sys.argv[2])
        root.withdraw()
        messagebox.showinfo(sys.argv[2], sys.argv[3], parent=root)
        return

    with open(sys.argv[2], encoding="utf-8") as f:
        request = json.load(f)
    result = Dialog(request).run()
    with open(sys.argv[3], "w", encoding="utf-8") as f:
        json.dump(result, f)


if __name__ == "__main__":
    main()
