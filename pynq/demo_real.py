import time
import numpy as np
from pynq import Overlay, allocate, MMIO

# ---------- 1) synthesize a musical phrase on the PS ----------
SR = 48000
NOTES = {'C': 261.63, 'D': 293.66, 'E': 329.63, 'F': 349.23,
         'G': 392.00, 'A': 440.00, 'B': 493.88, 'C5': 523.25}
MELODY = ['C', 'C', 'G', 'G', 'A', 'A', 'G', 'F', 'F', 'E', 'E', 'D', 'D', 'C']
NOTE_DUR = 0.4

t_note = np.arange(int(SR * NOTE_DUR)) / SR
track = []
for name in MELODY:
    f0 = NOTES[name]
    env = np.minimum(t_note / 0.01, 1.0) * np.exp(-2.0 * t_note)
    note = (np.sin(2 * np.pi * f0 * t_note)
            + 0.5 * np.sin(2 * np.pi * 2 * f0 * t_note)
            + 0.25 * np.sin(2 * np.pi * 3 * f0 * t_note)) * env
    track.append(note)
music = np.concatenate(track)
music = music / np.abs(music).max() * 0.8
audio = (music * 32767).astype(np.int16)
np.save('/home/xilinx/music.npy', audio)
print('synth done: %d samples (%.1fs)' % (len(audio), len(audio) / SR))

# ---------- 2) v5 hardware pipeline: DMA -> FIR -> FFT ----------
ol = Overlay('/home/xilinx/audio_fir_fft_v5.bit')
dma = ol.axi_dma_0
dma.sendchannel._align = 4
dma.recvchannel._align = 4
N = 1024
FRAMES = len(audio) // N
in_buf = allocate(shape=(N,), dtype=np.uint32)
out_buf = allocate(shape=(N,), dtype=np.uint32)
fir = MMIO(0x40000000, 65536)

s16 = audio[:N * FRAMES].astype(np.int64)
frames = np.zeros((FRAMES, N), dtype=np.uint32)
for f in range(FRAMES):
    frames[f] = (s16[f * N:(f + 1) * N] & 0xFFFF).astype(np.uint32)

def write_coeffs(q):
    for i in range(32):
        lo = q[2 * i] & 0xFFFF
        hi = q[2 * i + 1] & 0xFFFF
        fir.write(0x80 + 4 * i, (hi << 16) | lo)

def unpack(buf):
    w = buf.astype(np.uint64)
    re = (w & 0xFFFF).astype(np.int32)
    im = ((w >> 16) & 0xFFFF).astype(np.int32)
    re[re >= 32768] -= 65536
    im[im >= 32768] -= 65536
    return re, im

def run_frame(x):
    np.copyto(in_buf, x)
    in_buf.flush()
    dma.sendchannel.transfer(in_buf)
    dma.recvchannel.transfer(out_buf)
    t0 = time.time()
    while not dma.sendchannel.idle:
        if time.time() - t0 > 10:
            print('MM2S TIMEOUT')
            break
        time.sleep(0.1)
    t0 = time.time()
    while not dma.recvchannel.idle:
        if time.time() - t0 > 10:
            print('S2MM TIMEOUT')
            break
        time.sleep(0.1)
    dma.sendchannel.stop()
    dma.recvchannel.stop()
    return unpack(out_buf)

def spectrum():
    acc = np.zeros(N)
    for f in range(FRAMES):
        re, im = run_frame(frames[f])
        acc += re.astype(float) ** 2 + im.astype(float) ** 2
    return np.sqrt(acc / FRAMES)

ALLPASS = [0] * 64
ALLPASS[32] = 32767
LP = [-10, -26, -29, -14, 17, 50, 61, 31, -37, -109, -130, -64, 76, 217, 254, 123,
      -142, -398, -459, -220, 254, 708, 822, 397, -468, -1347, -1637, -848, 1111,
      3807, 6403, 7993, 7993, 6403, 3807, 1111, -848, -1637, -1347, -468, 397, 822,
      708, 254, -220, -459, -398, -142, 123, 254, 217, 76, -64, -130, -109, -37, 31,
      61, 50, 17, -14, -29, -26, -10]

write_coeffs(ALLPASS)
print('AP coeffs set')
mag_ap = spectrum()

write_coeffs(LP)
print('LP coeffs set')
mag_lp = spectrum()

def bandfrac(mag, hi):
    e = mag ** 2
    return e[:hi].sum() / e.sum()

print('frames=%d peak_ap=%.0f peak_lp=%.0f' % (FRAMES, mag_ap.max(), mag_lp.max()))
print('energy_below_bin64: AP=%.3f LP=%.3f' % (bandfrac(mag_ap, 64), bandfrac(mag_lp, 64)))
print('MAG_AP:', ','.join('%.0f' % v for v in mag_ap[:512]))
print('MAG_LP:', ','.join('%.0f' % v for v in mag_lp[:512]))
print('ALL_DONE')
