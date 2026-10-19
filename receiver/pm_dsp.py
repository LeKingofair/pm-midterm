"""Shared PM math: I/Q demodulation, spectra, Bessel sidebands, bandwidth."""
import numpy as np
from scipy.signal import butter, sosfiltfilt
from scipy.special import jv


def iq_demod(x, fs, fc, cutoff=1000.0):
    """Recover phi(t) from x = A cos(2 pi fc t + phi). Returns t, phi with the
    clock-offset ramp removed, and the measured carrier offset in Hz."""
    t = np.arange(x.size) / fs
    sos = butter(5, cutoff, fs=fs, output="sos")
    i = sosfiltfilt(sos, x * np.cos(2 * np.pi * fc * t))
    q = sosfiltfilt(sos, -x * np.sin(2 * np.pi * fc * t))
    phi = np.unwrap(np.arctan2(q, i))
    slope, offset = np.polyfit(t, phi, 1)  # clock mismatch -> straight phase ramp
    return t, phi - (slope * t + offset), slope / (2 * np.pi)


def fit_sine(t, y, f):
    """Least-squares fit y = a sin + b cos + c at a known frequency f."""
    M = np.column_stack([np.sin(2 * np.pi * f * t), np.cos(2 * np.pi * f * t), np.ones_like(t)])
    coef, *_ = np.linalg.lstsq(M, y, rcond=None)
    return np.hypot(coef[0], coef[1]), M @ coef


def spectrum(x, fs):
    """Hann-windowed one-sided FFT, scaled so a sine of amplitude A reads A."""
    w = np.hanning(x.size)
    X = np.abs(np.fft.rfft(x * w)) / (w.sum() / 2)
    return np.fft.rfftfreq(x.size, 1 / fs), X


def sideband_amplitudes(f, X, fc, fm, nmax=8, search_hz=5.0):
    """Peak at fc + n*fm for n = -nmax..nmax, normalized so the squares sum to 1."""
    n = np.arange(-nmax, nmax + 1)
    amps = np.array([X[np.abs(f - (fc + k * fm)) <= search_hz].max() for k in n])
    return n, amps / np.sqrt(np.sum(amps ** 2))


def bessel_amplitudes(beta, nmax=8):
    n = np.arange(-nmax, nmax + 1)
    return n, np.abs(jv(n, beta))


def carson_bw(beta, fm):
    return 2 * (beta + 1) * fm


def power_bw(amps, fm, fraction=0.98):
    """Smallest band 2*N*fm around the carrier holding `fraction` of the power."""
    nmax = (amps.size - 1) // 2
    p = amps ** 2 / np.sum(amps ** 2)
    for N in range(nmax + 1):
        if p[nmax - N: nmax + N + 1].sum() >= fraction:
            return 2 * N * fm
    return 2 * nmax * fm