# Bibliothecary — 早期阅览室与口型分支

这里是 Margin 阶段的历史开发分支 `codex/multilingual-lipsync`。现行图书管理员、整本书阅读、Telegram 与读书记录功能请看 [main 主分支](https://github.com/Muurrphy/bibliothecary)。下文说明仅对应这个早期分支。

**旧 Kindle 上的 AI 伴读，手机上有一张会说话的数码嘴。**

Kindle 显示文章，并标出当前讲到的句子。手机或 iPad 播放讲解，接收语音提问，按语音时间显示口型。伴读目前选择中文或英文，单独使用的口型工具也支持西班牙语。

Kindle 不用越狱，也不用装任何东西。Kindle 和手机都只是打开网页，真正干活的是你电脑上的一个小程序。

[English](README.md) · [配置说明](docs/configuration.md) · [已知问题](docs/known-issues.md)

## 两部分：可以合起来用，也可以单独用

| 部分 | 是什么 | 单独拿来做什么 |
|---|---|---|
| **伴读**（`margin`） | Kindle 阅读页：划线、圈词、页边批注、小图示；提前备好的讲稿，可以随时打断；开口提问由大模型回答。 | 用电子书读文章，打字或说话提问，不需要嘴。 |
| **嘴型**（`robot_lipsync`） | 把语音的时间信息变成嘴型，支持中文、英文、西班牙语。可以画在网页上，也可以显示在 128×64 的 OLED 小屏上（带 ESP32 固件）。 | 任何需要“嘴跟着 TTS 声音动”的机器人、虚拟形象或小屏幕。 |

合在一起时，伴读说话，嘴就在手机上动。放在床头的手机，就变成一张给你讲书的小脸。

这个仓库原来叫 **robot-lipsync**。2026 年 10 月，嘴型项目和 Kindle 伴读合并到了这里，因为两个东西放在一起才最有意思。嘴型项目原来的提交历史都保留着。

## 每台设备干什么

| 设备 | 干什么 |
|---|---|
| Kindle（已在第 10 代，固件 5.16 上使用） | 显示文章、划线和批注。不录音。 |
| 手机或 iPad | 放声音、听你提问、显示嘴。 |
| 电脑 | 跑讲稿，调用模型，准备声音和嘴型时间。 |
| 更多手机或平板（可选） | 当额外的嘴，和主设备同时开口，不开麦克风。 |

所有设备连同一个 Wi-Fi。

## 跑起来

需要 Python 3.11 或更新版本。

```bash
git clone --branch codex/multilingual-lipsync https://github.com/Muurrphy/bibliothecary.git
cd bibliothecary
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 不用密钥、不花钱：用示例课程打开阅读页
margin serve examples/village.lesson.json --voice silent --paused
```

Kindle 的「实验性浏览器」打开终端里打印的 `http://<电脑地址>:8765/`；电脑打开 `http://localhost:8765/remote`，可以播放、暂停、打字提问。

只看嘴型：

```bash
robot-lipsync demo --text "你好，世界。" --language zh-CN --output build/mouth.html
```

这个预览用的是编出来的时间；接上真实配音后，时间来自配音服务。详见[嘴型说明](docs/lipsync.md)。

## 接上声音和语音提问

```bash
cp .env.example .env      # 填你自己的 OpenAI、ElevenLabs 密钥和音色 ID
margin serve examples/octopus.lesson.json --voice elevenlabs --paused
```

手机打开终端打印的 `https://…:8765/speaker`，点一下屏幕。手机用麦克风需要先装电脑生成的本地证书（步骤见[配置说明](docs/configuration.md#https-on-the-phone)）。在 Safari 里把这个地址的「网站设置 → 麦克风」设成「允许」，不然每次打开都会再问一遍。

你可以用语音询问文章内容，回答后继续播放讲稿。简单播放指令由程序直接处理，包括「继续」「等一下」「再说一遍」「跳过」「从头讲」「刷新」。最后被点过的那台设备负责听，其他设备只当安静的嘴。

## 换成自己的文章

```bash
margin build https://example.com/文章 --explain "Simplified Chinese" --bedtime -o tonight.json
margin serve tonight.json --voice elevenlabs --paused
```

讲稿是提前备好的（这篇讲什么 → 需要的背景 → 按顺序讲要点 → 为什么重要），一句不问也能听完整个故事。示例课程有：人人都会手语的村子、章鱼怎么睡觉、熊蜂玩小球、诺奖中微子。

## 原理

```text
电脑：讲稿 + 你的问题 → 回答 → 声音 + 每个字的时间
   ├─ Kindle：文章、划线、批注      （一个长轮询网页，老式 JavaScript）
   └─ 手机：声音 + 嘴（robot_lipsync）  麦克风 → 实时模型
```

- **Kindle 使用轻量网页。** 文字和普通 JavaScript 负责显示文章。请求设置了超时，连接中断后程序会尝试重画页面并恢复更新。
- **大模型不直接碰屏幕。** 它只返回和手写讲稿一样的小步骤，每一步都先和原文核对。
- **语音问题交给实时模型。** 手机通过电脑持续上传声音，OpenAI 处理问题并生成回答。请求卡住时，程序可改用语音转文字和文字模型。
- **回答一句一句地念。** 第一句先出声，后面的边念边准备。
- **嘴型跟着真实时间走。** 配音服务返回每个字在第几毫秒，嘴型模块把它变成口型，手机按自己的音频时钟画出来。

更多：[原理](docs/device-companion.md) · [嘴型模块](docs/lipsync.md) · [多语言](docs/multilingual.md) · [数据流向](SECURITY.md)

## 现状

早期原型，已在第 10 代 Kindle（固件 5.16）上演示，语音端使用过 iPhone 和 iPad。0.2.2 更新了连接恢复和语音上传处理，手机长时间使用仍在测试。见[已知问题](docs/known-issues.md)。

## 开发

```bash
pip install -e ".[dev,elevenlabs,serial]"
python -m pytest
```

测试全部离线：不用密钥、不开麦克风、不动电机。[参与贡献](CONTRIBUTING.md) · [更新记录](CHANGELOG.md) · [合并历史](docs/migration.md)

## 许可

MIT。
