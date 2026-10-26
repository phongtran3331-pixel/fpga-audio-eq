import time
import numpy as np
from pynq import Overlay, allocate, MMIO

N = 1024
REPS = 20

ol = Overlay('/home/xilinx/audio_fir_fft_v6.bit')
dma = ol.axi_dma_0
dma.sendchannel._align = 4
dma.recvchannel._align = 4
in_buf = allocate(shape=(N,), dtype=np.uint32)
out_buf = allocate(shape=(N,), dtype=np.uint32)
fir = MMIO(0x40000000, 65536)
for i in range(32):
    fir.write(0x80 + 4 * i, 0)
fir.write(0x80 + 4 * 16, 32767)

n = np.arange(N)
x = (0.35 * 32767 * (np.sin(2 * np.pi * 20 * n / N) + np.sin(2 * np.pi * 200 * n / N))).astype(np.int64)
np.copyto(in_buf, (x & 0xFFFF).astype(np.uint32))

T = {'rt': 0.0, 'st': 0.0, 'rwait': 0.0, 'swait': 0.0, 'rstop': 0.0, 'sstop': 0.0}

# 预热
dma.recvchannel.transfer(out_buf)
dma.sendchannel.transfer(in_buf)
while not dma.sendchannel.idle:
    pass
while not dma.recvchannel.idle:
    pass
dma.sendchannel.stop()
dma.recvchannel.stop()

for _ in range(REPS):
    in_buf.flush()
    t0 = time.time()
    dma.recvchannel.transfer(out_buf)
    t1 = time.time()
    dma.sendchannel.transfer(in_buf)
    t2 = time.time()
    while not dma.sendchannel.idle:
        pass
    t3 = time.time()
    while not dma.recvchannel.idle:
        pass
    t4 = time.time()
    dma.sendchannel.stop()
    t5 = time.time()
    dma.recvchannel.stop()
    t6 = time.time()
    T['rt'] += t1 - t0
    T['st'] += t2 - t1
    T['swait'] += t3 - t2
    T['rwait'] += t4 - t3
    T['sstop'] += t5 - t4
    T['rstop'] += t6 - t5

tot = sum(T.values())
print('RECV_TRANSFER %.2f ms' % (T['rt'] / REPS * 1000))
print('SEND_TRANSFER %.2f ms' % (T['st'] / REPS * 1000))
print('SEND_WAIT %.2f ms' % (T['swait'] / REPS * 1000))
print('RECV_WAIT %.2f ms' % (T['rwait'] / REPS * 1000))
print('SEND_STOP %.2f ms' % (T['sstop'] / REPS * 1000))
print('RECV_STOP %.2f ms' % (T['rstop'] / REPS * 1000))
print('TOTAL_PER_FRAME %.2f ms' % (tot / REPS * 1000))
print('ACCEL4_DONE')
