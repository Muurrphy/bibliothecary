"""The librarian in a Telegram chat, for when you have no personal agent.

    biblio telegram          (needs TELEGRAM_BOT_TOKEN, from @BotFather)

It answers only the one person who paired with it (``/start <code>`` with the code
printed in the terminal). What it does:

- a link or a file (.txt, .md, .html, .pdf): it prepares the reading and sends the guide back;
- a whole book (.epub, or a long .txt/.pdf): it goes on the shelf; the librarian keeps your place and
  prepares one session at a time, read as text (读原文), digest (拆书) or best passages (精华原文);
  ``/book``, ``/books``, ``/mode``, ``/next``. While a book is open, the daily round continues it;
- "something on X": it searches open-access papers (OpenAlex, arXiv) or the web, suggests a few,
  and prepares the one you choose;
- a voice message: transcribed, then handled like text;
- anything else: the librarian talks with you about what to read, knowing your records;
- on pairing it introduces itself and asks when you usually read (``/time`` changes it);
- around that time each day it asks what you'd like (10 h before) and sends the prepared reading
  (45 min before), choosing and preparing one itself when you said nothing; greetings follow the
  time of day (good night for evening readers). Until it knows your time: ``--ask-at``/``--decide-at``;
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

from . import books, library, report
from .desk import Desk

URL = re.compile(r"https?://\S+")
FILE_TYPES = (".txt", ".md", ".html", ".htm", ".pdf", ".epub")


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
            return self.t("在电脑上运行 biblio read 就能听。", "Run biblio read on the computer to hear it."), None
        if self.room.folder is None or library.status(self.room.folder) == "read":
            self.room.open(folder.name)                   # nothing else open: the Kindle shows this one
        return (self.t(f"点下面的按钮在手机上读（要和电脑连同一个 Wi-Fi）；用 Kindle 就打开 {self.room.kindle}",
                       f"Tap below to read on your phone (same Wi-Fi as the computer); on the Kindle open {self.room.kindle}"),
                [(self.t("📖 在手机上读", "📖 Read on this phone"), self.room.link(folder))])

    # ---- getting to know each other -----------------------------------------------------
    def introduction(self) -> str:
        return self.t(
            "你好，我是你的私人图书管理员。\n\n"
            "我能帮你做这些事：\n"
            "· 找值得读的东西。论文我从 OpenAlex、arXiv 里找能读到全文的；长文只从一批靠谱的来源里找，"
            "比如 nobelprize.org、Quanta、Nature、知识分子。不推营销号，链接只给真正搜到的。\n"
            "· 把文章备成讲稿：先补你可能缺的背景，再按顺序讲要点，最后问你几个问题。\n"
            "· 陪你读。点我发的「📖 在手机上读」：上面是原文，讲到哪句就标到哪句，重要的地方会弹出批注；"
            "下面是我的声音和一张会说话的嘴。随时开口打断我提问；我不确定的事，会先上网查。\n"
            "· 记住你。每次的问答都记进读书报告，读完发给你；下次挑文章会参考你读过什么、哪里还没弄懂。\n"
            "· 陪你读整本书。把 EPUB、TXT 或 PDF 发给我，我记住你读到哪，每次备一段：小说散文就读原文，"
            "我只在难处加注，开头说一句前情提要（绝不剧透）；知识类的书可以拆书讲，或者只挑最值得读的原文段落。"
            "没有书的话，/library 里有一份公版书单。\n\n"
            "你也可以随时发我链接、PDF 或语音，我来备课。你的读书记录只存在你自己的电脑上"
            "（聊天消息会经过 Telegram 的服务器）。\n\n"
            "先问你一件事：你一般每天什么时候读？比如“晚上 10 点”“早上 7 点半”“午休 12 点半”。"
            "我会每天提前问你想读什么，到点前把文章备好，你点开就能读。",
            "Hello, I'm your personal librarian.\n\n"
            "Here is what I do:\n"
            "· Find things worth reading. Papers come from OpenAlex and arXiv, only ones you can read in full; "
            "long reads only from a shelf of sources I trust, like nobelprize.org, Quanta and Nature. "
            "No clickbait, and every link is one I really found.\n"
            "· Prepare a reading: the background you may be missing, the main points in order, then a few "
            "questions for you.\n"
            "· Read it with you. Tap “📖 Read on this phone” when I send it: the article on top, the sentence "
            "I'm on underlined, notes popping up where they matter, and my voice and a talking mouth below. "
            "Interrupt me any time with a question; if I'm not sure of something, I look it up first.\n"
            "· Remember you. Every question and answer goes into a reading report I send you afterwards, "
            "and I choose the next reading with what you've read and what's still unclear in mind.\n"
            "· Read whole books with you. Send an EPUB, TXT or PDF; I keep your place and prepare one part at a "
            "time: novels and essays in their own words, with notes only where it's hard and a “previously” that "
            "never gives anything away; idea books as a digest, or just the passages most worth reading. "
            "No book at hand? /library has a list of public-domain ones.\n\n"
            "You can also send me a link, a PDF or a voice message any time. Your reading records stay on "
            "your own computer (chat messages pass through Telegram's servers).\n\n"
            "First, one question: when do you usually read? For example “10 pm”, “7:30 in the morning”, "
            "“12:30 at lunch”. Each day I'll ask beforehand what you'd like, and have it ready on time.")

    @property
    def read_at(self) -> str | None:
        return self.state.get("read_at")

    def set_reading_time(self, text: str, *, asked: bool = False) -> None:
        when = parse_time(text) if text else None
        if when is None and text and self.client is not None:
            try:
                data = self.client.chat_json(
                    "Extract the time of day the person usually reads. Return JSON {\"time\": \"HH:MM\"} in 24-hour "
                    "time, or {\"time\": null} if there is no time in what they said.", text, max_tokens=60)
                when = parse_time(str(data.get("time") or ""))
            except Exception as err:
                self.log(f"could not read the time: {err}")
        if when is None:
            if not text and self.read_at:
                return self.send(self.t(f"现在是每天 {self.read_at} 读。要改就发 /time 加时间，比如 /time 21:30。",
                                        f"You read at {self.read_at} each day. To change it: /time 21:30"))
            return self.send(self.t("没太听懂几点。告诉我一个时间就行，比如 /time 晚上10点 或者 /time 7:30。",
                                    "I didn't catch the time. Send one, like /time 10pm or /time 7:30."))
        self.state.update(read_at=when)
        self.state.pop("setup", None)
        self.save()
        hh, mm = _hhmm(when)
        ask = (dt.datetime(2000, 1, 1, hh, mm) - dt.timedelta(hours=10)).strftime("%H:%M")
        ready = (dt.datetime(2000, 1, 1, hh, mm) - dt.timedelta(minutes=45)).strftime("%H:%M")
        part = day_part(when)
        self.send(self.t(
            f"好，记下了：每天 {when} 读。\n"
            f"我会在 {ask} 左右问你想读什么；你没说的话，我就按我对你的了解自己挑。"
            f"{ready} 左右把备好的文章发给你，点开就能读。\n"
            + ("读完我跟你说晚安。" if is_bedtime(when) else
               "早上读的话，我就跟你说早上好。" if part == "morning" else "")
            + "\n要改时间，随时发 /time 加时间，比如 /time 21:30。\n\n"
            "现在就想读点什么也行，直接告诉我。",
            f"Got it: you read at {when} every day.\n"
            f"Around {ask} I'll ask what you'd like; if you don't say, I'll choose from what I know about you. "
            f"Around {ready} I'll send the prepared reading, ready to open.\n"
            "To change the time, send /time with a time, like /time 21:30.\n\n"
            "If you'd like something right now, just tell me."))

    def greeting(self) -> str:
        part = day_part(self.read_at or "21:00")
        return self.t({"morning": "早上好！", "noon": "中午好！", "afternoon": "下午好！", "night": "晚上好！"}[part],
                      {"morning": "Good morning!", "noon": "Good afternoon!", "afternoon": "Good afternoon!",
                       "night": "Good evening!"}[part])

    def when_word(self, now: dt.datetime, at: dt.datetime) -> str:
        part = day_part(at.strftime("%H:%M"))
        tomorrow = at.date() > now.date()
        zh = {"morning": "早上", "noon": "中午", "afternoon": "下午", "night": "晚上"}[part]
        if part == "night" and not tomorrow:
            return self.t("今晚", "tonight")
        return self.t(("明天" if tomorrow else "今天") + zh,
                      ("tomorrow " if tomorrow else "this ") + {"morning": "morning", "noon": "lunchtime",
                                                                 "afternoon": "afternoon", "night": "evening"}[part])

    def next_reading(self, now: dt.datetime) -> dt.datetime:
        """The next reading time (today's still counts until two hours after it)."""
        hh, mm = _hhmm(self.read_at)
        at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if at < now - dt.timedelta(hours=2):
            at += dt.timedelta(days=1)
        return at

    def deliver(self, now: dt.datetime, at: dt.datetime) -> None:
        """Before the reading time: a prepared reading, ready to open, or one chosen and prepared now."""
        waiting = books.up_next()
        greet = self.greeting()
        intro = greet + self.t(f"{self.when_word(now, at)}读这篇。", f" Here's your reading for {self.when_word(now, at)}.")
        if waiting is not None:
            how, buttons = self.read_here(waiting)
            return self.send(intro + "\n\n" + self.guide(waiting) + "\n\n" + how, buttons)
        if self.client is None:
            return self.send(greet + self.t("还没有备好的篇目，发我一个链接吧。", " Nothing is prepared yet; send me a link."))
        job = threading.Thread(target=self._choose_and_prepare, args=(greet, intro, now, at), daemon=True,
                               name="bibliothecary-choose")
        self.jobs.append(job)
        job.start()

    def _choose_and_prepare(self, greet: str, intro: str, now: dt.datetime, at: dt.datetime) -> None:
        book = books.current()
        if book is not None:                              # a book is open: tonight is its next part
            return self._book_session(book, intro=greet + self.t(f"{self.when_word(now, at)}接着读《{book.title}》。",
                                                                  f" Tonight we go on with “{book.title}”."))
        task = (f"It is time to choose the reading for {self.when_word(now, at)} ({at:%H:%M}). Using what you know "
                "about the reader and anything they said today, choose ONE piece that suits them, search as "
                "needed, and return it with \"prepare\": \"<url>\" and a short reply saying why this one. "
                "Do not pick something they have already read. If you know nothing about them yet, still "
                "choose one good, broadly interesting piece.")
        try:
            answer = self.desk.reply(task, choose=True)
        except Exception as err:
            self.log(f"choosing a reading failed: {err}")
            return self.send(greet + self.t("今天我没挑成，发我一个链接或者说说想读什么吧。",
                                            " I couldn't choose one today; send me a link or an idea."))
        for line in answer.trace:
            self.log(line)
        if not answer.prepare:
            return self.send(greet + self.t("", " ") + (answer.text or self.t(
                "今天想读点什么？", "What would you like to read today?")))
        self._prepare_now(answer.prepare, intro=intro + ("\n" + answer.text if answer.text else ""))

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
                self.state.update(setup="read_at", introduced=True)
                self.save()
                self.send(self.introduction())
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
        if command == "/time":
            return self.set_reading_time(text[len(text.split()[0]):].strip(), asked=True)
        if self.state.get("setup") == "read_at" and not command and answers_time(text):
            return self.set_reading_time(text)       # the answer to "when do you read?"; anything else is a chat
        if command in ("/start", "/help"):
            return self.send(self.t("发链接或文件给我备课；/tonight 今晚读什么；/records 读过的；/report 最近的读书报告。\n"
                                    "整本书：发 EPUB/TXT/PDF，或 /library 从公版书单里挑；/book 在读的书；/books 书架；/mode 拆书、精华 或 原文；"
                                    "/next 备下一段；/book pause 先放一放。",
                                    "Send a link or file to prepare it. /tonight · /records · /report\n"
                                    "Books: send an EPUB/TXT/PDF, or pick one from /library. /book · /books · /mode digest|excerpts|text · /next · "
                                    "/book pause"))
        if command == "/asbook":
            last = Path(self.state.get("last_file") or "")
            if not last.is_file():
                return self.send(self.t("先把书的文件发给我。", "Send me the book's file first."))
            return self.start_book(last)
        if command in ("/library", "/get"):
            return self.catalog_command(command, text[len(text.split()[0]):].strip())
        if command in ("/book", "/books", "/mode", "/next"):
            return self.book_command(command, text[len(text.split()[0]):].strip())
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
            return self.send(self.t("这种文件我还读不了。发 .txt、.md、.html、.pdf、.epub，或者直接发链接。",
                                    "I can't read that kind of file yet. Send .txt, .md, .html, .pdf, .epub, or a link."))
        inbox = library.home() / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        path = inbox / name
        path.write_bytes(self.bot.download(doc["file_id"]))
        self._remember("reader", f"(file) {name}")
        if name.lower().endswith((".epub", ".txt", ".pdf")) and books.looks_like_book(path):
            return self.start_book(path)
        self.state["last_file"] = str(path)
        self.save()
        if name.lower().endswith((".txt", ".pdf")) and path.stat().st_size > 300_000:
            self.send(self.t("我先当一篇文章备课。如果这其实是一本书，发 /asbook，我按整本书一段一段读。",
                             "I'll prepare it as one article. If it is really a book, send /asbook and I'll read it part by part."))
        self.start_prepare(str(path))

    # ---- whole books -----------------------------------------------------------------
    def _job(self, target, *args) -> None:
        job = threading.Thread(target=target, args=args, daemon=True, name="bibliothecary-book")
        self.jobs.append(job)
        job.start()

    def _bedtime(self) -> bool:
        return self.bedtime and (self.read_at is None or is_bedtime(self.read_at))

    def start_book(self, path: Path) -> None:
        if self.client is None:
            return self.send(self.t("读书需要模型密钥（.env 里的 OPENAI_API_KEY）。", "Books need a model key (OPENAI_API_KEY)."))
        self.send(self.t("收到一本书，我先上架、看看怎么读。", "A book! Let me shelve it and see how to read it."))
        self._job(self._shelve, path)

    def _shelve(self, path: Path) -> None:
        try:
            book = books.add(path, client=self.client, explain=self.explain, log=self.log)
        except Exception as err:
            self.log(f"shelving {path.name} failed: {err}")
            return self.send(self.t(f"这本书我没读进来：{err}", f"I couldn't read that book: {err}"))
        chinese = books.is_chinese(self.explain)
        lines = [books.describe(book, chinese)]
        if book.data.get("why"):
            lines.append(book.data["why"])
        lines.append(self.t("换读法发 /mode 拆书、/mode 精华 或 /mode 原文。我先备第一段，好了告诉你。",
                            "To read it another way: /mode digest, /mode excerpts or /mode text. "
                            "I'm preparing the first part now."))
        self.send("\n".join(lines))
        self._book_session(book)

    def _book_session(self, book, intro: str | None = None) -> None:
        try:
            folder = books.prepare_next(self.client, book, explain=self.explain, bedtime=self._bedtime(),
                                        review=self.review, log=self.log)
        except Exception as err:
            self.log(f"preparing {book.title} failed: {err}")
            return self.send(self.t(f"这一段没备成：{err}", f"I couldn't prepare the next part: {err}"))
        how, buttons = self.read_here(folder)
        with self._lock:
            self.send((intro + "\n\n" if intro else "") + self.guide(folder) + "\n\n" + how, buttons)

    def catalog_command(self, command: str, arg: str) -> None:
        from . import catalog

        chinese = books.is_chinese(self.explain)
        if command == "/library" or not arg:
            return self.send(catalog.listing(chinese) + "\n\n" + self.t(
                "想读哪本就发 /get 加编号，比如 /get darwin-emotions；/get sample 是自带的示例书（塞涅卡《论生命之短暂》）。"
                "都是公版书，从 Standard Ebooks、Project Gutenberg 或维基文库下载。",
                "Send /get with an id, e.g. /get darwin-emotions; /get sample is the bundled sample (Seneca, On the "
                "Shortness of Life). All public domain, fetched from Standard Ebooks, Project Gutenberg or Wikisource."))
        if self.client is None:
            return self.send(self.t("读书需要模型密钥（.env 里的 OPENAI_API_KEY）。", "Books need a model key (OPENAI_API_KEY)."))
        if arg.lower() not in ("sample", "示例", "样书") and catalog.find(arg) is None:
            return self.send(self.t(f"书单里没有“{arg}”。/library 看书单。", f"“{arg}” isn't in the list. /library shows it."))
        self.send(self.t("好，我去取书。", "OK, fetching it."))
        self._job(self._fetch_book, arg)

    def _fetch_book(self, query: str) -> None:
        from . import catalog

        try:
            book = catalog.get(self.client, query, explain=self.explain, log=self.log)
        except Exception as err:
            self.log(f"fetching {query} failed: {err}")
            return self.send(self.t(f"没取到这本：{err}。/library 看书单。", f"I couldn't get that one: {err}. /library lists them."))
        chinese = books.is_chinese(self.explain)
        lines = [books.describe(book, chinese)]
        if book.data.get("why"):
            lines.append(book.data["why"])
        lines.append(self.t("换读法发 /mode 拆书、/mode 精华 或 /mode 原文。我先备第一段。",
                            "To read it another way: /mode digest, /mode excerpts or /mode text. Preparing the first part."))
        self.send("\n".join(lines))
        self._book_session(book)

    def book_command(self, command: str, arg: str) -> None:
        chinese = books.is_chinese(self.explain)
        if command == "/books":
            found = books.shelf()
            if not found:
                return self.send(self.t("书架还是空的。把 EPUB、TXT 或 PDF 发给我就行。",
                                        "The shelf is empty. Send me an EPUB, TXT or PDF."))
            now = books.current()
            names = {"reading": self.t("在读", "reading"), "paused": self.t("放着", "paused"),
                     "finished": self.t("读完", "finished")}
            return self.send("\n".join(("▸ " if now and now.folder == b.folder else "· ")
                                        + f"[{names.get(books.sync(b).data.get('status', 'reading'), '')}] "
                                        + books.describe(b, chinese) for b in found))
        if command == "/book" and arg.split()[:1] in (["pause"], ["暂停"], ["放一放"]):
            book = books.current()
            if book is None:
                return self.send(self.t("现在没有在读的书。", "No book is open right now."))
            books.set_status(book, "paused")
            return self.send(self.t(f"《{book.title}》先放一放，进度都留着。想接着读就发 /book {book.title}。",
                                    f"“{book.title}” is set aside; your place is kept. /book {book.title} to go back."))
        book = books.find(arg) if command == "/book" and arg else books.current()
        if book is None:
            return self.send(self.t("没找到这本书。/books 看书架。" if arg else "现在没有在读的书。把书发给我就行。",
                                    "No such book; /books shows the shelf." if arg else "No book open; send me one."))
        if command == "/book":
            if arg:
                books.set_status(book, "reading")
            books.sync(book)
            return self.send(books.describe(book, chinese))
        if command == "/mode":
            mode = books.mode_of(arg)
            if mode is None:
                return self.send(self.t("读法有三种：/mode 拆书、/mode 精华、/mode 原文。",
                                        "Three ways: /mode digest, /mode excerpts, /mode text."))
            books.set_mode(book, mode)
            self.send(self.t(f"好，《{book.title}》改成「{books.MODE_NAMES[mode][0]}」。我重新备这一段。",
                             f"OK, “{book.title}” is now read as {books.MODE_NAMES[mode][1]}. Preparing this part again."))
            return self._job(self._book_session, book)
        if command == "/next":
            waiting = books.pending(books.sync(book))
            if waiting is not None:                       # the part already prepared comes first
                how, buttons = self.read_here(waiting)
                return self.send(self.t("上一段还没读完，先读这一段：", "The last part isn't finished yet; this one first:")
                                 + "\n\n" + self.guide(waiting) + "\n\n" + how, buttons)
            self.send(self.t("好，我去备下一段。", "OK, preparing the next part."))
            return self._job(self._book_session, book)

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

    def _prepare_now(self, article: str, *, intro: str | None = None) -> None:
        try:
            if self._prepare is not None:
                folder = self._prepare(article)
            else:
                from .prepare import prepare

                bedtime = self.bedtime and (self.read_at is None or is_bedtime(self.read_at))
                folder = prepare(self.client, article, explain=self.explain, bedtime=bedtime,
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
            self.send((intro + "\n\n" if intro else "") + self.guide(folder) + "\n\n" + how, buttons)

    def guide(self, folder: Path) -> str:
        lesson = Lesson.load(folder / "lesson.json")
        preview = [s.say for s in lesson.steps if s.part == "preview" and s.say]
        notes = [s.note for s in lesson.steps if s.note and s.part is None]
        questions = sum(1 for s in lesson.steps if s.expect)
        marker = books.book_of(folder) or {}
        if marker.get("mode") == "text":                 # reading the text itself: notes are glosses, questions open
            lines = [self.t(f"备好了：《{lesson.title}》", f"Ready: “{lesson.title}”")]
            if preview:
                lines += ["", self.t("前情提要：", "Previously:"), *(f"· {p}" for p in preview)]
            lines += ["", self.t(f"这次你自己读原文，我在旁边：难懂的地方有 {len(notes)} 条注释，读完聊 {questions} 个问题，没有标准答案。",
                                 f"You read the text yourself; I'm alongside: {len(notes)} notes where it's hard, "
                                 f"and {questions} open questions at the end.")]
            return "\n".join(lines)
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
        folder = books.up_next()
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
        if not self.state.get("introduced"):             # paired before the introduction existed: once
            self.state.update(setup="read_at", introduced=True)
            self.save()
            self.send(self.introduction())
        now = self.now()
        today, clock = now.date().isoformat(), (now.hour, now.minute)
        late = (min(23, self.decide_at[0] + 3), self.decide_at[1])
        if self.read_at:                                  # the round follows the reader's own reading time
            at = self.next_reading(now)
            key = at.date().isoformat()
            ask, ready = at - dt.timedelta(hours=10), at - dt.timedelta(minutes=45)
            if ask <= now < ready and self.state.get("asked") != key:
                self.send(self.daily_question(self.when_word(now, at)))
                self.state["asked"] = key
                self.save()
            if ready <= now < at + dt.timedelta(hours=2) and self.state.get("decided") != key:
                self.deliver(now, at)
                self.state["decided"] = key
                self.save()
        # each message only within its own window, so starting the bot at midnight sends nothing
        elif self.ask_at <= clock < self.decide_at and self.state.get("asked") != today:
            self.send(self.daily_question())
            self.state["asked"] = today
            self.save()
        if not self.read_at and self.decide_at <= clock < late and self.state.get("decided") != today:
            self.send(*self.tonight())
            self.state["decided"] = today
            self.save()
        sent = set(self.state.get("reported") or [])
        for folder in library.readings():
            if library.status(folder) == "read" and folder.name not in sent:
                if self.state.get("watching"):           # not on the first start: old reports stay put
                    self.send_report(folder)
                sent.add(folder.name)
        if sent != set(self.state.get("reported") or []) or not self.state.get("watching"):
            self.state["reported"], self.state["watching"] = sorted(sent), True
            self.save()

    def daily_question(self, when: str | None = None) -> str:
        when = when or self.t("今晚", "tonight")
        book = books.current()
        if book is not None:                              # a book is open: the day's reading is its next part
            return self.t(f"{when}接着读《{book.title}》（进度 {book.progress()}），到时候我把下一段备好。"
                          "想换别的就告诉我，或者发 /book pause 先放一放。",
                          f"{when.capitalize()} we go on with “{book.title}” ({book.progress()}); I'll have the next "
                          "part ready. Tell me if you'd rather read something else, or /book pause.")
        lines = [self.t(f"{when}想读点什么？", f"What would you like to read {when}?")]
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
        lines.append(self.t("发我一个链接或文件，或者跟我说说想读什么方向；不说的话，到时候我按我对你的了解挑一篇。",
                            "Send me a link or a file, or tell me what you're in the mood for; if you don't, "
                            "I'll choose one from what I know about you."))
        return "\n".join(lines)


# ---- reading time ----------------------------------------------------------------------
_ZH_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
           "十": 10, "十一": 11, "十二": 12}
_PM = re.compile(r"下午|晚上|晚|今晚|夜里|夜|睡前|傍晚|pm|p\.m\.|evening|night|tonight|bed", re.IGNORECASE)
_AM = re.compile(r"早上|早晨|上午|清晨|凌晨|早|am|a\.m\.|morning", re.IGNORECASE)
_NOON = re.compile(r"中午|午休|午饭|noon|lunch", re.IGNORECASE)


def parse_time(text: str) -> str | None:
    """"晚上10点半", "早上7:30", "22:00", "10pm", "睡前" -> "HH:MM" (None when there is no time in it)."""
    t = text.strip().lower()
    m = re.search(r"(\d{1,2})\s*[:：.]\s*(\d{2})", t) or re.search(r"(\d{1,2})\s*(?:点|點|时|時|h\b|o'?clock|am|pm|a\.m|p\.m)", t)
    hour = minute = None
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else 0
    else:
        z = re.search(r"(十[一二]?|[一二两三四五六七八九十])\s*[点點时時]", t)
        if z:
            hour, minute = _ZH_NUM[z.group(1)], 0
    if hour is not None:
        if re.search(r"[点點时時]\s*半|半\b|:30|half", t) and minute == 0:
            minute = 30
        q = re.search(r"[点點时時]\s*(\d{1,2})\s*分?|[点點]\s*(一刻|三刻)", t)
        if q and minute == 0:
            minute = int(q.group(1)) if q.group(1) else (15 if q.group(2) == "一刻" else 45)
        if _NOON.search(t) and hour < 6:
            hour += 12
        elif _PM.search(t) and hour < 12:
            hour += 12
        elif _PM.search(t) and hour == 12 and re.search(r"晚上|夜|midnight|night", t):
            hour = 0                               # "晚上12点" is midnight
        elif not _AM.search(t) and not _NOON.search(t) and 1 <= hour <= 11:
            hour += 12          # a bare "10点": most people read in the evening (the reply says which, to correct)
        if hour == 24:
            hour = 0
        if 0 <= hour < 24 and 0 <= minute < 60:
            return f"{hour:02d}:{minute:02d}"
        return None
    if re.search(r"睡前|before bed|bedtime", t):
        return "22:30"
    if _NOON.search(t):
        return "12:30"
    if _AM.search(t):
        return "07:30"
    if re.search(r"下午|afternoon", t):
        return "15:00"
    if _PM.search(t):
        return "21:30"
    return None


def answers_time(text: str) -> bool:
    """Is this the answer to "when do you read?" (and not a request like "今晚读什么" or a link)?"""
    if URL.search(text) or re.search(r"[?？]|什么|吗|呢|哪|what|which", text, re.IGNORECASE):
        return False
    if parse_time(text) is None:
        return False
    explicit = re.search(r"\d|[一二两三四五六七八九十]\s*[点點时時]", text)
    return bool(explicit) or len(re.sub(r"[\s,，。.!！]|一般|每天|通常|大概|左右|的时候|读|看|书|吧|我|在", "", text)) <= 4


def day_part(hhmm: str) -> str:
    hour = int(hhmm.split(":")[0])
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 13:
        return "noon"
    if 13 <= hour < 18:
        return "afternoon"
    return "night"


def is_bedtime(hhmm: str) -> bool:
    hour = int(hhmm.split(":")[0])
    return hour >= 20 or hour < 4


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
