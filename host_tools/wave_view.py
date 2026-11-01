# PC 端：MP3 -> 串口上传板卡做硬件 FIR+FFT 处理 -> 接收两路波形
#       10 ms 滑动视窗动态显示，播放时窗口跟随播放头
# 用法（电脑上）：
#   pip install pyserial matplotlib numpy miniaudio sounddevice   # sounddevice 可选
#   python wave_view.py --com COM6 --mp3 某首歌.mp3 [--seconds 4] [--start 10]
# 本机实测示例（周杰伦《菊花台》）：
#   python wave_view.py --com COM6 --mp3 "D:\KimiData\kimi\workspace\ruixinpage\app\music\《菊花台》- 周杰伦.mp3" --start 10 --seconds 3
# 不带 --mp3 时退回板端合成双音模式（无需上传）
import argparse
import base64
import os
import struct
import sys
import time

import numpy as np
import serial

MAGIC_BEGIN = b'WAVE_BEGIN '
MAGIC_END = b'WAVE_END'
SR = 48000
WIN = 0.01          # 显示窗口 10 ms


class Rx:
    """带缓冲的行读取器：read(1) 逐字节在 921600 波特下会丢字节，
    这里按 in_waiting 整块读取；跨行的余量留给下一行。"""

    def __init__(self, ser):
        self.ser = ser
        self.buf = b''

    def read_line(self, timeout=60):
        t0 = time.time()
        while b'\n' not in self.buf:
            if time.time() - t0 > timeout:
                raise TimeoutError('等待板端数据超时，最后收到: %r' % self.buf[-80:])
            b = self.ser.read(max(1, self.ser.in_waiting))
            if b:
                self.buf += b
        line, self.buf = self.buf.split(b'\n', 1)
        return line.strip()


def read_line(ser, timeout=60):   # 兼容旧调用
    return Rx(ser).read_line(timeout)


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


def clean_shell(ser, tries=12):
    """把板端 shell 清回干净提示符（Ctrl-C 中断残留进程 + 回车）。"""
    for i in range(tries):
        ser.write(b'\x03\r')
        time.sleep(0.6)
        junk = ser.read(ser.in_waiting or 1)
        if b'xilinx@pynq' in junk and not ser.in_waiting:
            time.sleep(0.4)
            tail = ser.read(ser.in_waiting or 1)
            if b'xilinx@pynp' in tail or tail == b'':
                return True
    return False


def decode_mp3(path, seconds, start):
    """MP3 -> 48kHz 单声道 int16 PCM，截取 [start, start+seconds] 秒。"""
    import miniaudio
    try:
        f = miniaudio.decode_file(path, output_format=miniaudio.SampleFormat.SIGNED16,
                                  nchannels=1, sample_rate=SR)
    except miniaudio.DecodeError:
        # miniaudio 在 Windows 下打不开含非 ASCII 字符的路径，
        # 复制到纯英文临时文件再解码
        import shutil
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), 'pynq_wave_input.mp3')
        shutil.copyfile(path, tmp)
        f = miniaudio.decode_file(tmp, output_format=miniaudio.SampleFormat.SIGNED16,
                                  nchannels=1, sample_rate=SR)
    pcm = np.frombuffer(f.samples, dtype='<i2')
    i0 = int(start * SR)
    i1 = min(len(pcm), i0 + int(seconds * SR))
    clip = pcm[i0:i1]
    print('MP3 解码: %s | %d 点 -> 截取 %.2f~%.2f s, %d 点 (%.2f s)'
          % (os.path.basename(path), len(pcm) / SR, start, start + len(clip) / SR,
             len(clip), len(clip) / SR))
    return clip


