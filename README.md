# Live Phase Modulation Link: ESP32 Transmitter with a Laptop I/Q Demodulator

CET 3625 Applied Analysis Laboratory, Fall 2026, midterm project. William Morales.

An ESP32 generates a phase-modulated signal

    s(t) = A cos(2π f_c t + k_p m(t)),   f_c = 4 kHz

and a computer records it through the microphone jack and recovers the message in Python
with I/Q demodulation. Measured spectra and recovered phase are compared with Bessel-function
theory (sideband heights |J_n(β)|), Carson's rule (B ≈ 2(β + 1) f_m), and the carrier null at β = 2.405.

## Repository layout

```
firmware/                 ESP32 transmitter (C++, Arduino framework, PlatformIO)
  platformio.ini          board and build settings
  src/main.cpp            40 kHz timer interrupt, phase accumulator, sine table, serial commands
receiver/                 Python receiver and analysis
  pm_dsp.py               shared math: I/Q demodulation, spectrum, Bessel sidebands, bandwidth
  pm_gui.py               live GUI (simulator, mic input, optional ESP32 control)
  simulate_pm.py          full PM chain in software, figures vs theory and vs SNR
  record.py               records the ESP32 signal from the mic input to data/
  sim_record.py           writes a simulated recording to data/ (no hardware needed)
  analyze.py              analyzes a recording: beta, sidebands vs Bessel, bandwidth
  live_view.py            simple live phase view
figures/                  result images used in the presentation
```

## How it works

**Transmitter (firmware/src/main.cpp).** A hardware timer fires 40,000 times per second. A 32-bit
phase accumulator advances by `f_c / 40000 · 2^32` per tick (2^32 counts = one full 2π, so overflow is
mod 2π for free). The message (a sine table or the potentiometer on GPIO34) is scaled by k_p and added
to the phase, and the top 10 bits index a 1024-entry sine table written to the 8-bit DAC on GPIO25.

**Circuit.** GPIO25 → R1 2 kΩ → C1 10 nF to GND (RC low-pass, ≈ 8 kHz) → R2 10 kΩ / R3 220 Ω divider
→ C2 1 µF DC block → 3.5 mm plug tip (sleeve = GND) → PC mic input.

**Receiver (receiver/pm_dsp.py, pm_gui.py).** The recording x(t) is mixed with cos(2πf_c t) and
−sin(2πf_c t), low-pass filtered to get I = (A/2)cos φ and Q = (A/2)sin φ, and the phase is
φ = unwrap(atan2(Q, I)). A straight-line fit removes the clock offset between the ESP32 and the PC.
A least-squares sine fit gives the measured β, and a Hann-windowed FFT gives the spectrum.

## Running it

Setup (once), Python 3 with Tk:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd receiver
```

Everything runs **with or without the hardware**. The simulated transmitter uses the same signal model
(including a 0.7 Hz clock offset and adjustable noise) and feeds the same receiver code.

| Task | Without hardware (simulated) | With the ESP32 + mic cable |
| --- | --- | --- |
| Live GUI | `python pm_gui.py --sim` | `python pm_gui.py --port /dev/ttyUSB0 --device <index>` |
| Make a recording | `python sim_record.py kp1 1.0` | `python record.py kp1 5` |
| Analyze a recording | `python analyze.py kp1 1.0` | `python analyze.py kp1 1.0` |
| Theory and noise figures | `python simulate_pm.py` | (not needed) |
| Live phase view | `python pm_gui.py --sim --mode pot` | `python live_view.py` |

`sim_record.py <name> <kp> [fm] [snr_db] [seconds]` makes the same kind of file as `record.py`, e.g.
`python sim_record.py null 2.405` (carrier null) or `python sim_record.py noisy 1.0 200 12` (12 dB SNR).
`sounddevice` and `pyserial` are only used in hardware mode.

Find the mic input index with `python -m sounddevice`.

Firmware (hardware mode only): open `firmware/` in VS Code with the PlatformIO extension, then Build and Upload.
Serial commands at 115200 baud: `mode carrier|sine|pot`, `kp <0-3>`, `fm <Hz>`, `fc <Hz>`, `status`.

## Results

- Hardware: k_p = 1.00 set, β = 1.00 measured; sidebands matched J₀(1) = 0.77 and J₁(1) = 0.44;
  measured 98% bandwidth matched Carson's rule (800 Hz at f_m = 200 Hz).
- Simulation (same receiver code): carrier vanished at β = 2.405; β still recovered at ~12 dB SNR.

## References

1. A. B. Downey, *Think DSP: Digital Signal Processing in Python*, Green Tea Press.
2. NIST Digital Library of Mathematical Functions, Chapter 10: Bessel Functions. https://dlmf.nist.gov/10
