import time
import wave
import numpy as np
from pynq import Overlay, allocate, MMIO

# ---------- 1) synthesize a public-domain melody (Twinkle Twinkle) ----------
SR = 48000
NOTES = {'C': 261.63, 'D': 293.66, 'E': 329.63, 'F': 349.23,
         'G': 392.00, 'A': 440.00, 'B': 493.88, 'C5': 523.25}
MELODY = ['C', 'C', 'G', 'G', 'A', 'A', 'G', 'F', 'F', 'E', 'E', 'D', 'D', 'C']
NOTE_DUR = 0.35

t_note = np.arange(int(SR * NOTE_DUR)) / SR
track = []
for name in MELODY:
    f0 = NOTES[name]
    env = np.minimum(t_note / 0.01, 1.0) * np.exp(-2.0 * t_note)
    note = np.zeros_like(t_note)
    for k in range(1, 11):
        note += (1.0 / k) * np.sin(2 * np.pi * k * f0 * t_note)
    note *= env
    track.append(note)
music = np.concatenate(track)
music = music / np.abs(music).max() * 0.8
audio = (music * 32767).astype(np.int16)
print('synth done: %.1fs' % (len(audio) / SR))

# ---------- 2) low-pass coefficients, 64 taps, cutoff ~650 Hz ----------
N_TAPS = 64
fc = 650.0 / (SR / 2.0)
n = np.arange(N_TAPS)
h = np.sinc(2 * fc * (n - (N_TAPS - 1) / 2.0)) * 2 * fc
h *= np.hamming(N_TAPS)
h = h / h.sum()
LP = (h * 32767 * 0.95).astype(np.int64).tolist()
ALLPASS = [0] * 64
ALLPASS[32] = 32767

# ---------- 3) hardware pipeline on v6 bitstream ----------
# v6 = FIR -> FFT. The PL output is the *spectrum* of the FIR-filtered
# frame, so we recover the filtered time signal with an IFFT on the board.
# Overlap-add (Hann, 50% hop) removes the circular-convolution seam.
ol = Overlay('/home/xilinx/audio_fir_fft_v6.bit')
dma = ol.axi_dma_0
dma.sendchannel._align = 4
dma.recvchannel._align = 4
N = 1024
HOP = 512
fir = MMIO(0x40000000, 65536)
rev = np.array([int(format(i, '010b')[::-1], 2) for i in range(N)])
win = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N) / N)

in_buf = allocate(shape=(N,), dtype=np.uint32)
out_buf = allocate(shape=(N,), dtype=np.uint32)

s16 = audio.astype(np.int64)
nframes = (len(s16) - N) // HOP + 1

def run_all(q):
    for i in range(32):
        fir.write(0x80 + 4 * i, 0)
    for i in range(32):
        lo = q[2 * i] & 0xFFFF
        hi = q[2 * i + 1] & 0xFFFF
        fir.write(0x80 + 4 * i, (hi << 16) | lo)
    out = np.zeros(HOP * (nframes - 1) + N)
    for f in range(nframes):
        seg = s16[f * HOP:f * HOP + N]
        np.copyto(in_buf, (seg & 0xFFFF).astype(np.uint32))
        in_buf.flush()
        dma.recvchannel.transfer(out_buf)
        dma.sendchannel.transfer(in_buf)
        t0 = time.time()
        while not dma.sendchannel.idle:
            if time.time() - t0 > 10:
                print('MM2S TIMEOUT')
                break
            time.sleep(0.001)
        t0 = time.time()
        while not dma.recvchannel.idle:
            if time.time() - t0 > 10:
                print('S2MM TIMEOUT')
                break
            time.sleep(0.001)
        dma.sendchannel.stop()
        dma.recvchannel.stop()
        w = out_buf.astype(np.uint64)
        re = (w & 0xFFFF).astype(np.int32)
        im = ((w >> 16) & 0xFFFF).astype(np.int32)
        re[re >= 32768] -= 65536
        im[im >= 32768] -= 65536
        spec = (re + 1j * im)[rev]      # natural-order spectrum
        y = np.fft.ifft(spec).real      # filtered time signal
        out[f * HOP:f * HOP + N] += y * win
        if f % 64 == 0:
            print('frame %d/%d' % (f, nframes))
    return out

print('PASS1: allpass through PL ...')
ap = run_all(ALLPASS)
print('PASS2: lowpass through PL ...')
lp = run_all(LP)

def save_wav(path, data):
    peak = max(1, int(np.abs(data).max()))
    d = (data * (30000.0 / peak)).astype(np.int16)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(d.tobytes())

save_wav('/home/xilinx/out_ap.wav', ap)
save_wav('/home/xilinx/out_lp.wav', lp)

def bandfrac(data, hz):
    F = np.fft.rfft(data.astype(float))
    mag = np.abs(F)
    e = mag ** 2
    bin_hi = int(hz / (SR / len(data)))
    return e[:bin_hi].sum() / e.sum()

print('energy_below_1kHz: AP=%.3f LP=%.3f' % (bandfrac(ap, 1000), bandfrac(lp, 1000)))
print('AP_WAV_READY /home/xilinx/out_ap.wav')
print('LP_WAV_READY /home/xilinx/out_lp.wav')
print('PLAY_DEMO_DONE')