def upload_pcm(ser, pcm):
    """经串口控制台把 int16 PCM 以 base64 文本传到板端 /tmp/in.pcm。
    借用 cat 会话：先关回显，cat 收文本行，Ctrl-D 结束，再开回显。"""
    b64 = base64.b64encode(pcm.astype('<i2').tobytes()).decode()
    print('  上传 PCM: %d 字节 (base64 %d 字符) ...' % (len(pcm) * 2, len(b64)))

    def sh(cmd, wait=0.4):
        ser.write(cmd + b'\r')
        time.sleep(wait)
        return ser.read(ser.in_waiting or 1)

    sh(b'pkill -f "cat > /tmp/in.b64" 2>/dev/null; echo UP_READY', 0.6)
    sh(b'stty -echo', 0.4)
    sh(b'rm -f /tmp/in.b64 /tmp/in.pcm', 0.3)
    ser.write(b'cat > /tmp/in.b64\r')
    time.sleep(0.8)
    ser.read(ser.in_waiting or 1)
    CH = 512
    lines = (len(b64) + CH - 1) // CH
    t0 = time.time()
    for k, i in enumerate(range(0, len(b64), CH)):
        ser.write(b64[i:i + CH].encode() + b'\n')
        time.sleep(0.02)          # 限速，防止 tty 输入缓冲溢出
        if (k + 1) % 100 == 0:
            el = time.time() - t0
            print('    上传 %d/%d 行 (%.0f%%), %.0f s' % (k + 1, lines,
                  (k + 1) / lines * 100, el))
    # 等 cat 把内核缓冲的最后几行全部写盘（连续 1 秒无新数据视为消化完）
    idle = 0
    while idle < 10:
        time.sleep(0.1)
        b = ser.read(ser.in_waiting or 1)
        idle = 0 if b else idle + 1
    ser.write(b'\x04')            # Ctrl-D 结束 cat（当前在行首）
    time.sleep(1.0)
    ser.read(ser.in_waiting or 1)
    sh(b'stty echo', 0.3)

    # 确认回到 shell 提示符（最多等 10 秒），再校验
    ok = False
    for _ in range(20):
        out = sh(b'echo UP_DONE', 0.5)
        if b'UP_DONE' in out and b'xilinx@pynq' in out:
            ok = True
            break
    if not ok:
        ser.write(b'\x03\r')      # 兜底：Ctrl-C 杀掉可能残留的 cat
        time.sleep(1.0)
        ser.read(ser.in_waiting or 1)
        sh(b'stty echo', 0.3)
        raise RuntimeError('cat 会话未能正常结束，板端串口状态未知')

    expect = str(len(pcm) * 2)
    out = b''
    for _ in range(6):
        out += sh(b'base64 -d /tmp/in.b64 > /tmp/in.pcm && wc -c < /tmp/in.pcm', 2.0)
        if expect.encode() in out:
            break
    if expect.encode() not in out:
        raise RuntimeError('PCM 上传校验失败: %r' % out[-120:])
    print('  上传校验通过: %s 字节' % expect)


def parse_wave_stream(ser):
    """协议: WAVE_BEGIN <sr> <n1> <n2> B64 \\n | base64 数据行 | WAVE_END"""
    rx = Rx(ser)
    while True:
        # 板端处理耗时与片段长度成正比（约 20 s/秒音频），这里给足 15 分钟
        line = rx.read_line(timeout=900)
        if line.startswith(MAGIC_BEGIN):
            break
        print('[板端]', line.decode('utf-8', 'replace'))
    parts = line.split()
    _, sr, n1, n2 = parts[:4]
    sr, n1, n2 = int(sr), int(n1), int(n2)
    b64 = rx.read_line(timeout=300)
    raw = base64.b64decode(b64)
    if len(raw) != (n1 + n2) * 2:
        raise ValueError('base64 解码长度异常: %d != %d' % (len(raw), (n1 + n2) * 2))
    alld = np.frombuffer(raw, dtype='<i2')
    end = read_line(ser, timeout=30)
    if MAGIC_END not in end:
        print('[warn] 结束标记异常:', end[:60])
    return sr, alld[:n1].astype(float), alld[n1:].astype(float)


