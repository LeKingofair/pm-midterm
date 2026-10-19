"""PM Lab: one-window dashboard for the ESP32 phase-modulation link.

Shows the live spectrum (with the Bessel-function prediction), the recovered
phase, and the numbers a presentation needs: measured beta, Carson bandwidth,
clock drift and input level.

  python pm_gui.py --sim                       # no hardware: built-in simulator
  python pm_gui.py                             # listen to the mic jack
  python pm_gui.py --port /dev/ttyUSB0         # mic jack + control the ESP32 from the GUI
  python pm_gui.py --device 3                  # pick an input from `python -m sounddevice`

Close the PlatformIO serial monitor before using --port: only one program can
hold the serial port at a time.
"""
import argparse
import time
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, RadioButtons, Slider
from scipy.signal import butter, sosfilt
from scipy.special import jv

FS, FC = 48000, 4000.0
NFFT = 24000                      # 0.5 s window for the spectrum
BG, PANEL, INK, DIM = "#0f1419", "#171d24", "#e6edf3", "#8b98a5"
BLUE, ORANGE, GREEN, RED = "#4fc3f7", "#ffb74d", "#81c784", "#ef5350"
_HERE = Path(__file__).resolve().parent
FIG_DIR = (_HERE.parent if _HERE.name == "receiver" else _HERE) / "figures"   # pm-midterm/figures or ./figures


# ---------------------------------------------------------------- signal sources
class SimSource:
    """Software stand-in for ESP32 + sound card, including a clock offset and noise."""

    def __init__(self):
        self.mode, self.kp, self.fm, self.knob = "sine", 1.0, 200.0, 0.0
        self.snr_db, self.df, self.amp = 60.0, 0.7, 0.3
        self.n, self.t0, self.rng = 0, None, np.random.default_rng(1)

    def read(self):
        now = time.perf_counter()
        if self.t0 is None:
            self.t0 = now
        target = int((now - self.t0) * FS)
        n_new = min(target - self.n, FS)
        if n_new <= 0:
            return np.zeros(0)
        t = (self.n + np.arange(n_new)) / FS
        self.n += n_new
        m = {"carrier": 0.0, "sine": np.sin(2 * np.pi * self.fm * t), "pot": self.knob}[self.mode]
        x = self.amp * np.cos(2 * np.pi * (FC + self.df) * t + self.kp * m)
        sigma = np.sqrt(self.amp ** 2 / 2 / 10 ** (self.snr_db / 10))
        return x + self.rng.normal(0, sigma, t.size)


class MicSource:
    def __init__(self, device):
        import queue
        import sounddevice as sd
        self.q = queue.Queue()
        self.stream = sd.InputStream(samplerate=FS, channels=1, device=device, blocksize=2400,
                                     callback=lambda d, f, t, s: self.q.put(d[:, 0].astype(float)))
        self.stream.start()

    def read(self):
        out = []
        while not self.q.empty():
            out.append(self.q.get_nowait())
        return np.concatenate(out) if out else np.zeros(0)


class Esp:
    """Sends the firmware's text commands over USB serial."""

    def __init__(self, port):
        import serial
        self.ser = serial.Serial(port, 115200, timeout=0.1)
        time.sleep(2.5)           # opening the port resets the board; let it boot
        self.ser.reset_input_buffer()

    def send(self, cmd):
        self.ser.write((cmd + "\n").encode())


