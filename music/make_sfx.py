"""Generates the original VICECITY INTEL sound identity (owned by us): intro, transition, reveal, outro."""
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent / "sfx"
OUT.mkdir(exist_ok=True)
SR = "44100"
SOUNDS = {
    # rising neon synth sweep + sub hit
    "intro": "aevalsrc='0.5*sin(2*PI*(110+900*t*t)*t)*exp(-1.5*t)+0.6*sin(2*PI*48*t)*exp(-6*(t-0.45)*gt(t,0.45))*gt(t,0.45)':s=44100:d=0.9",
    # short filtered whoosh
    "transition": "anoisesrc=d=0.35:c=pink:a=0.6,highpass=f=800,lowpass=f=6000,afade=in:d=0.12,afade=out:st=0.15:d=0.2",
    # cinematic boom with a bright ping
    "reveal": "aevalsrc='0.9*sin(2*PI*42*t)*exp(-3*t)+0.3*sin(2*PI*1760*t)*exp(-8*t)':s=44100:d=1.2",
    # two-note signature (Vice City pink/cyan: minor third)
    "outro": "aevalsrc='0.4*sin(2*PI*659*t)*exp(-4*t)*lt(t,0.35)+0.4*sin(2*PI*784*(t-0.35))*exp(-3*(t-0.35))*gte(t,0.35)':s=44100:d=1.0",
}

for name, src in SOUNDS.items():
    f = OUT / f"vci_{name}.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-ar", SR, "-ac", "2", str(f)], check=True)
    print("made", f.name)
