# PC 端：经串口线接收板端 wave_send.py 发来的两路波形，可交互显示与播放
# 用法（电脑上）：
#   pip install pyserial matplotlib numpy sounddevice   # sounddevice 可选，用于播放
#   python wave_view.py --com COM4
import argparse
import os
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
    """协议: WAVE_BEGIN <sr> <n1> <n2> B64 \\n | base64(n1*2 + n2*2 字节 int16 LE) \\n | WAVE_END
    （数据走 base64 文本，避免 tty 烹调模式破坏二进制）"""
    import base64
    while True:
        line = read_line(ser)
        if line.startswith(MAGIC_BEGIN):
            break
        print('[板端]', line.decode('utf-8', 'replace'))
    parts = line.split()
    _, sr, n1, n2 = parts[:4]
    sr, n1, n2 = int(sr), int(n1), int(n2)
    b64 = read_line(ser, timeout=120)
    raw = base64.b64decode(b64)
    expect = (n1 + n2) * 2
    if len(raw) != expect:
        raise ValueError('base64 解码长度异常: %d != %d' % (len(raw), expect))
    alld = np.frombuffer(raw, dtype='<i2')
    d_orig, d_filt = alld[:n1], alld[n1:]
    end = read_line(ser, timeout=30)
    if MAGIC_END not in end:
        print('[warn] 结束标记异常:', end)
    return sr, d_orig.astype(float), d_filt.astype(float)


def clean_shell(ser, tries=12):
    """把板端 shell 清回干净的提示符：Ctrl-C 中断残留进程 + 回车，
    直到看到 xilinx@pynq 提示符且再无新数据（上次中断留下的二进制残数据
    会在这一步被全部倒出来丢掉）。"""
    for i in range(tries):
        ser.write(b'\x03\r')
        time.sleep(0.6)
        junk = ser.read(ser.in_waiting or 1)
        if b'xilinx@pynq' in junk and not ser.in_waiting:
            # 再多等一拍确认没有后续残数据
            time.sleep(0.4)
            tail = ser.read(ser.in_waiting or 1)
            if b'xilinx@pynq' in tail or tail == b'':
                return True
    return False


def run(com, save_only=False):
    print('1/4 打开串口 %s @115200' % com)
    ser = serial.Serial(com, 115200, timeout=1)
    time.sleep(0.3)
    ser.reset_input_buffer()
    print('  清理板端残留状态 ...')
    if not clean_shell(ser):
        print('  [warn] shell 清理未完全确认，继续执行')

    print('2/4 提升板端波特率到 460800 ...')
    ser.write(b'stty -F /dev/ttyPS0 460800\r')
    time.sleep(0.8)
    ser.close()
    ser = serial.Serial(com, 460800, timeout=1)
    time.sleep(0.2)
    ser.reset_input_buffer()
    clean_shell(ser)   # 提速后再确认一次，丢光切换波特率时涌出的残数据

    print('3/4 启动板端 wave_send.py（sudo -E 保留环境，密码自动发送 xilinx）...')
    ser.reset_input_buffer()
    ser.write(b'sudo -E python3 /home/xilinx/wave_send.py\r')
    time.sleep(1.0)
    ser.write(b'xilinx\r')

    print('4/4 接收波形数据（约 4 秒）...')
    sr, d_orig, d_filt = parse_wave_stream(ser)
    ser.close()
    print('接收完成: %d 点 @ %d Hz, 滤波后 %d 点' % (len(d_orig), sr, len(d_filt)))
    # 原始数据落盘，之后不用重连板卡也能重画
    npz = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wave_data.npz')
    np.savez(npz, sr=sr, orig=d_orig, filt=d_filt)
    print('原始数据已保存: %s' % npz)
    show(sr, d_orig, d_filt, save_only=save_only)


def show(sr, d_orig, d_filt, save_only=False):
    import matplotlib.pyplot as plt
    from matplotlib.widgets import Button

    # 中文字体：托管 Python 默认 DejaVu Sans 不含 CJK，会显示成方框
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Noto Sans SC']
    plt.rcParams['axes.unicode_minus'] = False

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

    # 无论是否有图形界面，先落盘一张 PNG，保证一定有图可看
    png = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'wave_compare_%s.png' % time.strftime('%H%M%S'))
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    fig.savefig(png, dpi=130)
    print('波形图已保存: %s' % png)

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
    if save_only:
        plt.close(fig)
    else:
        plt.show()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--com', default='COM6', help='串口号，默认 COM6')
    ap.add_argument('--save-only', action='store_true',
                    help='只保存 PNG 不弹窗（适合无人值守/录素材）')
    args = ap.parse_args()
    try:
        run(args.com, save_only=args.save_only)
    except Exception as e:
        print('失败:', e)
        sys.exit(1)
