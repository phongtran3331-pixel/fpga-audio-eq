import time
import numpy as np
from pynq import Overlay, allocate, MMIO

N = 1024
REPS = 200

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

# ---------- 软件 FFT 计时（PS 端 NumPy，同数据规模）----------
x_sw = (x & 0xFFFF).astype(np.int32)
x_sw = np.where(x_sw >= 32768, x_sw - 65536, x_sw).astype(np.float64)
np.fft.fft(x_sw)  # warmup
t0 = time.time()
for _ in range(REPS):
    np.fft.fft(x_sw)
t_sw = (time.time() - t0) / REPS

# ---------- 硬件 DMA -> FIR -> FFT -> DMA 计时 ----------
def hw_once():
    in_buf.flush()
    dma.recvchannel.transfer(out_buf)
    dma.sendchannel.transfer(in_buf)
    while not dma.sendchannel.idle:
        pass
    while not dma.recvchannel.idle:
        pass
    dma.sendchannel.stop()
    dma.recvchannel.stop()

hw_once()  # warmup
t0 = time.time()
for _ in range(REPS):
    hw_once()
t_hw = (time.time() - t0) / REPS

print('SOFTWARE_NUMPY_FFT_MS %.3f' % (t_sw * 1000))
print('HARDWARE_FIR_FFT_MS %.3f' % (t_hw * 1000))
print('SPEEDUP %.1f' % (t_sw / t_hw))
print('EFFECTIVE_SAMPLE_RATE %d' % int(N / t_hw))
print('ACCEL_TEST_DONE')
