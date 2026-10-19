"""Live PM demodulation: turn the pot, watch the recovered phase move."""
import numpy as np
import sounddevice as sd
import matplotlib.pyplot as plt
from scipy.signal import butter, sosfilt

FS, FC, BLOCK = 48000, 4000.0, 4800  # 0.1 s blocks
DEVICE = None                        # same as in record.py
DECIM = 100                          # display at 480 points per second
WINDOW_S = 5

sos = butter(4, 800, fs=FS, output="sos")
zi_i = np.zeros((sos.shape[0], 2))
zi_q = np.zeros((sos.shape[0], 2))
n_done, last_phase = 0, 0.0


def demod_block(x):
    """I/Q demodulate one block; returns phase samples and their times."""
    global zi_i, zi_q, n_done, last_phase
    t = (n_done + np.arange(x.size)) / FS
    n_done += x.size
    i, zi_i = sosfilt(sos, x * np.cos(2 * np.pi * FC * t), zi=zi_i)
    q, zi_q = sosfilt(sos, -x * np.sin(2 * np.pi * FC * t), zi=zi_q)
    ph = np.angle(i + 1j * q)[::DECIM]
    ph = np.unwrap(np.concatenate([[last_phase], ph]))[1:]  # continuous across blocks
    last_phase = ph[-1]
    return ph, t[::DECIM]


input("Type 'mode carrier' in the Serial Monitor, then press Enter here to calibrate...")
with sd.InputStream(samplerate=FS, channels=1, device=DEVICE, blocksize=BLOCK) as stream:
    stream.read(BLOCK * 3)  # let the filters settle
    cal_ph, cal_t = [], []
    for _ in range(20):  # 2 s of carrier
        x, _ = stream.read(BLOCK)
        ph, t = demod_block(x[:, 0])
        cal_ph.append(ph); cal_t.append(t)
    slope, _ = np.polyfit(np.concatenate(cal_t), np.concatenate(cal_ph), 1)
    print(f"Clock offset: {slope / (2 * np.pi):+.3f} Hz. Now type 'mode pot' and turn the knob.")

    plt.ion()
    fig, ax = plt.subplots(figsize=(9, 4))
    line, = ax.plot([], [])
    ax.set_xlim(0, WINDOW_S); ax.set_ylim(-3.5, 3.5)
    ax.set_xlabel("time (s)"); ax.set_ylabel("recovered phase kp*m(t) (rad)")
    buf, base = [], None
    while plt.fignum_exists(fig.number):
        x, overflow = stream.read(BLOCK)
        ph, t = demod_block(x[:, 0])
        corrected = ph - slope * t
        if base is None:
            base = corrected[0]
        buf = (buf + list(corrected - base))[-int(WINDOW_S * FS / DECIM):]
        line.set_data(np.arange(len(buf)) * DECIM / FS, buf)
        plt.pause(0.001)