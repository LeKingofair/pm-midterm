"""Analyze a recording made in sine mode.
Usage: python analyze.py <name> <kp> [fm]      e.g. python analyze.py kp1 1.0"""
import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from scipy.io import wavfile
import pm_dsp as dsp

FC = 4000.0
ROOT = Path(__file__).resolve().parent.parent
name, kp = sys.argv[1], float(sys.argv[2])
fm = float(sys.argv[3]) if len(sys.argv) > 3 else 200.0

fs, x = wavfile.read(ROOT / "data" / f"{name}.wav")
x = x.astype(float)[int(0.2 * fs):]  # skip input settling
x -= x.mean()

# Demodulate and measure the phase deviation beta
t, phi, df = dsp.iq_demod(x, fs, FC)
trim = slice(int(0.02 * fs), -int(0.02 * fs))
t, phi = t[trim], phi[trim]
beta, fit = dsp.fit_sine(t, phi, fm)
rel_err = np.sqrt(np.mean((phi - fit) ** 2)) / beta

# Spectrum vs Bessel prediction
f, X = dsp.spectrum(x, fs)
n, meas = dsp.sideband_amplitudes(f, X, FC + df, fm)
_, theory = dsp.bessel_amplitudes(kp)
raw = np.array([X[np.abs(f - (FC + df + k * fm)) <= 5].max() for k in n])
Xn = X / np.sqrt(np.sum(raw ** 2))  # same normalization as `meas`

print(f"Carrier offset (clock mismatch): {df:+.3f} Hz")
print(f"kp set = {kp:.3f} rad   beta measured = {beta:.3f} rad")
print(f"Demodulation error (RMS / beta): {100 * rel_err:.2f} %")
print(f"Bessel fit RMS difference: {np.sqrt(np.mean((meas - theory) ** 2)):.4f}")
print(f"Carson BW = {dsp.carson_bw(kp, fm):.0f} Hz   98% power BW = {dsp.power_bw(meas, fm):.0f} Hz")
print("  n   measured   |J_n(kp)|")
for k, a, b in zip(n, meas, theory):
    print(f"{k:3d}   {a:8.4f}   {b:8.4f}")

fig, ax = plt.subplots(3, 1, figsize=(9, 10))
ax[0].plot(f, Xn, lw=0.8, label="FFT of recording")
ax[0].plot(FC + n * fm, theory, "o", mfc="none", label="|J_n(kp)|")
ax[0].set_xlim(FC - 2000, FC + 2000); ax[0].set_xlabel("frequency (Hz)"); ax[0].legend()
ax[1].bar(n - 0.2, meas, 0.4, label="measured")
ax[1].bar(n + 0.2, theory, 0.4, label="Bessel theory")
ax[1].set_xlabel("sideband n"); ax[1].set_ylabel("normalized amplitude"); ax[1].legend()
show = t < t[0] + 0.02
ax[2].plot((t[show] - t[0]) * 1e3, phi[show], label="recovered phase")
ax[2].plot((t[show] - t[0]) * 1e3, fit[show], "--", label=f"sine fit, beta = {beta:.3f}")
ax[2].set_xlabel("time (ms)"); ax[2].set_ylabel("rad"); ax[2].legend()
fig.suptitle(f"{name}: kp = {kp}, fm = {fm:.0f} Hz")
fig.tight_layout(); fig.savefig(ROOT / "figures" / f"{name}_analysis.png", dpi=150)
plt.show()