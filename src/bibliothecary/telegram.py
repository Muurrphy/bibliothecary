"""The librarian in a Telegram chat, for when you have no personal agent.

    biblio telegram          (needs TELEGRAM_BOT_TOKEN, from @BotFather)

It answers only the one person who paired with it (``/start <code>`` with the code
printed in the terminal). What it does:

- a link or a file (.txt, .md, .html, .pdf): it prepares the reading and sends the guide back;
- "something on X": it searches open-access papers (OpenAlex, arXiv) or the web, suggests a few,
  and prepares the one you choose;
- a voice message: transcribed, then handled like text;
- anything else: the librarian talks with you about what to read, knowing your records;
- once a day (``--ask-at``) it asks what you'd like to read tonight;
- in the evening (``--decide-at``) it says what tonight's reading is;
- when a session ends, it sends the reading report.

Messages pass through Telegram's servers. The records stay in the local folder.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from margin.lesson import Lesson

from . import library, report
from .desk import Desk

URL = re.compile(r"https?://\S+")
FILE_TYPES = (".txt", ".md", ".html", ".htm", ".pdf")


class TelegramError(RuntimeError):
    pass


class Bot:
    """The few Bot API calls the librarian needs, over plain HTTPS."""

    def __init__(self, token: str, timeout: float = 70.0) -> None:
        self.base = f"https://api.telegram.org/bot{token}"
        self.files = f"https://api.telegram.org/file/bot{token}"
        self.timeout = timeout

    def _call(self, method: str, data: bytes, content_type: str) -> Any:
        req = urllib.request.Request(f"{self.base}/{method}", data=data, headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                body = json.loads(res.read())
        except urllib.error.HTTPError as err:
            body = json.loads(err.read() or b"{}")
        except (urllib.error.URLError, OSError) as err:
            raise TelegramError(f"cannot reach Telegram: {getattr(err, 'reason', err)}") from err
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', 'failed')}")
        return body["result"]

    def call(self, method: str, **params: Any) -> Any:
        return self._call(method, json.dumps(params).encode(), "application/json")

    def updates(self, offset: int, wait: int = 30) -> list[dict]:
        return self.call("getUpdates", offset=offset, timeout=wait, allowed_updates=["message"])

    def send(self, chat: int, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        """``buttons``: [(label, url)] shown under the message, e.g. a link that opens the reading."""
        pieces = split(text)
        for n, piece in enumerate(pieces):
            params: dict[str, Any] = {"chat_id": chat, "text": piece, "link_preview_options": {"is_disabled": True}}
            if buttons and n == len(pieces) - 1:
                params["reply_markup"] = {"inline_keyboard": [[{"text": label, "url": url}] for label, url in buttons]}
                try:
                    self.call("sendMessage", **params)
                    continue
                except TelegramError as err:                 # Telegram refused the address: send it as text
                    if "url" not in str(err).lower() and "button" not in str(err).lower():
                        raise
                    params.pop("reply_markup")
                    params["text"] = piece + "\n\n" + "\n".join(f"{label}: {url}" for label, url in buttons)
            self.call("sendMessage", **params)

    def typing(self, chat: int) -> None:
        try:
            self.call("sendChatAction", chat_id=chat, action="typing")
        except TelegramError:
            pass

    def send_file(self, chat: int, path: Path, caption: str = "") -> None:
        boundary = uuid.uuid4().hex
        fields = [("chat_id", str(chat))] + ([("caption", caption[:1000])] if caption else [])
        body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                        for k, v in fields)
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{path.name}"\r\n'
                 "Content-Type: text/markdown\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        self._call("sendDocument", body, f"multipart/form-data; boundary={boundary}")

    def download(self, file_id: str) -> bytes:
        path = self.call("getFile", file_id=file_id)["file_path"]
        with urllib.request.urlopen(f"{self.files}/{path}", timeout=self.timeout) as res:
            return res.read()


def split(text: str, size: int = 3900) -> list[str]:
    """Telegram takes at most 4096 characters per message: cut at paragraph or line ends."""
    pieces, rest = [], text.strip()
    while len(rest) > size:
        cut = max(rest.rfind("\n\n", 0, size), rest.rfind("\n", 0, size))
        cut = cut if cut > size // 2 else size
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    return [*pieces, rest] if rest else pieces


def _say(language: str, zh: str, en: str) -> str:
    return zh if report.chinese(language) else en


class Librarian:
    """Everything the chat does, independent of the network (``bot`` and ``client`` can be fakes)."""

    def __init__(self, bot, client=None, *, explain: str = "English", bedtime: bool = True, review: int = 3,
                 ask_at: str = "12:00", decide_at: str = "19:00", prepare: Callable[..., Path] | None = None,
                 now: Callable[[], dt.datetime] | None = None, log: Callable[[str], None] | None = None,
                 chat_model: str | None = None, room=None) -> None:
        self.bot, self.client, self.explain = bot, client, explain
        self.bedtime, self.review = bedtime, review
        self.ask_at, self.decide_at = _hhmm(ask_at), _hhmm(decide_at)
        self._prepare = prepare
        self.now = now or (lambda: dt.datetime.now().astimezone())
        self.log = log or (lambda _msg: None)
        self.state_file = library.home() / "telegram.json"
        self.state = self._load()
        self._lock = threading.Lock()
        self.jobs: list[threading.Thread] = []
        self.desk = Desk(client, language=explain, model=chat_model, now=self.now, log=self.log)
        self.room = room                                   # a ReadingRoom, so links can open readings

    # ---- state -----------------------------------------------------------------------
    def _load(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @property
    def owner(self) -> int | None:
        return self.state.get("owner")

    def pairing_code(self) -> str:
        if not self.state.get("code"):
            self.state["code"] = f"{secrets.randbelow(900000) + 100000}"
            self.save()
        return self.state["code"]

    def t(self, zh: str, en: str) -> str:
        return _say(self.explain, zh, en)

    def _remember(self, who: str, text: str) -> None:
        self.desk.remember(who, text)

    def send(self, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        if buttons:
            self.bot.send(self.owner, text, buttons)
        else:
            self.bot.send(self.owner, text)
        self._remember("librarian", text)

    def read_here(self, folder: Path) -> tuple[str, list[tuple[str, str]] | None]:
        """How to start reading: a button for the phone and the Kindle's address, or the command."""
        if self.room is None:
            return self.t("晚上在电脑上运行 biblio read 就能听。", "Run biblio read tonight to hear it."), None
        if self.room.folder is None or library.status(self.room.folder) == "read":
            self.room.open(folder.name)                   # nothing else open: the Kindle shows this one
        return (self.t(f"点下面的按钮在手机上读（要和电脑连同一个 Wi-Fi）；用 Kindle 就打开 {self.room.kindle}",
                       f"Tap below to read on your phone (same Wi-Fi as the computer); on the Kindle open {self.room.kindle}"),
                [(self.t("📖 在手机上读", "📖 Read on this phone"), self.room.link(folder))])

    # ---- incoming messages -----------------------------------------------------------
    def handle(self, update: dict) -> None:
        msg = update.get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        text = (msg.get("text") or msg.get("caption") or "").strip()
        if chat is None:
            return
        if self.owner is None:
            if text == f"/start {self.state.get('code')}" and self.state.get("code"):
                self.state["owner"] = chat
                self.state.pop("code", None)
                self.save()
                self.log(f"paired with Telegram chat {chat}")
                self.send(self.t(
                    "你好，我是你的图书管理员。发我一个链接或文件，我来备课；想读什么也可以直接跟我聊。"
                    "每天我会问你一次今晚想读什么。\n\n提醒一句：聊天消息会经过 Telegram 的服务器；"
                    "你的读书记录只存在你自己的电脑上。\n\n命令：/tonight 今晚读什么 · /records 读过的 · /report 最近的读书报告 · /profile 我记得的关于你的事",
                    "Hello, I'm your librarian. Send me a link or a file and I'll prepare it; or just tell me what "
                    "you'd like to read. Once a day I'll ask what you want to read tonight.\n\nNote: chat messages "
                    "pass through Telegram's servers; your reading records stay on your own computer.\n\n"
                    "Commands: /tonight · /records · /report · /profile"))
            return
        if chat != self.owner:
            return                                 # a librarian never talks about you to strangers
        if msg.get("voice") or msg.get("audio"):
            text = self._transcribe(msg)
            if not text:
                return
        elif msg.get("document"):
            return self._document(msg["document"])
        if not text:
            return
        self._remember("reader", text)
        command = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        if command in ("/start", "/help"):
            return self.send(self.t("发链接或文件给我备课；/tonight 今晚读什么；/records 读过的；/report 最近的读书报告。",
                                    "Send a link or file to prepare it. /tonight · /records · /report"))
        if command == "/tonight":
            return self.send(*self.tonight())
        if command == "/records":
            return self.send(self.records())
        if command == "/profile":
            facts = self.desk.reader()
            return self.send("\n".join(f"· {f}" for f in facts) if facts else
                             self.t("我对你还了解得不多。多聊聊吧。", "I don't know much about you yet. Tell me more."))
        if command == "/report":
            return self.send_report(self._latest_read(), quiet=False)
        found = URL.search(text)
        if found:
            return self.start_prepare(found.group(0).rstrip(").,，。）"))
        reply = self.chat(text)
        if reply:
            self.send(reply)

    def _transcribe(self, msg: dict) -> str:
        if self.client is None:
            self.send(self.t("听语音需要配置模型密钥；先打字给我吧。", "I need a model key to hear voice messages; please type."))
            return ""
        media = msg.get("voice") or msg.get("audio")
        try:
            audio = self.bot.download(media["file_id"])
            text = self.client.transcribe(audio, filename="voice.ogg", mime=media.get("mime_type") or "audio/ogg")
        except Exception as err:
            self.log(f"voice message failed: {err}")
            self.send(self.t("这条语音我没听清，再说一次或者打字吧。", "I couldn't hear that one; try again or type it."))
            return ""
        return text.strip()

    def _document(self, doc: dict) -> None:
        name = Path(doc.get("file_name") or "article.txt").name
        if not name.lower().endswith(FILE_TYPES):
            return self.send(self.t("这种文件我还读不了。发 .txt、.md、.html、.pdf，或者直接发链接。",
                                    "I can't read that kind of file yet. Send .txt, .md, .html, .pdf, or a link."))
        inbox = library.home() / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        path = inbox / name
        path.write_bytes(self.bot.download(doc["file_id"]))
        self._remember("reader", f"(file) {name}")
        self.start_prepare(str(path))

    # ---- preparing -------------------------------------------------------------------
    def start_prepare(self, article: str, *, quiet: bool = False) -> None:
        if self.client is None and self._prepare is None:
            return self.send(self.t("备课需要模型密钥（.env 里的 OPENAI_API_KEY）。",
                                    "Preparing needs a model key (OPENAI_API_KEY in .env)."))
        if not quiet:
            self.send(self.t("收到，我去备课，好了告诉你。", "Got it. I'll prepare it and tell you when it's ready."))
        job = threading.Thread(target=self._prepare_now, args=(article,), daemon=True, name="bibliothecary-prepare")
        self.jobs.append(job)
        job.start()

    def _prepare_now(self, article: str) -> None:
        try:
            if self._prepare is not None:
                folder = self._prepare(article)
            else:
                from .prepare import prepare

                folder = prepare(self.client, article, explain=self.explain, bedtime=self.bedtime,
                                 review=self.review, log=self.log)
        except Exception as err:
            self.log(f"preparing {article} failed: {err}")
            if "almost no text" in str(err):
                return self.send(self.t("这篇只读到了很少的文字，多半是付费墙或者只有摘要，没法备成讲稿。"
                                        "要不要我找一篇能读全文的？",
                                        "I could only reach a few lines of that one (probably a paywall or "
                                        "just the abstract). Shall I find one that can be read in full?"))
            return self.send(self.t(f"这篇没备成：{err}", f"I couldn't prepare that one: {err}"))
        how, buttons = self.read_here(folder)
        with self._lock:
            self.send(self.guide(folder) + "\n\n" + how, buttons)

    def guide(self, folder: Path) -> str:
        lesson = Lesson.load(folder / "lesson.json")
        preview = [s.say for s in lesson.steps if s.part == "preview" and s.say]
        notes = [s.note for s in lesson.steps if s.note and s.part is None]
        questions = sum(1 for s in lesson.steps if s.expect)
        lines = [self.t(f"备好了：《{lesson.title}》", f"Ready: “{lesson.title}”")]
        if preview:
            lines += ["", self.t("读之前要知道的：", "Before you read:"), *(f"· {p}" for p in preview)]
        if notes:
            lines += ["", self.t("要点：", "Main points:"), *(f"· {n}" for n in notes[:8])]
        lines += ["", self.t(f"讲完会问你 {questions} 个问题。", f"{questions} review questions at the end.")]
        return "\n".join(lines)

    # ---- talking ---------------------------------------------------------------------
    def scripted(self) -> str | None:
        """A rehearsed demo: with ``demo.json`` in the library folder, each message gets the next
        prepared reply instead of the model's, so a filmed demo goes the same way every take.

        {"next": 0, "steps": [{"reply": "...", "delay": 3, "open": "<reading folder name>"}]}
        ``open`` then sends that reading's guide and button, as if it had just been prepared.
        Edit or delete the file at any time; when the steps run out the real librarian answers."""
        path = library.home() / "demo.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            steps, n = data.get("steps") or [], int(data.get("next") or 0)
        except (OSError, ValueError, TypeError) as err:
            self.log(f"demo.json unreadable, answering for real: {err}")
            return None
        if n >= len(steps):
            return None
        step = steps[n]
        data["next"] = n + 1
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.log(f"demo step {n + 1} of {len(steps)}")
        end = time.monotonic() + float(step.get("delay") or 0)
        while time.monotonic() < end:
            self.bot.typing(self.owner)
            time.sleep(min(4.0, max(0.0, end - time.monotonic())))
        reply = str(step.get("reply") or "")
        name = step.get("open")
        if not name:
            return reply
        if reply:
            self.send(reply)
        folder = library.readings_dir() / Path(str(name)).name
        wait = time.monotonic() + float(step.get("prepare_delay") or 0)
        while time.monotonic() < wait:
            self.bot.typing(self.owner)
            time.sleep(min(4.0, max(0.0, wait - time.monotonic())))
        how, buttons = self.read_here(folder)
        with self._lock:
            self.send(self.guide(folder) + "\n\n" + how, buttons)
        return ""

    def chat(self, text: str) -> str | None:
        """Talk at the reference desk. Returns the reply (None when it already went out)."""
        demo = self.scripted()
        if demo is not None:
            return demo or None
        if self.client is None:
            return self.t("想读什么，发我一个链接或文件就行。", "Send me a link or a file and I'll prepare it.")
        self.bot.typing(self.owner)
        try:
            answer = self.desk.reply(text)
        except Exception as err:
            self.log(f"chat failed: {err}")
            if any(w in str(err) for w in ("insufficient_quota", "credit_balance", "no credits")):
                return self.t("OpenAI 账户余额用完了。充值后把刚才那句再发一次就行。",
                              "The OpenAI account is out of credit. Top it up, then send that again.")
            if "401" in str(err) or "invalid_api_key" in str(err):
                return self.t("OpenAI 密钥不对或过期了，检查一下 .env 里的 OPENAI_API_KEY。",
                              "The OpenAI key was refused; check OPENAI_API_KEY.")
            return self.t("我这边连不上模型，稍后再说。", "I can't reach the model right now; try again later.")
        for line in answer.trace:
            self.log(line)
        reply = answer.text or self.t("我没找到够好的，换个方向试试？", "I couldn't find anything good enough; another angle?")
        if answer.prepare:
            self.send(reply)
            self.start_prepare(answer.prepare, quiet=True)
            return None
        return reply

    def tonight(self) -> tuple[str, list[tuple[str, str]] | None]:
        folder = library.next_unread()
        if folder is None:
            return self.t("今晚还没有要读的。发我一个链接吧。", "Nothing to read tonight yet. Send me a link."), None
        title = Lesson.load(folder / "lesson.json").title
        how, buttons = self.read_here(folder)
        return self.t(f"今晚读《{title}》。", f"Tonight: “{title}”.") + "\n" + how, buttons

    def records(self) -> str:
        found = library.readings()[-10:]
        if not found:
            return self.t("还没有读书记录。", "No readings yet.")
        names = {"prepared": self.t("待读", "to read"), "started": self.t("读了一半", "started"),
                 "read": self.t("读完", "read")}
        return "\n".join(f"{f.name[:10]} · {names[library.status(f)]} · {Lesson.load(f / 'lesson.json').title}"
                         for f in found)

    def _latest_read(self) -> Path | None:
        done = [f for f in library.readings() if library.status(f) == "read"]
        return done[-1] if done else None

    def send_report(self, folder: Path | None, *, quiet: bool = True) -> None:
        if folder is None:
            if not quiet:
                self.send(self.t("还没有读完的篇目。", "Nothing has been read yet."))
            return
        lesson = Lesson.load(folder / "lesson.json")
        events = library.events(folder)
        asked = sum(1 for e in events if e.get("kind") == "exchange" and not e.get("review"))
        lines = [self.t(f"《{lesson.title}》的读书报告。" + (f"今晚你问了 {asked} 个问题。" if asked else ""),
                        f"The reading report for “{lesson.title}”." + (f" You asked {asked} questions." if asked else ""))]
        summary = folder / "summary.json"
        if summary.is_file():
            unclear = json.loads(summary.read_text(encoding="utf-8")).get("unclear") or []
            if unclear:
                lines.append(self.t("还没弄懂的：", "Still unclear:") + " " + "；".join(unclear))
        self.bot.send_file(self.owner, folder / "report.md", "\n".join(lines))
        self._remember("librarian", f"(sent the report) {lesson.title}")

    # ---- the daily round -------------------------------------------------------------
    def tick(self) -> None:
        """Called every few seconds: the daily question, tonight's choice, new reports."""
        if self.owner is None:
            return
        now = self.now()
        today, clock = now.date().isoformat(), (now.hour, now.minute)
        late = (min(23, self.decide_at[0] + 3), self.decide_at[1])
        # each message only within its own window, so starting the bot at midnight sends nothing
        if self.ask_at <= clock < self.decide_at and self.state.get("asked") != today:
            self.state["asked"] = today
            self.save()
            self.send(self.daily_question())
        if self.decide_at <= clock < late and self.state.get("decided") != today:
            self.state["decided"] = today
            self.save()
            self.send(*self.tonight())
        sent = set(self.state.get("reported") or [])
        for folder in library.readings():
            if library.status(folder) == "read" and folder.name not in sent:
                if self.state.get("watching"):           # not on the first start: old reports stay put
                    self.send_report(folder)
                sent.add(folder.name)
        if sent != set(self.state.get("reported") or []) or not self.state.get("watching"):
            self.state["reported"], self.state["watching"] = sorted(sent), True
            self.save()

    def daily_question(self) -> str:
        lines = [self.t("今晚想读点什么？", "What would you like to read tonight?")]
        waiting = [f for f in library.readings() if library.status(f) != "read"]
        if waiting:
            titles = "、".join(f"《{Lesson.load(f / 'lesson.json').title}》" for f in waiting[:3])
            lines.append(self.t(f"已经备好的：{titles}。", "Already prepared: " + ", ".join(
                f"“{Lesson.load(f / 'lesson.json').title}”" for f in waiting[:3]) + "."))
        latest = self._latest_read()
        if latest and (latest / "summary.json").is_file():
            threads = json.loads((latest / "summary.json").read_text(encoding="utf-8")).get("threads") or []
            if threads:
                lines.append(self.t(f"上次读完留下的线索：{threads[0]}", f"A thread from last time: {threads[0]}"))
        lines.append(self.t("发我一个链接或文件，或者跟我说说想读什么方向。",
                            "Send me a link or a file, or tell me what you're in the mood for."))
        return "\n".join(lines)


def _hhmm(value: str) -> tuple[int, int]:
    hours, minutes = value.split(":")
    return int(hours), int(minutes)


def run(token: str, client, *, log: Callable[[str], None], room=None, **options) -> None:
    bot = Bot(token)
    librarian = Librarian(bot, client, log=log, room=room, **options)
    me = bot.call("getMe")
    if librarian.owner is None:
        print(f"\n  In Telegram, open @{me['username']} and send:   /start {librarian.pairing_code()}\n", flush=True)
    else:
        print(f"\n  The librarian is on Telegram as @{me['username']}. Ctrl+C to stop.\n", flush=True)
    offset = 0
    while True:
        try:
            for update in bot.updates(offset, wait=20):
                offset = update["update_id"] + 1
                try:
                    librarian.handle(update)
                except Exception as err:            # one bad message never stops the librarian
                    log(f"message failed: {err}")
            librarian.tick()
        except TelegramError as err:
            log(f"{err}; trying again in 10 s")
            time.sleep(10)
