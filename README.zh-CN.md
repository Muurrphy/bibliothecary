# Bibliothecary（图书管理员）

> **0.5.0a1 长期使用预览**：完整对话自动留存为文字，另存带出处的整理笔记；不要求说“记住”，不保存麦克风录音原件。保留原有黑白杂志界面。SQLite、后台任务、记忆纠正和学习安排已接入，实机与七天验收尚未完成。[升级与验收记录](docs/longterm-acceptance.md)。

**一个私人图书管理员。** 它为你备好今晚睡前读的文章，在旧 Kindle 或手机上陪你读，把你问的每个问题、它的每个回答都整理进读书报告，下一次就从你已经懂的地方接着来。

*Bibliothecary* 是英语里"图书管理员"的旧词，1610 年代进入英语，来自拉丁文 *bibliothecarius*。中文名就叫"图书管理员"，英文展示名 **The Librarian**。

[English](README.md) · [需求文档](docs/requirements.zh-CN.md) · [配置说明](docs/configuration.md) · [已知问题](docs/known-issues.md)

## 从图书管理员的职责出发

我们不是从"AI 能做什么"出发，而是从"一个好的图书管理员应该做什么"出发，把每一项职责对应到一项功能。

| 图书管理员的职责 | 对应到我们的功能 |
|---|---|
| **馆藏建设**：决定收什么、从哪收 | 书库：一份有品味的官方来源清单，分论文、新闻与长报道、书、散文；只收经典，或又新又好的 |
| **参考咨询**：先弄清读者真正想知道什么 | 每天在聊天框里主动问你一次今晚想读什么；第一次使用时了解你的兴趣和目标 |
| **读者顾问**：按人推荐，经典和新作搭配 | 选书规则：经典与新作交替、难易交替、按月节奏排布，不会天天塞论文 |
| **编目**：每本书都有记录、能查到 | 每篇文章入库时编目：来源、类型、主题、难度、是否读过，避免重复推荐 |
| **借阅记录** | 每晚的问答完整存档，写成当天的读书报告 |
| **读者教育**：教人读懂、会读 | 讲读有结构：先补先验知识，再讲正文，最后复习并提问 |
| **了解读者的知识水平** | 知识地图：从白天聊天和过往读书报告里判断你哪里懂、哪里有空缺 |
| **为读者保密** | 真正的图书管理员不会泄露借阅记录，所以只存在本地 |

图书管理员的职责几百年来变了很多。早期的 *bibliothecary*——亚历山大图书馆、中世纪修道院、17 世纪牛津的博德利图书馆——首先是守书人：收集、编目、别让书丢，有时还把书用链子锁在书架上。1627 年，诺代（Gabriel Naudé）主张既收古典名著，也收新作。现代图书管理员则是为读者服务：解答疑问、推荐书、教人读书，并为每个人的阅读记录保密。我们两头都取：从古代取认真编目、有品味地收书，从现代取围着一个人服务、保护他的隐私。

## 现在能做什么，接下来做什么

0.5.0a1 接续完整 0.4.0，是可靠性与自动整理的预览版。具体实现范围、边界和待验收项目见[长期使用验收](docs/longterm-acceptance.md)，历次变化见[更新记录](CHANGELOG.zh-CN.md)。

| | |
|---|---|
| **现在能用** | `biblio prepare` 把一篇文章做成三段式讲读：预习背景、正读、复习提问。`biblio read` 在 Kindle 和手机上讲读，接收语音提问，复习时等你回答，结束时自动归档一份读书报告。 |
| **也能用了** | `biblio telegram`：图书管理员住进 Telegram 聊天框。发它链接、文件或语音，它去备课；每天问你今晚想读什么；读完把读书报告发给你。 |
| **也能用了** | 读整本书：EPUB、TXT、PDF 一段一段读，记住进度，三种读法（读原文、拆书、精华原文），不剧透。 |
| **接下来** | 实机与七天验收；之后再考虑 MCP、原生 App 和公网访问 |

