# PC 端：经串口线接收板端 wave_send.py 发来的两路波形，可交互显示与播放
# 用法（电脑上）：
#   pip install pyserial matplotlib numpy sounddevice   # sounddevice 可选，用于播放
#   python wave_view.py --com COM8
import argparse
import struct
import sys
import time

import numpy as np
import serial

MAGIC_BEGIN = b'WAVE_BEGIN '
MAGIC_END = b'WAVE_END'


def read_line(ser, timeout=60):
    """读取一行 ASCII（协议头 / 结束标记），超时抛异常。"""
    buf = b''
    t0 = time.time()
    while not buf.endswith(b'\n'):
        if time.time() - t0 > timeout:
            raise TimeoutError('等待板端数据超时，最后收到: %r' % buf[-80:])
        b = ser.read(1)
        if b:
            buf += b
    return buf.strip()


def read_exact(ser, n, timeout=120):
    buf = b''
    t0 = time.time()
    while len(buf) < n:
        if time.time() - t0 > timeout:
            raise TimeoutError('波形数据不完整: %d/%d 字节' % (len(buf), n))
        chunk = ser.read(n - len(buf))
        if chunk:
            buf += chunk
    return buf


def parse_wave_stream(ser):
    """协议: WAVE_BEGIN <sr> <n1> <n2> \\n | n1*2 字节原波 int16 LE | n2*2 字节滤波 int16 LE | WAVE_END"""
    while True:
        line = read_line(ser)
        if line.startswith(MAGIC_BEGIN):
            break
        print('[板端]', line.decode('utf-8', 'replace'))
    _, sr, n1, n2 = line.split()
    sr, n1, n2 = int(sr), int(n1), int(n2)
    d_orig = np.frombuffer(read_exact(ser, n1 * 2), dtype='<i2')
    d_filt = np.frombuffer(read_exact(ser, n2 * 2), dtype='<i2')
    end = read_line(ser, timeout=30)
    if MAGIC_END not in end:
        print('[warn] 结束标记异常:', end)
    return sr, d_orig.astype(float), d_filt.astype(float)


def run(com):
    print('1/4 打开串口 %s @115200' % com)
    ser = serial.Serial(com, 115200, timeout=1)
    time.sleep(0.3)

    print('2/4 提升板端波特率到 460800 ...')
    ser.write(b'stty -F /dev/ttyPS0 460800\r')
    time.sleep(0.8)
    ser.close()
    ser = serial.Serial(com, 460800, timeout=1)
    time.sleep(0.2)

    print('3/4 启动板端 wave_send.py（sudo 密码自动发送 xilinx）...')
    ser.reset_input_buffer()
    ser.write(b'sudo python3 /home/xilinx/wave_send.py\r')
    time.sleep(1.5)
    ser.write(b'xilinx\r')

    print('4/4 接收波形数据（约 4 秒）...')
    sr, d_orig, d_filt = parse_wave_stream(ser)
    ser.close()
    print('接收完成: %d 点 @ %d Hz, 滤波后 %d 点' % (len(d_orig), sr, len(d_filt)))
    show(sr, d_orig, d_filt)


def show(sr, d_orig, d_filt):
    import matplotlib.pyplot as plt
    from matplotlib.widgets import Button

    t = np.arange(len(d_orig)) / sr
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    fig.canvas.manager.set_window_title('PYNQ 原波 vs 滤波波形')
    ax1.plot(t, d_orig, lw=0.7, color='#0b7a5c')
    ax1.set_title('原波（全通系数）')
    ax1.set_ylabel('幅度')
    ax1.grid(alpha=0.3)
    ax2.plot(t[:len(d_filt)], d_filt, lw=0.7, color='#b3541e')
    ax2.set_title('滤波波形（低通系数，3000 Hz 分量被抑制）')
    ax2.set_xlabel('时间 (s)')
    ax2.set_ylabel('幅度')
    ax2.grid(alpha=0.3)

    sd = None
    try:
        import sounddevice as sd
    except ImportError:
        print('[提示] 未安装 sounddevice，播放按钮不可用（pip install sounddevice）')

    def play(which):
        if sd is None:
            return
        sd.stop()
        d = (d_orig if which == 'orig' else d_filt)
        d = d / max(1e-9, np.abs(d).max()) * 0.8
        sd.play(d, sr)

    def stop(event):
        if sd is not None:
            sd.stop()

    axb1 = fig.add_axes([0.72, 0.01, 0.08, 0.05])
    axb2 = fig.add_axes([0.81, 0.01, 0.08, 0.05])
    axb3 = fig.add_axes([0.90, 0.01, 0.07, 0.05])
    b1 = Button(axb1, '播放原声')
    b2 = Button(axb2, '播放滤波')
    b3 = Button(axb3, '停止')
    b1.on_clicked(lambda e: play('orig'))
    b2.on_clicked(lambda e: play('filt'))
    b3.on_clicked(stop)
    plt.tight_layout(rect=[0, 0.06, 1, 1])
    plt.show()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--com', default='COM8', help='串口号，默认 COM8')
    args = ap.parse_args()
    try:
        run(args.com)
    except Exception as e:
        print('失败:', e)
        sys.exit(1)
