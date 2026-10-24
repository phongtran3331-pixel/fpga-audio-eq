import time
import numpy as np
from pynq import Overlay, allocate, MMIO

ol = Overlay('/home/xilinx/audio_fir_fft_v5.bit')
dma = ol.axi_dma_0
dma.sendchannel._align = 4
dma.recvchannel._align = 4
N = 1024
in_buf = allocate(shape=(N,), dtype=np.uint32)
out_buf = allocate(shape=(N,), dtype=np.uint32)
fir = MMIO(0x40000000, 65536)
for i in range(32):
    fir.write(0x80 + 4 * i, 0)
fir.write(0x80 + 4 * 16, 32767)

n = np.arange(N)
x = np.zeros(N).astype(np.int64)
xin = (x & 0xFFFF).astype(np.uint32)
np.copyto(in_buf, xin)
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
top = np.argsort(mag)[-6:]
print('top bins:', sorted(top.tolist()))
print('top vals:', [int(mag[i]) for i in sorted(top.tolist())])
print('mag[100]=%.0f' % mag[100])
print('SINGLETONE_DONE')
