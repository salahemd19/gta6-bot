"""Original VICECITY INTEL music beds, synthesised here, so videos can carry music when they are posted from the cloud
(platform editors and in-app sounds are not reachable there). Nothing is sampled: we own the result.

  python music/make_beats.py      writes music/original/*.mp3 and registers the tracks in library.json
"""
import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "original"
SR = 44100
RNG = np.random.default_rng(2026)


def hz(note):
    return 440.0 * 2 ** ((note - 69) / 12)


def time(seconds):
    return np.arange(int(seconds * SR)) / SR


def env(t, attack, decay):
    return np.minimum(1.0, t / attack) * np.exp(-t / decay)


def smooth(x, n):
    return np.convolve(x, np.ones(n) / n, mode="same")


def kick():
    t = time(0.4)
    phase = 2 * np.pi * np.cumsum(44 + 120 * np.exp(-t / 0.03)) / SR
    return np.tanh(2.4 * np.sin(phase)) * env(t, 0.001, 0.13)


def clap():
    t = time(0.3)
    noise = RNG.uniform(-1, 1, t.size)
    noise = smooth(noise, 3) - smooth(noise, 24)
    shape = sum(np.where(t >= d, np.exp(-(t - d) / 0.012), 0) for d in (0.0, 0.011, 0.022)) + 0.7 * np.exp(-t / 0.09)
    return noise * shape * 0.9


def hat(decay=0.025):
    t = time(0.09)
    noise = np.diff(RNG.uniform(-1, 1, t.size + 2), 2) / 3
    return noise * env(t, 0.001, decay)


def bass(note, seconds, drive=2.8):
    t = time(seconds)
    f = hz(note) * (1 + 0.35 * np.exp(-t / 0.025))
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR)
    return np.tanh(drive * tone) * env(t, 0.004, seconds * 0.7) * np.minimum(1, (seconds - t) / 0.02)


def cowbell(note, seconds=0.28):
    t = time(seconds)
    f = hz(note)
    tone = np.sign(np.sin(2 * np.pi * f * t)) + 0.8 * np.sign(np.sin(2 * np.pi * f * 1.482 * t))
    tone = smooth(tone, 5) - smooth(tone, 60)
    return tone * env(t, 0.001, 0.085)


def pluck(note, seconds=0.22):
    t = time(seconds)
    f = hz(note)
    tone = 2 / np.pi * np.arcsin(np.sin(2 * np.pi * f * t)) + 0.3 * np.sin(4 * np.pi * f * t)
    return tone * env(t, 0.003, 0.08)


def bell(note, seconds=0.9):
    t = time(seconds)
    f = hz(note)
    tone = np.sin(2 * np.pi * f * t + 1.6 * np.sin(2 * np.pi * f * 3.01 * t) * np.exp(-t / 0.2))
    return tone * env(t, 0.002, 0.28)


def pad(notes, seconds):
    t = time(seconds)
    tone = sum(2 * ((hz(n) * d * t + RNG.random()) % 1) - 1 for n in notes for d in (0.996, 1.0, 1.005))
    tone = smooth(smooth(tone / (len(notes) * 3), 18), 18)
    return tone * np.minimum(1, t / 0.25) * np.minimum(1, (seconds - t) / 0.25)


class Mix:
    def __init__(self, seconds):
        self.drums = np.zeros((int(seconds * SR) + SR, 2))
        self.music = np.zeros_like(self.drums)
        self.kicks = []
        self.length = int(seconds * SR)

    def add(self, sound, at, gain, pan=0.0, drum=False):
        i = int(at * SR)
        n = min(sound.size, self.drums.shape[0] - i)
        target = self.drums if drum else self.music
        target[i:i + n, 0] += sound[:n] * gain * (1 - max(0, pan))
        target[i:i + n, 1] += sound[:n] * gain * (1 + min(0, pan))

    def render(self):
        duck = np.ones(self.drums.shape[0])
        tail = 1 - 0.65 * np.exp(-time(0.4) / 0.11)
        for k in self.kicks:  # the music pumps around every kick
            i = int(k * SR)
            n = min(tail.size, duck.size - i)
            duck[i:i + n] = np.minimum(duck[i:i + n], tail[:n])
        out = (self.drums + self.music * duck[:, None])[: self.length]
        out = np.tanh(1.15 * out)
        return out / max(1e-9, np.abs(out).max()) * 0.94


def drift():
    """Phonk: cowbell hook, distorted 808."""
    bpm, bars = 130, 16
    step = 60 / bpm / 4
    mix = Mix(bars * 16 * step)
    a = [77, 0, 77, 0, 80, 0, 77, 0, 82, 0, 80, 0, 77, 78, 77, 0]
    b = [73, 0, 73, 0, 75, 0, 73, 0, 80, 0, 78, 0, 77, 0, 75, 0]
    for bar in range(bars):
        t0, line, root = bar * 16 * step, (a if bar % 4 < 2 else b), (29 if bar % 4 < 2 else 25)
        breakdown = bar == 7
        for s, note in enumerate(line):
            if note:
                mix.add(cowbell(note), t0 + s * step, 0.34, pan=0.25 if s % 4 else -0.2)
        if not breakdown:
            for s, long in ((0, 5), (6, 2), (8, 3), (11, 5)):
                mix.add(kick(), t0 + s * step, 0.95, drum=True)
                mix.kicks.append(t0 + s * step)
                mix.add(bass(root + (12 if s == 6 else 0), long * step), t0 + s * step, 0.55)
        for s in (4, 12):
            mix.add(clap(), t0 + s * step, 0.5, drum=True)
        for s in range(0, 16, 2):
            mix.add(hat(), t0 + s * step, 0.22, pan=0.3, drum=True)
        if bar % 4 == 3:
            for k in range(8):
                mix.add(hat(0.012), t0 + (14 + k / 4) * step, 0.2, pan=-0.3, drum=True)
    return mix.render()


