# 用4种候选模型模拟板上数据通路，与实测top bins比对
# 输入与 ifft_test.py 完全一致：FIR=纯延迟16（不影响幅值），FFT/IFFT x 截断
import numpy as np

N = 1024
n = np.arange(N)
A = 0.4 * 32767

def board_mag(Yfull):
    # 板端只取低16bit作为re/im（有符号）
    re = np.mod(Yfull.real.astype(np.int64), 65536)
    im = np.mod(Yfull.imag.astype(np.int64), 65536)
    re[re >= 32768] -= 65536
    im[im >= 32768] -= 65536
    return np.sqrt(re.astype(float) ** 2 + im.astype(float) ** 2)

def report(name, mag):
    top = sorted(np.argsort(mag)[-8:].tolist())
    print('%s top bins: %s' % (name, top))
    print('%s top vals: %s' % (name, [int(mag[i]) for i in top]))
    print('%s mag[100]=%.0f mag[924]=%.0f argmax=%d' % (name, mag[100], mag[924], int(np.argmax(mag))))

def wrap_scale(F, shift):
    # scaled模式：每级右移，总移位=shift；用floor除法模拟arithmetic shift
    return np.floor(F.astype(np.float64) / (2 ** shift))

for mode in ['A', 'B']:
    if mode == 'A':
        re = (A * np.cos(2 * np.pi * 100 * n / N)).astype(np.int64)
        im = (A * np.sin(2 * np.pi * 100 * n / N)).astype(np.int64)
    else:
        re = (A * np.cos(2 * np.pi * 100 * n / N)).astype(np.int64)
        im = np.zeros(N, dtype=np.int64)
    x = (re & 0xFFFF).astype(np.uint32) | ((im & 0xFFFF).astype(np.uint32) << 16)
    # 还原为复数（低16bit re, 高16bit im，有符号）
    xr = np.mod(x, 65536).astype(np.int64); xr[xr >= 32768] -= 65536
    xi = np.mod(x >> 16, 65536).astype(np.int64); xi[xi >= 32768] -= 65536
    xc = xr.astype(np.float64) + 1j * xi.astype(np.float64)

    F = np.fft.fft(xc)          # 正确FFT
    Fi = np.fft.ifft(xc) * N    # 无1/N的IFFT核输出（unscaled IFFT = N*IDFT）

    print('==== MODE %s ====' % mode)
    print('--- 实测 ---')
    if mode == 'A':
        print('top bins: [76, 94, 107, 143, 331, 479, 587, 991]')
        print('top vals: [45322, 42103, 41742, 41979, 41214, 41225, 42972, 42982]')
        print('mag[100]=26240 mag[924]=13602 argmax=76')
    else:
        print('top bins: [80, 81, 143, 182, 219, 243, 347, 420]')
        print('top vals: [44403, 43273, 43948, 44822, 42554, 43149, 43138, 43139]')
        print('mag[100]=17988 mag[924]=9009 argmax=182')

    # 模型1: FFT scaled(>>10)
    report('M1 FFT-scaled', board_mag(wrap_scale(F, 10)))
    # 模型2: FFT unscaled 直接截低16bit
    report('M2 FFT-unscaled', board_mag(F))
    # 模型3: IFFT scaled(>>10)：y[m]=F[(N-m)%N]>>10
    Frev = F[(N - n) % N]
    report('M3 IFFT-scaled', board_mag(wrap_scale(Frev, 10)))
    # 模型4: IFFT unscaled
    Firev = Fi[(N - n) % N]
    report('M4 IFFT-unscaled', board_mag(Firev))
    print()
