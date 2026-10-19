"""Record the ESP32 signal from the mic jack into data/<name>.wav.
Usage: python record.py <name> [seconds]      e.g. python record.py kp1 5"""
import sys
from pathlib import Path
import numpy as np
import sounddevice as sd
from scipy.io import wavfile

FS = 48000
DEVICE = None  # None = default input; or an index from `python -m sounddevice`
DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)

name = sys.argv[1] if len(sys.argv) > 1 else "recording"
dur = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
print(f"Recording {dur} s ...")
x = sd.rec(int(dur * FS), samplerate=FS, channels=1, dtype="float32", device=DEVICE)
sd.wait()
x = x[:, 0]
peak = np.max(np.abs(x))
print(f"Peak level: {peak:.3f} (full scale = 1.0)")
if peak > 0.95:
    print("WARNING: clipping. Lower the mic level in pavucontrol or add attenuation.")
elif peak < 0.01:
    print("WARNING: very quiet. Check the wiring and the selected input.")
wavfile.write(DATA / f"{name}.wav", FS, x)
print(f"Saved data/{name}.wav")