def run(com, mp3=None, seconds=4.0, start=0.0, baud=921600, save_only=False):
    pcm = None
    if mp3:
        pcm = decode_mp3(mp3, seconds, start)

    print('1/5 打开串口 %s @115200' % com)
    ser = serial.Serial(com, 115200, timeout=1)
    time.sleep(0.3)
    ser.reset_input_buffer()
    print('  清理板端残留状态 ...')
    if not clean_shell(ser):
        print('  [warn] shell 清理未完全确认，继续执行')

    print('2/5 提升板端波特率到 %d ...' % baud)
    ser.write(b'stty -F /dev/ttyPS0 %d\r' % baud)
    time.sleep(0.8)
    ser.read(ser.in_waiting or 1)
    ser.close()
    ser = serial.Serial(com, baud, timeout=1)
    time.sleep(0.2)
    ser.reset_input_buffer()
    clean_shell(ser)

    if pcm is not None:
        print('3/5 上传 MP3 片段到板卡 ...')
        upload_pcm(ser, pcm)
        cmd = b'sudo -E python3 /home/xilinx/wave_send.py /tmp/in.pcm'
    else:
        print('3/5 启动板端 wave_send.py（板端合成双音）...')
        cmd = b'sudo -E python3 /home/xilinx/wave_send.py'
    ser.reset_input_buffer()
    ser.write(cmd + b'\r')
    time.sleep(1.0)
    ser.write(b'xilinx\r')

    print('4/5 接收波形数据 ...')
    sr, d_orig, d_filt = parse_wave_stream(ser)

    print('5/5 收尾: 板端串口恢复 115200')
    ser.write(b'stty -F /dev/ttyPS0 115200\r')
    time.sleep(0.5)
    ser.read(ser.in_waiting or 1)
    ser.close()

    print('接收完成: %d 点 @ %d Hz (%.2f s)' % (len(d_orig), sr, len(d_orig) / sr))
    tag = os.path.splitext(os.path.basename(mp3))[0] if mp3 else 'twotone'
    npz = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wave_data_%s.npz' % tag)
    np.savez(npz, sr=sr, orig=d_orig, filt=d_filt)
    print('原始数据已保存: %s' % npz)
    show(sr, d_orig, d_filt, tag, save_only=save_only)


