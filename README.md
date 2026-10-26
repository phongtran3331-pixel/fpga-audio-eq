# 基于 PYNQ 的实时音频处理系统（Zynq-7020）

> FPGA 创新设计赛道（AMD）参赛工程 · 实时音频均衡 + 频谱分析

## 项目简介

本工程基于 AMD/Xilinx Zynq-7020 SoC（PYNQ-Z2 开发板），实现了一套"采集 → 均衡滤波 → 频谱分析 → 可视化"完整实时音频处理系统：

- **PL 端（硬件）**：64 阶复数 FIR 均衡器（Vitis HLS 综合，128 路并行 MAC，Q15 定点）+ 1024 点 XFFT 处理器（scaled 模式）+ AXI DMA 数据搬运，构成纯硬件流水线；
- **PS 端（软件）**：PYNQ v2.7 框架，Jupyter Notebook 交互，负责系数在线配置、DMA 调度与频谱可视化；
- **实时性**：音频经板载 ADAU1761 编解码器采集回放，FIR 系数支持运行期在线改写（低通/高通/全通等模式秒级切换）。

## 实测指标

| 指标 | 实测值 |
|---|---|
| 通带衰减（bin 20） | -0.4 dB |
| 阻带抑制（bin 200，64 阶低通） | -54.1 dB |
| 频谱镜像泄漏 | -58 dB |
| 硬件通路处理时延 | 2.1 ms/帧（吞吐约 0.49 Msps，PS 零占用） |
| 逻辑资源占用 | LUT 14.35% / FF 13.60% / DSP48 140 / BRAM 3.57% |
| 时序 | WNS 6.487 ns @ 100 MHz，零违例 |

## 目录结构

```
├── hls/                  # Vitis HLS 工程源码（FIR 均衡器）
│   ├── fir_eq.cpp        #   顶层：64 阶复数 FIR，AXI-Stream + AXI-Lite 系数
│   └── fir_eq_tb.cpp     #   C 仿真测试台
├── vivado/
│   └── design_1.bd       # Block Design 源文件（JSON）
│   └── ip/               # 各 IP 配置（.xci，含 XFFT 0x0555 配置常量）
├── bitstream/            # 预生成比特流（直接可用）
│   ├── audio_fir_fft_v6.bit
│   └── audio_fir_fft_v6.hwh
├── pynq/                 # 板端 Python 脚本（PYNQ）
│   ├── fft_check.py      #   FFT 正确性验证（单音/复音双判据）
│   ├── filter_demo.py    #   双音滤波演示（全通 vs 低通，输出频谱数据）
│   ├── accel_test.py     #   硬件 vs 软件加速比实测
│   ├── demo_real.py      #   板载音频合成与回放演示
│   └── singletone.py / zerotest.py / sim_models.py
├── host_tools/           # PC 端串口辅助脚本（上传/控制台，460800bps）
└── docs/                 # 实测图表（频谱对比 / FIR 响应 / 波形）
```

## 快速开始（复现步骤）

**环境**：PYNQ-Z2（Zynq-7020），PYNQ v2.7 镜像，Vivado/Vitis HLS 2020.2（重建工程时需要）。

1. **上电**：SD 卡烧录 PYNQ v2.7 镜像，插入板卡，通电；
2. **传文件**：`host_tools/uart_send.ps1` 串口上传（或网线直连 Jupyter 上传）本仓库 `bitstream/` 与 `pynq/` 至 `/home/xilinx/`；
3. **加载与自检**：
   ```bash
   sudo -E python3 /home/xilinx/fft_check.py A   # 期望：单峰 @ bin100，镜像 -58dB → PASS
   sudo -E python3 /home/xilinx/fft_check.py B     # 期望：100/924 对称双峰 → PASS
   ```
4. **滤波演示**：`sudo -E python3 /home/xilinx/filter_demo.py ap`（全通）→ 改 `lp`（低通），对比两次 SPEC 输出；
5. **加速比**：`sudo -E python3 /home/xilinx/accel_test.py`。

**重建工程**：Vivado 2020.2 新建工程 → 导入 `vivado/design_1.bd` 与 IP 配置 → HLS 端用 `hls/fir_eq.cpp` 重新综合生成 IP → 加入 BD（DMA→FIR→FFT→DMA，FFT config 接 16 位常量 0x0555）→ Generate Bitstream。

## LLM 辅助设计声明

本工程全程引入大语言模型辅助开发（约 30 天协作周期），包括但不限于：
- 概念教学与方案设计（PL/PS 架构、AXI 协议、DSP 原理图解）；
- HLS C++ 代码与 PYNQ 驱动代码的编写与审查；
- **关键调试**：系统出现确定性杂散时，由"确定性杂散 → 冲激正常 → 零输入零输出 → PC 端四种数学模型仿真比对"的证据链定位出 XFFT 配置通道（s_axis_config_tdata）悬空这一根连线问题（悬空即 IFFT + 零缩放 → 溢出回绕），修复后验证通过——该案例完整记录了"测量—假设—验证"的硬件调试方法论；
- 报告与演示视频脚本的结构化撰写。

## 许可

MIT License（见 LICENSE）。工程可自由复现、修改与引用。
