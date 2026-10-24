import sys, time
import numpy as np
from pynq import Overlay, allocate, MMIO

mode = sys.argv[1] if len(sys.argv) > 1 else 'ap'

LP = [26, 26, 26, 24, 20, 12, -2, -21, -48, -81, -119, -159, -198, -230,
      -250, -251, -228, -174, -85, 42, 207, 408, 641, 899, 1173, 1451,
      1721, 1971, 2189, 2362, 2484, 2546, 2546, 2484, 2362, 2189, 1971,
      1721, 1451, 1173, 899, 641, 408, 207, 42, -85, -174, -228, -251,
      -250, -230, -198, -159, -119, -81, -48, -21, -2, 12, 20, 24, 26, 26, 26]

ol = Overlay('/home/xilinx/audio_fir_fft_v6.bit')
dma = ol.axi_dma_0
dma.sendchannel._align = 4
dma.recvchannel._align = 4
N = 1024
in_buf = allocate(shape=(N,), dtype=np.uint32)
out_buf = allocate(shape=(N,), dtype=np.uint32)
fir = MMIO(0x40000000, 65536)

if mode == 'lp':
    c = LP
else:
    c = [0] * 64
    c[32] = 32767
for i in range(32):
    fir.write(0x80 + 4 * i, (c[2 * i] & 0xFFFF) | ((c[2 * i + 1] & 0xFFFF) << 16))

n = np.arange(N)
x = (0.35 * 32767 * (np.sin(2 * np.pi * 20 * n / N) + np.sin(2 * np.pi * 200 * n / N))).astype(np.int64)
np.copyto(in_buf, (x & 0xFFFF).astype(np.uint32))
in_buf.flush()

dma.recvchannel.transfer(out_buf)
dma.sendchannel.transfer(in_buf)
t1 = time.time()
while not dma.sendchannel.idle:
    if time.time() - t1 > 10:
        print('MM2S TIMEOUT')
        break
    time.sleep(0.01)
t1 = time.time()
while not dma.recvchannel.idle:
    if time.time() - t1 > 10:
        print('S2MM TIMEOUT')
        break
    time.sleep(0.01)
dma.sendchannel.stop()
dma.recvchannel.stop()

w = out_buf.astype(np.uint64)
re = (w & 0xFFFF).astype(np.int32)
im = ((w >> 16) & 0xFFFF).astype(np.int32)
re[re >= 32768] -= 65536
im[im >= 32768] -= 65536
mag = np.sqrt(re.astype(float) ** 2 + im.astype(float) ** 2)

rev = np.array([int(format(i, '010b')[::-1], 2) for i in range(N)])
magn = mag[rev]

print('MODE', mode)
print('SPEC ' + ' '.join(str(int(v)) for v in magn))
print('FILTER_DEMO_%s_DONE' % mode.upper())
