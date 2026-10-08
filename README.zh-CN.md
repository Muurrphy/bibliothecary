# Margin（页边）· 多设备伴读

我想继续用旧 Kindle 读文章，同时能直接开口提问，不用每次切回电脑。Kindle 没有麦克风也没关系：手机或 iPad 负责听问题、放声音，屏幕上显示一张跟着语音变化的数码嘴巴。

现在把 Kindle 伴读和多语言口型合在同一个项目里。Kindle 打开轻量阅读网页，电脑负责讲稿和 AI 调用。**Kindle 不用越狱，也不用安装应用。**

[English](README.md) · [配置说明](docs/configuration.md) · [已知问题](docs/known-issues.md)

> **当前是 v0.2.0 实验版本。** 手机收音仍不稳定，有时能听到，有时会漏掉问题或没有回复；声音和嘴型也可能需要刷新页面恢复。已经拍过演示，但日常免手操作的稳定性还没有达到可靠可用的程度。本次合并保留当前状态，没有继续修改收音功能。

## 设备分工

| 设备 | 负责什么 |
|---|---|
| Kindle | 显示文章、划线、圈词、批注和简单图示。 |
| 手机或 iPad | 用这台设备自己的麦克风收音，用自己的扬声器播放，屏幕显示嘴型。 |
| 电脑 | 运行本地服务，调用模型，准备讲解、声音和时间轴。 |
| 其他手机或平板 | 可以只显示嘴型，不额外开启麦克风。 |

设备需要在同一个局域网里。Kindle 只负责显示，不录音。这个项目不需要机械臂或机器人头。

## 安装和试用

需要 Python 3.11 或更新版本。macOS / Linux：

```bash
git clone https://github.com/Muurrphy/margin.git
cd margin
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

margin check examples/village.lesson.json
margin serve examples/village.lesson.json --voice silent --paused
```

Kindle 打开终端打印的 `http://<电脑地址>:8765/`；电脑打开 `http://localhost:8765/remote`，可以播放、暂停和用文字提问。没有 API key 时可以试用示例里写好的问题。

多语言口型已经包含在同一次安装中，不需要再下载另一个项目。下面是离线视觉预览，时间戳是合成的，不代表真实语音同步：

```bash
robot-lipsync demo --text "你好，世界。" --language zh-CN --output build/mouth.html
```

用浏览器打开 `build/mouth.html`。

## 接入语音问答

复制 `.env.example` 为 `.env`，填自己的 OpenAI、ElevenLabs 密钥和音色 ID。可以指定账号支持的 TTS 模型。使用服务可能产生费用。

```bash
cp .env.example .env
# 先编辑 .env，再运行：
margin serve examples/octopus.lesson.json --voice elevenlabs --paused
```

手机打开终端打印的 HTTPS 地址，在后面加 `/speaker?role=primary`，允许麦克风，点一次 **tap to begin** 解锁播放。试用时保持网页在前台，屏幕不要熄灭。

额外的 iPad 或手机打开 `https://<电脑地址>:8765/speaker?listen=0&mute=1`，就只显示嘴型。示例配置启用了 `MARGIN_SINGLE_SPEAKER=1`，只让主设备收音和确认声音播完。

手机使用麦克风需要 HTTPS 和可信证书。程序用 `openssl` 生成本地证书；iPhone / iPad 的安装步骤见[配置说明](docs/configuration.md#https-on-the-phone)。程序在终端前台运行，结束时关闭终端会话或按 Ctrl+C。

它会按准备好的讲稿讲解，尝试在你提问时停下来回答，再接着往下讲。短指令包括「继续」「等一下」「再说一遍」「跳过」。目前手机可能漏听，电脑的 `/remote` 页可以用文字提问。

## 换文章

```bash
margin build article.txt --explain "Simplified Chinese" --bedtime -o tonight.json
margin serve tonight.json --voice elevenlabs --paused
```

也能输入文章网址。备课需要 OpenAI 兼容的聊天 API；实时语音提问使用 OpenAI。其他兼容服务可以设置 `MARGIN_REALTIME=0`，改走先转写再回答的方式，但是否支持转写要看服务本身。

仓库包含手语村、章鱼睡觉、熊蜂玩球和中微子的示例课程。讲解内容需要结合原始来源核对。

## 合并了哪些内容

`src/margin` 是阅读、讲稿、语音问答和网页连接。`src/robot_lipsync` 是内置的多语言口型模块，保留中文、英文、西班牙语的口型规则、网页渲染、对齐示例和 OLED 工具。原来的 Python 导入方式和 `robot-lipsync` 命令仍可用。

伴读目前通过文字判断中文或英文；西班牙语口型可以通过模块 API 和命令行指定，伴读中的自动选择还没有验证。

示例配置要求配音服务同时返回真实字符时间戳，手动偏移设为 0；一个字内部的音素时间仍是估算。关闭严格模式后可使用原有对齐后备方式，`MARGIN_ALIGN=local` 表示本地估算，不把生成的录音上传到强制对齐服务。

公开内容包括代码、嘴型数据、示例课程、测试、配置模板、技术说明和可选 OLED 固件。密钥、录音、个人日志、拍摄私有脚本、机械臂轨迹、设备校准和本地证书都没有放进仓库。

[口型模块说明](docs/lipsync.md) · [原理](docs/device-companion.md) · [已知问题](docs/known-issues.md) · [数据流向](SECURITY.md)

## 开发和许可

```bash
pip install -e ".[dev,elevenlabs,serial]"
python -m pytest
python -m build
```

测试和 CI 不调用付费 API，不开启麦克风或电机。MIT 许可。原 [robot-lipsync 仓库](https://github.com/Muurrphy/robot-lipsync) 保留历史资料，之后统一维护 Margin。