## 三部分：可以合起来用，也可以单独用

| 部分 | 是什么 |
|---|---|
| **图书管理员**（`biblio`） | 备课、保管记录、写读书报告。 |
| **Margin**（`margin`，页边） | 阅览室：Kindle 阅读页，有划线、圈词、页边批注、小图示；提前备好的讲稿，可以随时打断；开口提问由大模型回答。 |
| **嘴型**（`robot_lipsync`） | 把语音的时间信息变成嘴型，支持中文、英文、西班牙语。可以画在网页上，也可以显示在 128×64 的 OLED 小屏上（带 ESP32 固件）。可选。 |

设备怎么组合都可以：只用手机；Kindle 加电脑；Kindle 加手机；手机加 iPad；更多屏幕当额外的嘴。

### 只用手机，或者配 Kindle

Kindle 不是必须的。所有界面都是你自己电脑提供的网页，所以一部手机就够了：`/phone` 上面是文章，下面是声音、麦克风和嘴。

<img src="assets/phone-reading.png" alt="手机页面：文章里当前讲到的句子划了线，下面是批注卡片、正在说的话和嘴" width="300">

| 怎么读 | 打开 |
|---|---|
| 只用手机 | `https://<电脑地址>:8765/phone` |
| Kindle + 手机 | Kindle：`http://<电脑地址>:8765/` · 手机：`https://<电脑地址>:8765/speaker` |
| 手机 + iPad | 一台打开 `/`（文章），一台打开 `/speaker`（声音和嘴） |

