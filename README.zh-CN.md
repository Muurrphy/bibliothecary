# Robot LipSync 中文说明

**面向机器人和受限显示设备的实时、肌肉感语音口型。**

Robot LipSync 在 TTS 还在流式生成声音时，就把同一条音频时间线上的字符对齐转换成连续嘴部动作。它不是“声音越大嘴张得越大”的音量动画，也不是一套只能给某块 OLED 使用的位图。

项目只讲一个容易理解的承诺：

> 让机器人尽早开口，同时让嘴型在同一物理播放时钟上准确、自然地开始运动。

“约两秒开口”是参考硬件上的性能目标和 benchmark，不是第二个产品，也不是对所有网络和模型的保证。

## 无密钥体验

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
robot-lipsync demo
```

打开 `build/demo.html` 即可看到浏览器动画，同时会生成显示无关的 `build/demo.timeline.json`。

## 英语、普通话和西班牙语

语言标签现在会选择不同的“文字→音素→可视嘴型”管线，不再把所有拉丁字母都当英语，也不再把每个汉字压成同一个中性嘴型。

```bash
# 西班牙语：核心安装即可使用
robot-lipsync demo --text "Hola, mundo." --language es \
  --output build/spanish.html

# 普通话：安装带词组消歧的拼音支持
pip install -e ".[mandarin]"
robot-lipsync demo --text "你好，世界。" --language zh-CN \
  --output build/mandarin.html
```

西语使用独立的五元音目标，并处理 `b/v` 同属双唇音、`h` 不发音、`ñ/ll/rr`、`que/gui` 等规则；默认 `es` 使用 seseo，`es-ES` 保留卡斯蒂利亚西语的齿音区别。普通话按声母和韵母拆分，保留 `u/ü`、卷舌/舌面/齿音类别、复韵母运动路径与声调元数据；流式输入会保留两个汉字的右侧上下文，以减少多音字读音在发送到硬件后被改写。

论文依据、方言选择和仍需真人/实体机器人验证的限制见 [多语言发音说明](docs/multilingual.md)。

如需接入 ElevenLabs，可安装 `.[elevenlabs]` 并运行 `examples/elevenlabs_http.py`；普通话同时安装 `.[elevenlabs,mandarin]`。设置 `ELEVENLABS_LANGUAGE=es` 或 `zh-CN` 后，字符时间戳会进入对应语言管线。该示例从同一条 HTTP 响应同时取得音频与字符时间戳，不会为了计算口型把已生成的声音再上传给第二个模型；密钥只从环境变量读取。

仓库现已包含可复现编译的 ESP32-C3 + 128×64 OLED 通用固件，以及“20 个固定英文场景 × 5 次”的 100 轮 benchmark runner。固件直接消费八个连续肌肉通道，不依赖 Lilyput 的项目位图；benchmark 使用长期存活的适配器连接、逐轮落盘、断点续跑，并分别报告物理声音、第一帧嘴型、失败和欠载。仓库内模拟器只用于验证工具，所有记录明确标记 `simulated=true`，不能当作真实性能数据。中文和西语目前已有确定性测试与示例，但还没有可发布的真人/实体机器人感知基准。

## 核心差异

- 输出下颌、唇缝、嘴角宽度、圆唇、闭唇力度、前突、下唇内收和不对称等连续通道；
- 明确保留 M/B/P 闭唇、F/V 唇齿、O/U/W 圆唇和双元音路径；
- 纵向大开口与横向极限拉伸互相拮抗；
- 增量输入只发布已经稳定的词和动作，不改写已传给硬件的时间线；
- 同一 IR 可以驱动网页、OLED、虚拟角色和未来的硅胶机械嘴；
- 延迟从用户停嘴一直记录到实体扬声器起播和第一帧嘴部动作。

## 诚实的延迟表述

Lilyput 原型的大多数实测轮次约在 1.9–2.7 秒开始实体播放，同时记录到一次 4.573 秒长尾。因此目前准确的表达是“near-two-second reference response”，而不是“永远两秒内”或“全球最快”。仓库提供分阶段 trace、P50/P95/P99 和欠载指标，使优化能够复现和比较。

完整架构、研究边界和发布条件请阅读英文 [README](README.md) 及 `docs/`。