# ---------------------------------------------------------------- I/Q demodulator
class Demod:
    D = 12                        # keep the recovered phase at 4 kHz

    def __init__(self):
        self.sos = butter(4, 1500, fs=FS, output="sos")
        z = np.zeros((self.sos.shape[0], 2))
        self.zi, self.zq = z.copy(), z.copy()
        self.n, self.last = 0, 0.0
        self.T, self.P = np.zeros(0), np.zeros(0)
        self.slope, self.ref = 0.0, 0.0          # clock drift (rad/s) and phase zero

    def feed(self, x):
        g = self.n + np.arange(x.size)
        t = g / FS
        self.n += x.size
        i, self.zi = sosfilt(self.sos, x * np.cos(2 * np.pi * FC * t), zi=self.zi)
        q, self.zq = sosfilt(self.sos, -x * np.sin(2 * np.pi * FC * t), zi=self.zq)
        ph = np.unwrap(np.concatenate(([self.last], np.arctan2(q, i))))[1:]
        self.last = ph[-1]
        keep = g % self.D == 0
        keep_max = 4000 * 30
        self.T = np.concatenate([self.T, t[keep]])[-keep_max:]
        self.P = np.concatenate([self.P, ph[keep]])[-keep_max:]

    def corrected(self, seconds):
        k = int(seconds * FS / self.D)
        T, P = self.T[-k:], self.P[-k:]
        return T, P - self.slope * T - self.ref


def fit_tone(t, y, f):
    """Least squares y = a sin + b cos + c + d t at a known frequency f."""
    M = np.column_stack([np.sin(2 * np.pi * f * t), np.cos(2 * np.pi * f * t),
                         np.ones_like(t), t - t[0]])
    c, *_ = np.linalg.lstsq(M, y, rcond=None)
    return np.hypot(c[0], c[1]), M[:, :2] @ c[:2], M[:, 2:] @ c[2:]   # amplitude, tone, slow drift


def sideband_peaks(f, X, f0, fm, nmax=8):
    n = np.arange(-nmax, nmax + 1)
    search = min(6.0, 0.4 * fm)
    pk = []
    for k in n:
        sel = np.abs(f - (f0 + k * fm)) <= search
        pk.append(X[sel].max() if sel.any() else 0.0)
    return n, np.array(pk)


def power_bandwidth(pk, fm, fraction=0.98):
    nmax = (pk.size - 1) // 2
    p = pk ** 2 / np.sum(pk ** 2)
    for N in range(nmax + 1):
        if p[nmax - N: nmax + N + 1].sum() >= fraction:
            return 2 * N * fm
    return 2 * nmax * fm


