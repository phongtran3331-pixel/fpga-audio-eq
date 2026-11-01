# 一次性工具：把 pynq/wave_send.py 经串口控制台传到板卡 /home/xilinx/
# 并检查 bit 文件是否就位
import base64
import os
import sys
import time

import serial

COM = sys.argv[1] if len(sys.argv) > 1 else 'COM6'
SRC = os.path.join(os.path.dirname(__file__), '..', 'pynq', 'wave_send.py')


def drain(ser, quiet=0.4):
    time.sleep(quiet)
    data = ser.read(ser.in_waiting or 1)
    return data


def send_line(ser, line, quiet=0.3):
    ser.write(line.encode() + b'\r')
    return drain(ser, quiet)


def ensure_shell(ser):
    """无论当前是 login 提示还是已登录，都进入 xilinx 的 shell。"""
    for _ in range(10):
        tail = drain(ser, 0.6)
        if b'login:' in tail:
            send_line(ser, 'xilinx', 1.2)
        elif b'Password:' in tail:
            send_line(ser, 'xilinx', 1.2)
        elif b'$' in tail or b'#' in tail:
            return True
        else:
            ser.write(b'\r')
    # 最后确认
    out = send_line(ser, 'echo READY_$((6*7))', 0.8)
    return b'READY_42' in out


def main():
    data = open(SRC, 'rb').read()
    b64 = base64.b64encode(data).decode()
    print('待上传 wave_send.py: %d 字节 (base64 %d 字符)' % (len(data), len(b64)))

    ser = serial.Serial(COM, 460800, timeout=1)   # 上次运行已把板端 ttyPS0 提速到 460800
    print('等待 shell ...')
    if not ensure_shell(ser):
        print('失败: 无法进入板端 shell')
        sys.exit(1)
    print('已进入 shell')

    out = send_line(ser, 'ls -la /home/xilinx/audio_fir_fft_v6.bit /home/xilinx/audio_fir_fft_v6.hwh 2>&1 | tail -3', 1.0)
    print('[板端]', out.decode('utf-8', 'replace').strip())
    if b'No such' in out or b'cannot access' in out:
        print('!! 警告: 板端缺 audio_fir_fft_v6.bit/.hwh，wave_send.py 将无法加载 Overlay')

    send_line(ser, 'rm -f /home/xilinx/wave_send.py.b64', 0.4)
    CH = 400
    for i in range(0, len(b64), CH):
        chunk = b64[i:i + CH]
        out = send_line(ser, "echo '%s' >> /home/xilinx/wave_send.py.b64" % chunk, 0.25)
        if b'>' in out and b'$' not in out:
            pass
        if (i // CH) % 5 == 0:
            print('  上传 %d/%d' % (i, len(b64)))
    out = send_line(ser, 'base64 -d /home/xilinx/wave_send.py.b64 > /home/xilinx/wave_send.py && wc -c /home/xilinx/wave_send.py', 1.0)
    print('[板端]', out.decode('utf-8', 'replace').strip())
    out = send_line(ser, "python3 -c \"import ast; ast.parse(open('/home/xilinx/wave_send.py').read()); print('SYNTAX_OK')\"", 1.5)
    if b'SYNTAX_OK' in out:
        print('上传并校验成功')
    else:
        print('!! 语法校验未通过: %r' % out[-120:])
        sys.exit(1)
    ser.close()


if __name__ == '__main__':
    main()
