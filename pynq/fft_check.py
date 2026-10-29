import sys, time
import numpy as np
from pynq import Overlay, allocate, MMIO

mode = sys.argv[1] if len(sys.argv) > 1 else 'A'

ol = Overlay('/home/xilinx/audio_fir_fft_v6.bit')
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
A = 0.4 * 32767

if mode == 'A':
    re = (A * np.cos(2 * np.pi * 100 * n / N)).astype(np.int64)
    im = (A * np.sin(2 * np.pi * 100 * n / N)).astype(np.int64)
else:
    re = (A * np.cos(2 * np.pi * 100 * n / N)).astype(np.int64)
    im = np.zeros(N, dtype=np.int64)

np.copyto(in_buf, ((re & 0xFFFF) | ((im & 0xFFFF) << 16)).astype(np.uint32))
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
ore = (w & 0xFFFF).astype(np.int32)
oim = ((w >> 16) & 0xFFFF).astype(np.int32)
ore[ore >= 32768] -= 65536
oim[oim >= 32768] -= 65536
mag_br = np.sqrt(ore.astype(float) ** 2 + oim.astype(float) ** 2)

# FFT 核输出是倒位序：第 j 个输出 = 自然序 bin bitrev10(j)
rev = np.array([int(format(i, '010b')[::-1], 2) for i in range(N)])
mag = mag_br[rev]  # 现在 mag[k] = 自然序 bin k 的幅值

top = sorted(np.argsort(mag)[-8:].tolist())
big2 = sorted(np.argsort(mag)[-2:].tolist())  # 幅值最大的两个 bin（按 bin 编号排序）
print('MODE %s top bins (自然序): %s' % (mode, top))
print('MODE %s top vals: %s' % (mode, [int(mag[i]) for i in top]))
print('MODE %s mag[100]=%.0f mag[924]=%.0f argmax=%d' % (mode, mag[100], mag[924], int(np.argmax(mag))))

if mode == 'A':
    ok = (int(np.argmax(mag)) == 100) and (mag[924] < mag[100] / 5)
    print('MODE A 预期: 单峰在100(约13106), 924≈0 ->', 'PASS' if ok else 'FAIL')
else:
    ok = (big2 == [100, 924]) and (abs(mag[100] - mag[924]) < 0.3 * max(mag[100], mag[924]))
    print('MODE B 预期: 100和924双峰(各约6553) ->', 'PASS' if ok else 'FAIL')
print('FFT_CHECK_%s_DONE' % mode)