# ---------------------------------------------------------------- the app
class PMLab:
    def __init__(self, source, esp, args):
        self.src, self.esp, self.sim = source, esp, isinstance(source, SimSource)
        self.can_control = self.sim or esp is not None
        self.dm = Demod()
        self.raw = np.zeros(0)
        self.mode, self.kp, self.fm, self.knob = args.mode, args.kp, args.fm, args.knob
        self.sent, self.paused, self.t_start = {}, False, time.perf_counter()
        self.cal_ok, self._switching = False, False
        self.cal_state, self.auto_cal_done, self.prev_mode = None, False, None
        self.freqs = np.fft.rfftfreq(NFFT, 1 / FS)
        self.band = (self.freqs > FC - 2200) & (self.freqs < FC + 2200)
        self.win = np.hanning(NFFT)
        self.status = ("Click Calibrate with the ESP32 in carrier mode." if not self.can_control
                       else "Calibrating clock drift...")
        self.build()
        self.push()

    # ---- layout
    def build(self):
        plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": DIM,
                             "axes.labelcolor": INK, "xtick.color": DIM, "ytick.color": DIM,
                             "text.color": INK})
        self.fig = plt.figure(figsize=(13, 7.2), facecolor=BG)
        self.fig.canvas.manager.set_window_title("PM Lab")
        self.fig.text(0.04, 0.955, "PM Lab", fontsize=18, fontweight="bold", color=INK)
        self.fig.text(0.125, 0.958, "ESP32 phase-modulation link  |  s(t) = A cos(2π f_c t + k_p m(t))",
                      fontsize=11, color=DIM)

        self.ax_s = self.fig.add_axes([0.065, 0.54, 0.60, 0.35], facecolor=PANEL)
        self.ax_p = self.fig.add_axes([0.065, 0.085, 0.60, 0.36], facecolor=PANEL)
        for ax in (self.ax_s, self.ax_p):
            ax.grid(color="#26303a", lw=0.8)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
        self.ax_s.set_title("Spectrum  (0.5 s Hann window)", loc="left", fontsize=11, color=INK)
        self.ax_s.set_xlim(FC - 2000, FC + 2000)
        self.ax_s.set_ylim(0, 1.08)
        self.ax_s.set_xlabel("frequency (Hz)")
        self.ax_s.set_ylabel("normalized amplitude")
        (self.l_spec,) = self.ax_s.plot([], [], color=BLUE, lw=1.3)
        (self.l_bes,) = self.ax_s.plot([], [], "o", mfc="none", mec=ORANGE, ms=9, mew=1.8,
                                       label="Bessel theory |Jₙ(k_p)|")
        self.ax_s.legend(loc="upper right", frameon=False, labelcolor=ORANGE, fontsize=9)

        self.ax_p.set_title("Recovered phase", loc="left", fontsize=11, color=INK)
        self.ax_p.set_ylabel("phase (rad)")
        (self.l_ph,) = self.ax_p.plot([], [], color=GREEN, lw=1.4)
        (self.l_fit,) = self.ax_p.plot([], [], color=ORANGE, lw=1.2, ls="--")
        self.l_hi = self.ax_p.axhline(0, color=DIM, lw=0.8, ls=":")
        self.l_lo = self.ax_p.axhline(0, color=DIM, lw=0.8, ls=":")

        self.readout = self.fig.text(0.715, 0.915, "", va="top", fontsize=10.5,
                                     family="monospace", color=INK, linespacing=1.55)

        ax_r = self.fig.add_axes([0.715, 0.455, 0.26, 0.115], facecolor=PANEL)
        self.radio = RadioButtons(ax_r, ["carrier", "sine", "pot"],
                                  active=["carrier", "sine", "pot"].index(self.mode),
                                  activecolor=BLUE)
        for lab in self.radio.labels:
            lab.set_color(INK)
            lab.set_fontsize(11)
        self.radio.on_clicked(self.on_mode)
        self.fig.text(0.715, 0.578, "MESSAGE MODE", fontsize=8.5, color=DIM)

        def slider(y, label, lo, hi, val):
            ax = self.fig.add_axes([0.80, y, 0.15, 0.022], facecolor=PANEL)
            s = Slider(ax, label, lo, hi, valinit=val, color=BLUE)
            s.label.set_color(INK)
            s.label.set_fontsize(10)
            s.valtext.set_color(DIM)
            return s

        self.s_kp = slider(0.405, "k_p (rad)", 0.0, 3.0, self.kp)
        self.s_fm = slider(0.360, "f_m (Hz)", 50, 400, self.fm)
        self.s_kp.on_changed(lambda v: setattr(self, "kp", v))
        self.s_fm.on_changed(lambda v: setattr(self, "fm", v))
        if self.sim:
            self.s_knob = slider(0.315, "knob (sim)", -1, 1, self.knob)
            self.s_snr = slider(0.270, "SNR dB (sim)", 5, 60, 60)
            self.s_knob.on_changed(lambda v: setattr(self.src, "knob", v))
            self.s_snr.on_changed(lambda v: setattr(self.src, "snr_db", v))

        def button(x, y, w, text, cb):
            ax = self.fig.add_axes([x, y, w, 0.05])
            b = Button(ax, text, color=PANEL, hovercolor="#26303a")
            b.label.set_color(INK)
            b.on_clicked(cb)
            return b

        self.b_cal = button(0.715, 0.185, 0.125, "Calibrate drift", lambda e: self.start_cal())
        self.b_pause = button(0.85, 0.185, 0.125, "Pause", self.toggle_pause)
        self.b_save = button(0.715, 0.12, 0.26, "Save PNG to figures/", self.save)
        self.status_txt = self.fig.text(0.715, 0.075, "", fontsize=9, color=DIM, wrap=True, va="top")

    # ---- controls
    def on_mode(self, label):
        if self.cal_state is not None and not self._switching:
            self.prev_mode = label     # finish calibrating (< 3 s), then switch to the user's choice
            self.status = f"Calibrating drift... switching to {label} in a moment."
            return
        self.mode = label

    def set_radio(self, label):
        self._switching = True
        self.radio.set_active(["carrier", "sine", "pot"].index(label))
        self._switching = False

    def toggle_pause(self, _):
        self.paused = not self.paused
        self.b_pause.label.set_text("Resume" if self.paused else "Pause")

    def save(self, _=None):
        FIG_DIR.mkdir(exist_ok=True)
        path = FIG_DIR / time.strftime("pm_gui_%Y%m%d_%H%M%S.png")
        self.fig.savefig(path, dpi=150, facecolor=self.fig.get_facecolor())
        self.status = f"Saved {path.name}"

    def push(self):
        """Send current settings to the simulator or the ESP32 (only what changed)."""
        if self.sim:
            self.src.mode, self.src.kp, self.src.fm = self.mode, self.kp, self.fm
            self.src.knob = self.s_knob.val
        if self.esp is not None:
            for key, text in (("mode", f"mode {self.mode}"), ("kp", f"kp {self.kp:.3f}"),
                              ("fm", f"fm {self.fm:.1f}")):
                if self.sent.get(key) != text:
                    self.esp.send(text)
                    self.sent[key] = text

    # ---- drift calibration: 2 s of unmodulated carrier fixes the clock offset
    def start_cal(self, _=None):
        self.cal_state, self.cal_n0 = "settle", self.dm.n
        if self.can_control:
            self.prev_mode = self.mode
            self.mode = "carrier"
            self.set_radio("carrier")
            self.status = "Calibrating: carrier mode for 2.5 s..."
        else:
            self.status = "Calibrating on the current signal. It must be in carrier mode."

    def run_cal(self):
        if self.cal_state is None:
            return
        el = (self.dm.n - self.cal_n0) / FS          # seconds of audio since the request
        if self.cal_state == "settle" and el > 1.0:  # let the carrier-mode command take effect
            self.cal_from, self.cal_state = self.dm.n / FS, "collect"
        elif self.cal_state == "collect" and el > 3.0:
            m = self.dm.T > self.cal_from
            if m.sum() > 400:
                t, p = self.dm.T[m], self.dm.P[m]
                slope, icpt = np.polyfit(t, p, 1)
                rms = np.sqrt(np.mean((p - (slope * t + icpt)) ** 2))
                if rms < 1.5:
                    self.dm.slope, self.dm.ref = slope, icpt
                    self.cal_ok = True
                    self.status = f"Calibrated: clock offset {slope / (2 * np.pi):+.3f} Hz removed."
                else:
                    self.status = (f"Calibration failed (phase noise {rms:.2f} rad). The signal was "
                                   "not a clean carrier. Check the level, then click Calibrate drift.")
            self.cal_state = None
            if self.can_control and self.prev_mode:
                self.mode = self.prev_mode
                self.set_radio(self.mode)

    # ---- one refresh
    def update(self, _=None):
        x = self.src.read()
        if x.size:
            self.raw = np.concatenate([self.raw, x])[-NFFT:]
            self.dm.feed(x)
        if not self.auto_cal_done and self.can_control and time.perf_counter() - self.t_start > 1.5:
            self.auto_cal_done = True
            self.start_cal()
        self.run_cal()
        self.push()
        if self.paused or self.raw.size < NFFT:
            self.fig.canvas.draw_idle()
            return

        # spectrum and Bessel prediction
        X = np.abs(np.fft.rfft(self.raw * self.win)) / (self.win.sum() / 2)
        f0 = FC + self.dm.slope / (2 * np.pi)
        n, pk = sideband_peaks(self.freqs, X, f0, self.fm)
        if self.mode == "sine":
            scale = np.sqrt(np.sum(pk ** 2)) or 1.0
            self.l_bes.set_data(f0 + n * self.fm, np.abs(jv(n, self.kp)))
        else:
            scale = X[self.band].max() or 1.0
            self.l_bes.set_data([], [])
        self.l_spec.set_data(self.freqs[self.band], X[self.band] / scale)

        # recovered phase, drawn over a window that suits the mode
        beta = None
        if self.mode == "sine":
            span = 6.0 / self.fm
            T, Y = self.dm.corrected(max(span, 0.3))
            a, tone, base = fit_tone(T, Y, self.fm)   # short window: follows slow clock wander
            Y = Y - base                              # remove offset + drift continuously
            m = T > T[-1] - span
            Tw, Yw = T[m], Y[m]
            beta = a if self.cal_state is None else None
            self.l_ph.set_data((Tw - Tw[0]) * 1e3, Yw)
            self.l_fit.set_data((Tw - Tw[0]) * 1e3, tone[m])
            self.ax_p.set_xlim(0, span * 1e3)
            self.ax_p.set_xlabel("time (ms)")
        else:
            T, Y = self.dm.corrected(5.0)
            if self.mode == "carrier" or not self.cal_ok:
                p = np.polyfit(T - T[-1], Y, 1)       # no valid calibration: remove drift in the window
                Y = Y - np.polyval(p, T - T[-1])
            # pot mode with a valid calibration: Y is already absolute phase (drift and offset removed)
            self.l_ph.set_data(T - T[-1], Y)
            self.l_fit.set_data([], [])
            self.ax_p.set_xlim(-5, 0)
            self.ax_p.set_xlabel("time before now (s)")
        lim = self.kp if self.mode != "carrier" else 0.0
        self.l_hi.set_ydata([lim, lim])
        self.l_lo.set_ydata([-lim, -lim])
        top = max(1.2, 1.25 * max(abs(Y).max(), lim))
        self.ax_p.set_ylim(-top, top)

        # readout
        level = np.abs(self.raw).max()
        tag = "CLIPPING" if level > 0.95 else "too quiet" if level < 0.01 else "ok"
        lines = [f"source   {'simulator' if self.sim else 'mic jack'}"
                 f"{'  + ESP32 link' if self.esp else ''}",
                 f"mode     {self.mode}",
                 f"k_p set  {self.kp:5.2f} rad"]
        if self.mode == "sine" and beta is not None:
            bw98 = power_bandwidth(pk, self.fm) if pk.sum() > 0 else 0
            lines += [f"beta     {beta:5.2f} rad  (measured)",
                      f"Carson   {2 * (self.kp + 1) * self.fm:5.0f} Hz",
                      f"98% BW   {bw98:5.0f} Hz"]
        elif self.mode == "pot":
            lines += [f"phase    {Y[-200:].mean():+5.2f} rad  (knob)"]
        lines += [f"clock    {self.dm.slope / (2 * np.pi):+6.3f} Hz",
                  f"level    {level:5.2f}  {tag}"]
        self.readout.set_text("\n".join(lines))
        self.status_txt.set_text(self.status)
        self.fig.canvas.draw_idle()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", action="store_true", help="use the built-in simulator")
    ap.add_argument("--device", type=int, default=None, help="sounddevice input index")
    ap.add_argument("--port", default=None, help="ESP32 serial port, e.g. /dev/ttyUSB0")
    ap.add_argument("--mode", default="sine", choices=["carrier", "sine", "pot"])
    ap.add_argument("--kp", type=float, default=1.0)
    ap.add_argument("--fm", type=float, default=200.0)
    ap.add_argument("--knob", type=float, default=0.0)
    ap.add_argument("--snapshot", help="run for --seconds, save a PNG, exit (no window)")
    ap.add_argument("--seconds", type=float, default=6.0)
    args = ap.parse_args()

    esp = Esp(args.port) if args.port else None      # opening the port resets the ESP32: do it first
    src = SimSource() if args.sim else MicSource(args.device)
    app = PMLab(src, esp, args)
    if args.snapshot:
        end = time.perf_counter() + args.seconds
        while time.perf_counter() < end:
            app.update()
            time.sleep(0.04)
        Path(args.snapshot).resolve().parent.mkdir(parents=True, exist_ok=True)
        app.fig.savefig(args.snapshot, dpi=110, facecolor=app.fig.get_facecolor())
        return
    app.timer = app.fig.canvas.new_timer(interval=60)
    app.timer.add_callback(app.update)
    app.timer.start()
    plt.show()


if __name__ == "__main__":
    main()