def show(sr, d_orig, d_filt, tag, save_only=False):
    import matplotlib.pyplot as plt
    from matplotlib.widgets import Button

    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Noto Sans SC']
    plt.rcParams['axes.unicode_minus'] = False

    dur = len(d_orig) / sr
    t_full = np.arange(len(d_orig)) / sr

    fig = plt.figure(figsize=(11, 7))
    fig.canvas.manager.set_window_title('PYNQ 原波 vs 滤波波形（10 ms 视窗）')
    ax1 = fig.add_axes([0.07, 0.42, 0.86, 0.50])
    ax2 = fig.add_axes([0.07, 0.13, 0.86, 0.24], sharex=ax1)
    aov = fig.add_axes([0.07, 0.015, 0.62, 0.085])
    aov.set_facecolor('#f4f4f4')

    ax1.plot(t_full, d_orig, lw=0.7, color='#0b7a5c')
    ax1.set_ylabel('原波（全通）')
    ax1.set_title('视窗 10 ms —— 点上方缩略图可跳转，播放时窗口跟随', fontsize=10)
    ax1.grid(alpha=0.3)
    plt.setp(ax1.get_xticklabels(), visible=False)

    ax2.plot(t_full, d_filt, lw=0.7, color='#b3541e')
    ax2.set_ylabel('滤波（低通）')
    ax2.set_xlabel('时间 (s)')
    ax2.grid(alpha=0.3)
    ax2.set_xlim(0, WIN)

    # 缩略图: 两路波形叠加 + 当前窗口位置框
    aov.set_position([0.07, 0.015, 0.50, 0.085])
    aov.plot(t_full, d_orig, lw=0.4, color='#0b7a5c', alpha=0.65)
    aov.plot(t_full, d_filt, lw=0.4, color='#b3541e', alpha=0.65)
    aov.set_xlim(0, dur)
    aov.set_yticks([])
    aov.set_xticks(np.linspace(0, dur, 6))
    aov.set_xticklabels(['%.2f' % v for v in np.linspace(0, dur, 6)], fontsize=7)
    rect = plt.Rectangle((0, aov.get_ylim()[0]), WIN, 1, color='#2255aa', alpha=0.25)
    aov.add_patch(rect)

    state = {'t0': 0.0, 'playing': None, 'data': None, 'pos': 0}

    def set_window(t0):
        t0 = max(0.0, min(t0, dur - WIN))
        state['t0'] = t0
        ax2.set_xlim(t0, t0 + WIN)
        ax1.set_xlim(t0, t0 + WIN)
        rect.set_xy((t0, rect.get_y()))
        fig.canvas.draw_idle()

    # ---- 播放（sounddevice 可选） ----
    sd = None
    try:
        import sounddevice as sd
    except ImportError:
        print('[提示] 未安装 sounddevice，播放按钮不可用（pip install sounddevice）')

    stream = [None]

    def stop(event=None):
        if stream[0] is not None:
            try:
                stream[0].stop()
                stream[0].close()
            except Exception:
                pass
            stream[0] = None
        state['playing'] = None

    def play(which, offset=0.0):
        if sd is None:
            return
        stop()
        d = (d_orig if which == 'orig' else d_filt)
        d = d / max(1e-9, np.abs(d).max()) * 0.8
        state['data'] = d
        state['pos'] = int(offset * sr)
        state['playing'] = which

        def cb(out, frames, time_info, status):
            i = state['pos']
            chunk = state['data'][i:i + frames]
            if len(chunk) < frames:
                out[:len(chunk), 0] = chunk
                out[len(chunk):, 0] = 0
                state['pos'] = len(state['data'])
                raise sd.CallbackStop()
            out[:, 0] = chunk
            state['pos'] = i + frames

        stream[0] = sd.OutputStream(samplerate=sr, channels=1, dtype='float32',
                                      blocksize=2048, callback=cb)
        stream[0].start()

    def seek(event):
        if event.inaxes is not aov:
            return
        t = event.xdata
        if t is None:
            return
        set_window(t - 0.002 * WIN)
        if state['playing'] is not None:
            play(state['playing'], offset=max(0.0, t - WIN * 0.2))
        else:
            state['pos'] = int(t * sr)
    fig.canvas.mpl_connect('button_press_event', seek)

    def tick():
        if state['playing'] is not None and stream[0] is not None:
            t = state['pos'] / sr
            set_window(t - WIN * 0.2)
            if state['pos'] >= len(state['data']):
                stop()
        fig.canvas.draw_idle()

    def reset(event=None):
        """停止播放，播放头与视窗都回到 0 s"""
        stop()
        state['pos'] = 0
        set_window(0.0)

    axb0 = fig.add_axes([0.60, 0.03, 0.075, 0.045])
    axb1 = fig.add_axes([0.685, 0.03, 0.085, 0.045])
    axb2 = fig.add_axes([0.78, 0.03, 0.085, 0.045])
    axb3 = fig.add_axes([0.875, 0.03, 0.095, 0.045])
    b0 = Button(axb0, '复位')
    b1 = Button(axb1, '播放原声')
    b2 = Button(axb2, '播放滤波')
    b3 = Button(axb3, '停止')
    b0.on_clicked(reset)
    b1.on_clicked(lambda e: play('orig', offset=state['pos'] / sr))
    b2.on_clicked(lambda e: play('filt', offset=state['pos'] / sr))
    b3.on_clicked(lambda e: stop())

    set_window(0.0)

    png = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'wave_%s_%s.png' % (tag, time.strftime('%H%M%S')))
    fig.savefig(png, dpi=130)
    print('波形图已保存: %s' % png)

    if save_only:
        plt.close(fig)
        return

    timer = fig.canvas.new_timer(interval=50)
    timer.add_callback(tick)
    timer.start()
    plt.show()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--com', default='COM6', help='串口号，默认 COM6')
    ap.add_argument('--mp3', default=r'D:\KimiData\kimi\workspace\ruixinpage\app\music\《菊花台》- 周杰伦.mp3',
                    help='MP3 文件路径；不传则退回板端合成双音')
    ap.add_argument('--seconds', type=float, default=5.0, help='截取长度(秒)，默认 10')
    ap.add_argument('--start', type=float, default=10.0, help='截取起点(秒)，默认 10')
    ap.add_argument('--baud', type=int, default=921600, help='传输波特率，默认 921600')
    ap.add_argument('--save-only', action='store_true',
                    help='只保存 PNG 不弹窗（适合无人值守/录素材）')
    args = ap.parse_args()
    try:
        run(args.com, mp3=args.mp3, seconds=args.seconds, start=args.start,
            baud=args.baud, save_only=args.save_only)
    except Exception as e:
        print('失败:', e)
        sys.exit(1)