用 `biblio telegram` 时不用记地址：每篇备好后，聊天里会出现 **📖 在手机上读** 按钮，点一下就在阅览室里打开这篇；Kindle 显示的就是当前打开的那篇。阅览室由你自己的电脑在家中网络提供；默认没有用户登录隔离，同一局域网能访问该端口的设备也能进入，不应直接暴露到公网。（在手机上用麦克风提问，需要先装一次电脑的证书，见[配置说明](docs/configuration.md#https-on-the-phone)；不装也能听、能看。）

## 跑起来

需要 Python 3.11 或更新版本。

```bash
git clone https://github.com/Muurrphy/bibliothecary.git
cd bibliothecary
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 不用密钥、不花钱：今晚的示例是"章鱼怎么睡觉"
biblio read examples/octopus.lesson.json --voice silent --paused
```

Kindle 用"体验版网页浏览器"打开终端打印的 `http://<电脑地址>:8765/`，电脑打开 `http://localhost:8765/remote`，就能播放、暂停、打字提问。讲完（或按 Ctrl+C）时，读书报告就归档了：

```bash
biblio records          # 读过的全部篇目
biblio report --show    # 最近一篇的读书报告
```

`bibliothecary` 和 `biblio` 是同一个命令。

## 今晚读什么

```bash
cp .env.example .env      # 填你自己的 OpenAI、ElevenLabs 密钥和音色 ID
biblio prepare https://example.com/文章 --explain "Simplified Chinese" --bedtime
biblio read --paused
```

声音会自动选：填了 ElevenLabs 密钥和 `MARGIN_ELEVEN_VOICE`（或 `ELEVENLABS_VOICE_ID`），手机上就有声音、嘴也会动；没填就只显示文字，启动时会明确打印 `voice: SILENT…` 告诉你缺什么。`biblio telegram` 开着的阅览室也一样。任何 ElevenLabs 音色都能用，包括你自己克隆的声音；想故意静音就加 `--voice silent`。

`biblio read` 不带名字时，打开最早一篇还没读完的。手机打开终端打印的 `https://…:8765/speaker`，点一下屏幕。手机用麦克风需要先装电脑生成的本地证书（步骤见[配置说明](docs/configuration.md#https-on-the-phone)）。在 Safari 里把这个地址的「网站设置 → 麦克风」设成「允许」，不然每次打开都会再问一遍。

一次讲读分三段：

1. **预习。** 读这篇之前你可能不知道的背景：术语、人物、原理。`biblio prepare --no-preview` 可以不要。
2. **正读。** 按文章顺序讲：这篇讲什么、主要观点、为什么重要。随时可以打断提问。
3. **复习。** 问你几个问题（`biblio prepare --review N`，默认 3 个）。图书管理员会等你回答，告诉你哪里答对了、还缺什么。说**继续**就跳过这一题。

简单播放指令由程序直接处理：「继续」「等一下」「再说一遍」「跳过」「从头讲」「刷新」「再问一遍」（回到复习题，读完以后也可以）。回答复习题时可以停下来想一想。最后被点过的那台设备负责听，其他设备只当安静的嘴。

## 在 Telegram 里找图书管理员

如果你没有自己的 personal agent，图书管理员可以住在一个 Telegram 聊天框里。

1. 在 Telegram 里找 **@BotFather**，发 `/newbot`，起个名字。它会给你一串 token。
2. 把它写进 `.env`：`TELEGRAM_BOT_TOKEN=...`
3. 运行 `biblio telegram --explain "Simplified Chinese"`，把终端打印的 `/start` 配对码发给你的新机器人。之后它只回应你一个人。

然后在哪儿都能用：

- **发链接、.txt/.md/.html/.pdf 文件，或者语音。** 它去备课，备好后把导读发回来：读之前要知道的背景和要点。
- **直接聊。** "找一篇章鱼睡觉的经典论文""来篇讲黑洞的好长文"：它会去搜开放获取的论文（OpenAlex、arXiv；经典=高被引，新作=近一年）或者在书库的书架里搜（科学写作和一手来源如 nobelprize.org、严肃新闻、散文、能读全文的书；清单见 `src/bibliothecary/shelves.toml`），推荐两三篇并说明理由，你选哪篇它就备哪篇。书库以外的网站一律进不来，它也只给真正搜到的链接。想改书库，把 `shelves.toml` 复制到 `~/Bibliothecary/` 再改。它也知道你读过什么、哪里还没弄懂。
- **第一次配对**时它先自我介绍：能做什么、文章从哪找、怎么读，然后问你**每天什么时候读**（“晚上 10 点”“早上 7 点半”“睡前”都行；以后发 `/time 21:30` 改）。
- **每天按你的时间转一圈**：读之前大约 10 小时问你想读什么（早上读的人，前一天晚上问）；读之前 45 分钟把备好的文章和「📖 在手机上读」按钮发给你，点开就能读。你那天没说想读什么，它就按对你的了解自己挑一篇、备好再发。晚上读的人收到“晚上好”，讲完跟你说晚安；早上读的人收到“早上好”。还没告诉它时间之前，用 `--ask-at 12:00` 和 `--decide-at 19:00`。
- **讲完以后**，读书报告会发到聊天框里。
- `/tonight` 今晚读什么，`/records` 读过的，`/report` 最近的读书报告，`/profile` 它记得的关于你的事。

它说话像图书管理员，不像搜索框：你只说"今晚读什么"，它会先问你最近在想什么、读来做什么，再结合你的情况推荐，并讲清理由。每一批搜索结果都要经过第二道严格筛选，只有真正切题、值得花一晚上的才会拿出来；宁可只推荐一篇好的，也不凑三篇。它对你的了解存在 `~/Bibliothecary/reader.json`。

聊天和挑书需要判断力，可以用比备课更强的模型：在 `.env` 里设 `BIBLIOTHECARY_CHAT_MODEL`（或者加 `--chat-model`）。不开 Telegram 也能试：`biblio chat "今晚读什么"` 在终端里跟它聊，记忆和 Telegram 共用，并且会把每次搜索、留下了哪些、为什么都打印出来。

机器人要回消息，电脑得开着。聊天消息会经过 Telegram 的服务器；篇目和读书记录都留在你自己的电脑上。你和图书管理员的聊天记录存在本地的 `~/Bibliothecary/chat.jsonl`。

## 读整本书

在 Telegram 里把书发给图书管理员（EPUB，或者很长的 TXT、PDF），或者运行 `biblio book add <文件>`。书会放进 `~/Bibliothecary/books/`，按书自己的目录切成章；图书管理员记住你读到哪，每次备一段，下一次从你停下的地方接着读，开头先说一句前情提要。

读一本书有三种读法。图书管理员按书的类型先给建议，用 `/mode`（或 `--mode`）可以改。

| 读法 | 适合 | 怎么读 |
|---|---|---|
| **读原文** | 小说、散文、回忆录 | 你自己读原文，图书管理员尽量不出声：只在真会卡住的地方加注（典故、旧词、人名），光标按阅读速度往下走，读完问一两个开放的问题，没有标准答案。 |
| **拆书** | 科普、社科、讲道理的书 | 第一次先讲全书地图：这本书想回答什么、它的回答、怎么搭起来的、哪几章最重要。之后一次讲一章，不用每句都读。 |
| **精华原文** | 讲道理的书，又想看作者原话 | 只挑一章里最值得读的几段原文，逐句细读；段与段之间发生了什么，用一句话交代。挑的是书里整段原文，按段落编号取出来，不会出现编出来的"原文"。 |

不剧透：章节笔记只做到你读到的地方，前情提要只用你读过的内容，讲读时就算它知道这本书，也不会告诉你后面发生什么。一段读完才算数，进度随之往前走。Telegram 里：`/book`（在读的书和进度）、`/books`（书架）、`/mode`、`/next`、`/book pause`。有书在读时，每天的固定时间会备这本书的下一段，而不是另挑文章。每段的长度由 `BIBLIOTHECARY_BOOK_MINUTES` 决定（默认 20 分钟）。全书地图、注释和挑段落用 `BIBLIOTHECARY_BOOK_MODEL`（没设就用 `BIBLIOTHECARY_CHAT_MODEL`）。有 DRM 的书（Kindle 商店、微信读书）读不了；你自己的文件和公版书（Standard Ebooks、Project Gutenberg、维基文库）都可以。设计说明见 [docs/design/books.zh-CN.md](docs/design/books.zh-CN.md)。

### 图书馆自己的书

手边没书也行：图书管理员有一份值得读的公版书单（[`catalog.toml`](src/bibliothecary/catalog.toml)），分两个书架：生命与心智（达尔文、赫胥黎、威廉·詹姆斯、法拉第），文明与散文（蒙田、爱默生、梭罗、马可·奥勒留、塞涅卡、泰戈尔、密尔、托克维尔、柏拉图、王国维）。`biblio book catalog` 看书单，`biblio book get darwin-emotions` 把一本取到你的书架上；Telegram 里是 `/library` 和 `/get darwin-emotions`。书只从三个干净的来源取：[Standard Ebooks](https://standardebooks.org)（它自己做的部分以 CC0 捐给公有领域）、[Project Gutenberg](https://www.gutenberg.org)（上架时去掉它带商标的页眉和许可声明）和[维基文库](https://zh.wikisource.org)。书单里每本书在美国都是公版，作者和译者都已去世七十年以上，所以在按“去世后 70 年”或“50 年”计算的国家也都是公版；现代译本和带注释的版本一律不收。想加自己的书，写在 `~/Bibliothecary/catalog.toml`。

项目里自带一本短书，不联网也能试：塞涅卡《论生命之短暂》（Aubrey Stewart 1900 年英译本，来自 Standard Ebooks，约八千词）。`biblio book get sample`，或者在 Telegram 里发 `/get sample`。

## 读书报告

每篇文章一个文件夹，全部在你自己的电脑上：

```text
~/Bibliothecary/readings/2026-10-08-how-octopuses-sleep/     （用 $BIBLIOTHECARY_HOME 换位置）
  lesson.json      要讲的内容：预习、正读、复习
  session.jsonl    每个问题和回答的原文，说出口就立刻写下
  summary.json     模型对这次讲读的整理（可选）
  report.md        读书报告
```

读书报告分两次写。`biblio prepare` 在读之前写好导读（背景和要点笔记）；讲完后补上每一问每一答的原文、你的复习回答和参考答案；有模型时，再加上"我还没弄懂的"和"值得追的线索"。摘要和原文分开放，从不用摘要代替原文。报告用讲解语言写。格式是带 YAML 头的 Markdown：任何笔记软件都能打开，可以放进 git，agent 也能读。

## 每台设备干什么

| 设备 | 干什么 |
|---|---|
| Kindle（已在第 10 代，固件 5.16 上使用） | 显示文章、划线和批注。不录音。 |
| 手机或 iPad | 放声音、听你提问、显示嘴。 |
| 电脑 | 备课，调用模型，保管记录。 |
| 更多手机或平板（可选） | 当额外的嘴，和主设备同时开口，不开麦克风。 |

所有设备连同一个 Wi-Fi，讲读时电脑要开着。

## 原理

```text
电脑：讲稿 + 你的问题 → 回答 → 声音 + 每个字的时间 → 借阅记录
   ├─ Kindle：文章、划线、批注      （一个长轮询网页，老式 JavaScript）
   └─ 手机：声音 + 嘴（robot_lipsync）  麦克风 → 实时模型
```

- **Kindle 使用轻量网页。** 文字和普通 JavaScript 负责显示文章。请求设置了超时，连接中断后程序会尝试重画页面并恢复更新。
- **大模型不直接碰屏幕。** 它只返回和手写讲稿一样的小步骤，每一步都先和原文核对。
- **语音问题交给实时模型。** 手机通过电脑持续上传声音，OpenAI 处理问题并生成回答。请求卡住时，程序可改用语音转文字和文字模型。
- **回答一句一句地念。** 第一句先出声，后面的边念边准备。
- **嘴型依据语音时间戳，按音频时钟播放。** 程序会在本地检查音频波形；句段和停顿能明确对应时，校正句段边界，并在检测到的静音处收嘴。每个字内部的音素时间仍是估算，还不是逐音素强制对齐。详见[嘴型同步说明](docs/lipsync.md#timing-checks-in-the-reading-companion)。
- **先记录取得的文字，再回答和整理。** 评论和闲聊也会归档；转写失败明确标缺口，summary 不覆盖原文。

更多：[需求文档](docs/requirements.zh-CN.md) · [原理](docs/device-companion.md) · [嘴型模块](docs/lipsync.md) · [多语言](docs/multilingual.md) · [数据流向](SECURITY.md)

## 隐私

真正的图书管理员不会泄露借阅记录，所以只存在本地。篇目、记录和读书报告都在本地文件夹里。你配置的模型和语音服务会收到请求需要的原文、相关历史、用于转写的声音，以及读后整理需要的对话文字。本地档案不会公开发布；模型功能不是完全离线运行。见 [SECURITY.md](SECURITY.md)。

## 单独用阅览室或嘴

```bash
margin serve examples/village.lesson.json --voice silent --paused     # 只用阅览室，不留记录
margin build https://example.com/文章 -o tonight.json                  # 只生成讲稿文件
robot-lipsync demo --text "你好，世界。" --language zh-CN --output build/mouth.html
```

见[嘴型说明](docs/lipsync.md)。

## 现状

早期原型，已在第 10 代 Kindle（固件 5.16）上演示，语音端使用过 iPhone 和 iPad。手机长时间使用仍在测试。见[已知问题](docs/known-issues.md)。

这个仓库最早叫 **robot-lipsync**；2026 年 10 月嘴型项目和 Kindle 伴读合并，改名 **Margin**；伴读长成图书管理员后，改名 **Bibliothecary**。完整的提交历史都保留着（[合并历史](docs/migration.md)）。

## 开发

```bash
pip install -e ".[dev,elevenlabs,serial]"
python -m pytest
```

测试全部离线：不用密钥、不开麦克风、不动电机。[参与贡献](CONTRIBUTING.md) · [更新记录](CHANGELOG.zh-CN.md)（[English](CHANGELOG.md)）

## 许可

MIT。
