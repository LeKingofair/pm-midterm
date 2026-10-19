"""Full PM chain in software: modulate, add noise, demodulate, compare with theory."""
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import pm_dsp as dsp

FS, FC, FM, DUR = 48000, 4000.0, 200.0, 2.0
FIG = Path(__file__).resolve().parent.parent / "figures"
FIG.mkdir(exist_ok=True)
t = np.arange(int(FS * DUR)) / FS
m = np.sin(2 * np.pi * FM * t)  # amplitude 1, so beta = kp
trim = slice(int(0.01 * FS), -int(0.01 * FS))  # skip filter edges


def pm(kp, snr_db=None, seed=0):
    s = np.cos(2 * np.pi * FC * t + kp * m)
    if snr_db is not None:
        noise_var = 0.5 / 10 ** (snr_db / 10)  # signal power is 0.5
        s = s + np.random.default_rng(seed).normal(0, np.sqrt(noise_var), s.size)
    return s


# 1. Time domain: message, carrier, PM signal
show = t < 0.01
fig, ax = plt.subplots(3, 1, sharex=True, figsize=(9, 6))
ax[0].plot(t[show] * 1e3, m[show]); ax[0].set_ylabel("m(t)")
ax[1].plot(t[show] * 1e3, np.cos(2 * np.pi * FC * t[show])); ax[1].set_ylabel("carrier")
ax[2].plot(t[show] * 1e3, pm(2.0)[show]); ax[2].set_ylabel("PM, kp = 2")
ax[2].set_xlabel("time (ms)")
fig.tight_layout(); fig.savefig(FIG / "sim_time_domain.png", dpi=150)

# 2. Spectra vs Bessel prediction, and bandwidth vs Carson's rule
kps = [0.5, 1.0, 2.0, 2.405]
fig, axes = plt.subplots(len(kps), 1, sharex=True, figsize=(9, 10))
print("  kp   Carson (Hz)   98% power BW (Hz)")
for ax, kp in zip(axes, kps):
    f, X = dsp.spectrum(pm(kp), FS)
    n, meas = dsp.sideband_amplitudes(f, X, FC, FM)
    _, theory = dsp.bessel_amplitudes(kp)
    ax.plot(f, X, lw=0.8, label="FFT of s(t)")
    ax.plot(FC + n * FM, theory, "o", mfc="none", label="|J_n(beta)|")
    ax.set_xlim(FC - 2000, FC + 2000); ax.set_title(f"beta = kp = {kp}")
    print(f"{kp:5.3f} {dsp.carson_bw(kp, FM):12.0f} {dsp.power_bw(meas, FM):18.0f}")
axes[0].legend(); axes[-1].set_xlabel("frequency (Hz)")
fig.tight_layout(); fig.savefig(FIG / "sim_spectra_bessel.png", dpi=150)

# 3. Demodulation: recovered vs original message
kp = 1.0
tt, phi, _ = dsp.iq_demod(pm(kp), FS, FC)
m_hat = phi / kp
rms = np.sqrt(np.mean((m_hat[trim] - m[trim]) ** 2))
show = (tt > 0.02) & (tt < 0.04)
fig, ax = plt.subplots(figsize=(9, 3.5))
ax.plot(tt[show] * 1e3, m[show], label="original m(t)")
ax.plot(tt[show] * 1e3, m_hat[show], "--", label=f"recovered, RMS error {rms:.2e}")
ax.set_xlabel("time (ms)"); ax.legend()
fig.tight_layout(); fig.savefig(FIG / "sim_demod.png", dpi=150)

# 4. Noise: demodulation error vs SNR for several kp
snrs = np.arange(0, 41, 5)
fig, ax = plt.subplots(figsize=(7, 4))
for kp in [0.5, 1.0, 2.0]:
    errs = []
    for snr in snrs:
        _, phi, _ = dsp.iq_demod(pm(kp, snr), FS, FC)
        errs.append(np.sqrt(np.mean((phi[trim] / kp - m[trim]) ** 2)))
    ax.semilogy(snrs, errs, "o-", label=f"kp = {kp}")
ax.set_xlabel("SNR (dB)"); ax.set_ylabel("RMS error of recovered m(t)"); ax.legend()
fig.tight_layout(); fig.savefig(FIG / "sim_error_vs_snr.png", dpi=150)

plt.show()