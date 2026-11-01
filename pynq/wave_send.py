# 板端：生成双音测试信号 -> 硬件 FIR+FFT 处理（全通 / 低通两组系数）
#       PS 端 IFFT 重建原波与滤波波形 -> 经串口发送给 PC 的 wave_view.py
# 用法（串口控制台，需 sudo）：
#   stty -F /dev/ttyPS0 460800        # 先把串口提速（PC 端也要切到 460800）
#   sudo python3 /home/xilinx/wave_send.py
import base64
import sys
import time

import numpy as np
from pynq import Overlay, allocate, MMIO

BIT = '/home/xilinx/audio_fir_fft_v6.bit'
N = 1024
SR = 48000

LP = [26, 26, 26, 24, 20, 12, -2, -21, -48, -81, -119, -159, -198, -230,
      -250, -251, -228, -174, -85, 42, 207, 408, 641, 899, 1173, 1451,
      1721, 1971, 2189, 2362, 2484, 2546, 2546, 2484, 2362, 2189, 1971,
      1721, 1451, 1173, 899, 641, 408, 207, 42, -85, -174, -228, -251,
      -250, -230, -198, -159, -119, -81, -48, -21, -2, 12, 20, 24, 26, 26, 26]
ALLPASS = [0] * 64
ALLPASS[32] = 32767

# 10 位倒位序表：FFT 核输出第 j 项 = 自然序 bin bitrev10(j)
REV = np.array([int(format(i, '010b')[::-1], 2) for i in range(N)])


def write_coeffs(fir, q):
    for i in range(32):
        lo = q[2 * i] & 0xFFFF
        hi = q[2 * i + 1] & 0xFFFF
        fir.write(0x80 + 4 * i, (hi << 16) | lo)


def make_frames(x):
    """两端各补半个 hop 的零，再切 50% 重叠的 1024 点帧，打包 32bit（实部低 16 位，虚部 0）。
    补零让重叠相加的窗归一化在全段成立，重建后按原长裁回即可。"""
    hop = N // 2
    ext = np.zeros(len(x) + 2 * hop + N, dtype=np.int64)
    ext[hop:hop + len(x)] = x
    n_frames = (len(x) + 2 * hop - N) // hop + 1
    frames = []
    for f in range(n_frames):
        s = f * hop
        frames.append((ext[s:s + N] & 0xFFFF).astype(np.uint32))
    return np.array(frames, dtype=np.uint32), hop


def hw_spectrum(ol, dma, frames):
    """逐帧过 DMA->FIR->FFT，返回 (nframes, N) 复数频谱（自然序，已补偿 /1024 缩放）。"""
    in_buf = allocate(shape=(N,), dtype=np.uint32)
    out_buf = allocate(shape=(N,), dtype=np.uint32)
    Y = np.zeros((len(frames), N), dtype=np.complex128)
    for f in range(len(frames)):
        np.copyto(in_buf, frames[f])
        in_buf.flush()
        dma.recvchannel.transfer(out_buf)
        dma.sendchannel.transfer(in_buf)
        t0 = time.time()
        while not dma.sendchannel.idle:
            if time.time() - t0 > 10:
                raise RuntimeError('MM2S TIMEOUT at frame %d' % f)
        while not dma.recvchannel.idle:
            if time.time() - t0 > 20:
                raise RuntimeError('S2MM TIMEOUT at frame %d' % f)
        dma.sendchannel.stop()
        dma.recvchannel.stop()
        w = out_buf.astype(np.uint64)
        re = (w & 0xFFFF).astype(np.int32)
        im = ((w >> 16) & 0xFFFF).astype(np.int32)
        re[re >= 32768] -= 65536
        im[im >= 32768] -= 65536
        Y[f] = ((re + 1j * im) * 1024.0)[REV]   # 补偿缩放模式并恢复自然序
    return Y


def ola_reconstruct(Y):
    """Hann 窗 + 50% 重叠相加重建时域波形。
    Hann 窗在 50% 重叠下满足 COLA（win[k]+win[k+N/2]=1），故分子加权 win、
    分母累计 win 即可精确还原，无需再按窗能量归一化。"""
    hop = N // 2
    win = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N) / N)
    n_out = (len(Y) - 1) * hop + N
    num = np.zeros(n_out)
    den = np.zeros(n_out)
    for f in range(len(Y)):
        s = f * hop
        xr = np.fft.ifft(Y[f]).real
        num[s:s + N] += xr * win
        den[s:s + N] += win
    den[den == 0] = 1
    return num / den


def main():
    n = np.arange(SR)   # 1 秒双音信号
    x = (0.35 * 32767 * (np.sin(2 * np.pi * 300 * n / SR)
                         + np.sin(2 * np.pi * 3000 * n / SR))).astype(np.int64)

    ol = Overlay(BIT)
    dma = ol.axi_dma_0
    dma.sendchannel._align = 4
    dma.recvchannel._align = 4
    fir = MMIO(0x40000000, 65536)

    frames, hop = make_frames(x)
    write_coeffs(fir, ALLPASS)
    Y_ap = hw_spectrum(ol, dma, frames)
    write_coeffs(fir, LP)
    Y_lp = hw_spectrum(ol, dma, frames)

    x_orig = ola_reconstruct(Y_ap)[hop:hop + len(x)]   # 全通：原波，裁掉两端补零
    x_filt = ola_reconstruct(Y_lp)[hop:hop + len(x)]     # 低通：滤波后
    x_orig = np.clip(x_orig, -32768, 32767).astype('<i2')
    x_filt = np.clip(x_filt, -32768, 32767).astype('<i2')

    out = sys.stdout.buffer
    # 二进制过串口控制台会被 tty 烹调模式破坏（XON/XOFF、换行转换丢字节），
    # 因此整段数据 base64 文本化发送，PC 端解码
    payload = base64.b64encode(x_orig.tobytes() + x_filt.tobytes())
    out.write(('WAVE_BEGIN %d %d %d B64\n' % (SR, len(x_orig), len(x_filt))).encode())
    out.write(payload + b'\n')
    out.flush()
    print('WAVE_END')


if __name__ == '__main__':
    main()