def night_drive():
    """Synthwave: four on the floor, pulsing bass, arpeggio over a pad."""
    bpm, bars = 104, 16
    step = 60 / bpm / 4
    mix = Mix(bars * 16 * step)
    chords = ((57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62))
    for bar in range(bars):
        t0, chord = bar * 16 * step, chords[bar % 4]
        mix.add(pad(chord, 16 * step), t0, 0.28)
        for s in range(0, 16, 4):
            mix.add(kick(), t0 + s * step, 0.8, drum=True)
            mix.kicks.append(t0 + s * step)
        for s in (4, 12):
            mix.add(clap(), t0 + s * step, 0.4, drum=True)
        for s in range(0, 16, 2):
            mix.add(bass(chord[0] - 24 + (12 if s % 4 else 0), 2 * step, 1.6), t0 + s * step, 0.42)
            mix.add(hat(0.05 if s % 4 else 0.02), t0 + s * step, 0.17, pan=0.35, drum=True)
        order = (0, 1, 2, 1)
        for s in range(16):
            octave = 12 if (s // 4) % 2 == 0 else 24
            mix.add(pluck(chord[order[s % 4]] + octave), t0 + s * step, 0.2 if bar >= 2 else 0.12, pan=-0.4 if s % 2 else 0.4)
    return mix.render()


def heist():
    """Dark trap, half time: sliding 808, sparse bell, rolling hats."""
    bpm, bars = 140, 16
    step = 60 / bpm / 4
    mix = Mix(bars * 16 * step)
    tune = ([76, 0, 0, 79, 0, 0, 83, 0, 82, 0, 0, 79, 0, 0, 0, 0], [76, 0, 0, 79, 0, 0, 84, 0, 83, 0, 0, 78, 0, 0, 75, 0])
    roots = (28, 28, 24, 27)
    for bar in range(bars):
        t0, root = bar * 16 * step, roots[bar % 4]
        for s, note in enumerate(tune[bar % 2]):
            if note:
                mix.add(bell(note), t0 + s * step, 0.27, pan=0.2 if s % 2 else -0.2)
        for s, long in ((0, 7), (7, 3), (10, 6)):
            mix.add(kick(), t0 + s * step, 0.9, drum=True)
            mix.kicks.append(t0 + s * step)
            mix.add(bass(root + (0 if s else 0), long * step, 3.2), t0 + s * step, 0.6)
        mix.add(clap(), t0 + 8 * step, 0.62, drum=True)
        for s in range(0, 16, 2):
            mix.add(hat(), t0 + s * step, 0.2, pan=0.25, drum=True)
        for k in range(6 if bar % 2 else 3):
            mix.add(hat(0.01), t0 + (12 + k * 2 / 3) * step, 0.17, pan=-0.35, drum=True)
    return mix.render()


TRACKS = {
    "vci-drift": (drift, "VCI Drift", "dark, aggressive phonk", "high", 130, ["racing", "chaos", "challenges", "transitions"]),
    "vci-night-drive": (night_drive, "VCI Night Drive", "neon synthwave", "medium", 104, ["leonida", "secrets", "night", "cinematic"]),
    "vci-heist": (heist, "VCI Heist", "tense dark trap", "high", 140, ["chaos", "suspense", "tips", "epic", "funny"]),
}


def save(audio, path):
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "x.wav"
        with wave.open(str(raw), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((audio * 32767).astype(np.int16).tobytes())
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", "loudnorm=I=-14:TP=-1.5:LRA=9", "-ar", str(SR),
                        "-b:a", "192k", str(path)], check=True)


def main():
    OUT.mkdir(exist_ok=True)
    lib_file = HERE / "library.json"
    lib = json.loads(lib_file.read_text(encoding="utf-8"))
    lib["tracks"] = [t for t in lib["tracks"] if t.get("kind") != "original"]
    for tid, (make, title, mood, energy, bpm, cats) in TRACKS.items():
        audio = make()
        save(audio, OUT / f"{tid}.mp3")
        lib["tracks"].append({
            "id": tid, "title": title, "artist": "VICECITY INTEL (original)", "genre": "original", "mood": mood, "energy": energy,
            "bpm": bpm, "duration": round(len(audio) / SR, 1), "categories": cats, "best_moments": "under a countdown, from 0 s",
            "source": f"music/original/{tid}.mp3 (synthesised by music/make_beats.py)",
            "licence_evidence": "Original composition synthesised for VICECITY INTEL, no samples; we own it",
            "platforms": {"youtube": "APPROVED", "tiktok": "APPROVED", "reels": "APPROVED"}, "monetization": "Allowed",
            "attribution": "None", "conditions": "None", "best_start": 0, "volume_db": -13, "kind": "original"})
        print(tid, round(len(audio) / SR, 1), "s")
    lib_file.write_text(json.dumps(lib, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
