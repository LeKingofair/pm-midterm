"""Make a simulated recording in data/<name>.wav, so analyze.py works with no hardware.
It writes the same kind of file record.py makes from the mic jack: 48 kHz, mono, float32.

Usage: python sim_record.py <name> <kp> [fm] [snr_db] [seconds]
  e.g. python sim_record.py sim_kp1 1.0              (then: python analyze.py sim_kp1 1.0)
       python sim_record.py sim_null 2.405
       python sim_record.py sim_noisy 1.0 200 12

The model matches the GUI simulator: s(t) = A cos(2*pi*(fc + df)*t + kp*sin(2*pi*fm*t)) + noise,
with a 0.7 Hz clock offset df so the drift correction in pm_dsp.iq_demod has real work to do."""
import sys
from pathlib import Path
import numpy as np
from scipy.io import wavfile

FS, FC, A, DF = 48000, 4000.0, 0.3, 0.7
DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)

if len(sys.argv) < 3:
    sys.exit(__doc__)
name, kp = sys.argv[1], float(sys.argv[2])
fm = float(sys.argv[3]) if len(sys.argv) > 3 else 200.0
snr_db = float(sys.argv[4]) if len(sys.argv) > 4 else 40.0
dur = float(sys.argv[5]) if len(sys.argv) > 5 else 5.0

t = np.arange(int(dur * FS)) / FS
x = A * np.cos(2 * np.pi * (FC + DF) * t + kp * np.sin(2 * np.pi * fm * t))
sigma = np.sqrt(A ** 2 / 2 / 10 ** (snr_db / 10))      # noise power = signal power / SNR
x += np.random.default_rng(0).normal(0, sigma, t.size)

wavfile.write(DATA / f"{name}.wav", FS, x.astype(np.float32))
print(f"Saved data/{name}.wav  (kp={kp}, fm={fm} Hz, SNR={snr_db} dB, {dur} s, simulated)")
print(f"Next: python analyze.py {name} {kp} {fm:g}")
