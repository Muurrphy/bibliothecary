import datetime as dt
import json
from pathlib import Path

import pytest

from bibliothecary import library, report, telegram
from bibliothecary.records import Ledger
from margin.lesson import Lesson

ROOT = Path(__file__).resolve().parents[1]
OCTOPUS = ROOT / "examples" / "octopus.lesson.json"
ME, STRANGER = 111, 999


class FakeBot:
    def __init__(self):
        self.sent, self.files, self.downloads = [], [], {}

    def send(self, chat, text):
        self.sent.append((chat, text))

    def send_file(self, chat, path, caption=""):
        self.files.append((chat, Path(path).name, caption))

    def typing(self, chat):
        pass

    def download(self, file_id):
        return self.downloads[file_id]


class FakeClient:
    def __init__(self, reply="今晚读读章鱼？"):
        self.reply, self.prompts = reply, []

    def chat_json(self, system, user, **_):
        self.prompts.append((system, user))
        return {"reply": self.reply}

    def transcribe(self, audio, **_):
        return audio.decode()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIBLIOTHECARY_HOME", str(tmp_path / "lib"))
    return tmp_path / "lib"


def message(chat, text=None, **extra):
    return {"update_id": 1, "message": {"chat": {"id": chat}, **({"text": text} if text else {}), **extra}}


def paired(clock="2026-10-08T10:00", **kw):
    bot, prepared = FakeBot(), []

    def prepare(article):
        prepared.append(article)
        folder = library.new_reading(Lesson.load(OCTOPUS))
        report.write(folder)
        return folder

    now = dt.datetime.fromisoformat(clock)
    lib = telegram.Librarian(bot, kw.pop("client", FakeClient()), explain="Simplified Chinese",
                             prepare=prepare, now=lambda: now, **kw)
    lib.handle(message(ME, f"/start {lib.pairing_code()}"))
    bot.sent.clear()
    return lib, bot, prepared


def test_only_the_paired_reader_is_answered(home):
    bot = FakeBot()
    lib = telegram.Librarian(bot, FakeClient(), explain="Simplified Chinese")
    code = lib.pairing_code()
    lib.handle(message(STRANGER, "/start 000000"))
    lib.handle(message(STRANGER, "hello"))
    assert bot.sent == [] and lib.owner is None
    lib.handle(message(ME, f"/start {code}"))
    assert lib.owner == ME and "图书管理员" in bot.sent[0][1] and "Telegram 的服务器" in bot.sent[0][1]
    lib.handle(message(STRANGER, f"/start {code}"))
    lib.handle(message(STRANGER, "what does Murphy read?"))
    assert all(chat == ME for chat, _ in bot.sent)
    again = telegram.Librarian(FakeBot(), None)            # the pairing survives a restart
    assert again.owner == ME


def test_a_link_is_prepared_and_the_guide_sent_back(home):
    lib, bot, prepared = paired()
    lib.handle(message(ME, "今晚读这个 https://science.nasa.gov/universe/black-holes/。"))
    for job in lib.jobs:
        job.join(5)
    assert prepared == ["https://science.nasa.gov/universe/black-holes/"]
    assert "备课" in bot.sent[0][1]
    guide = bot.sent[-1][1]
    assert "备好了" in guide and "色素细胞" in guide and "2 个问题" in guide and "biblio read" in guide


def test_a_file_is_saved_locally_and_prepared(home):
    lib, bot, prepared = paired()
    bot.downloads["f1"] = b"# Title\n\nSome text."
    lib.handle(message(ME, document={"file_id": "f1", "file_name": "black-holes.md"}))
    for job in lib.jobs:
        job.join(5)
    assert prepared == [str(home / "inbox" / "black-holes.md")]
    assert (home / "inbox" / "black-holes.md").read_bytes() == b"# Title\n\nSome text."
    lib.handle(message(ME, document={"file_id": "f2", "file_name": "slides.pptx"}))
    assert "读不了" in bot.sent[-1][1]


def test_talking_uses_the_records_and_voice_is_heard(home):
    folder = library.new_reading(Lesson.load(OCTOPUS))
    (folder / "summary.json").write_text(json.dumps({"unclear": ["活跃睡眠和做梦的关系"], "threads": ["乌贼睡觉"]}),
                                         encoding="utf-8")
    client = FakeClient("要不要接着读章鱼？")
    lib, bot, _ = paired(client=client)
    lib.handle(message(ME, voice={"file_id": "v1", "mime_type": "audio/ogg"}))   # nothing to download yet
    bot.downloads["v1"] = "想读点动物的".encode()
    lib.handle(message(ME, voice={"file_id": "v1", "mime_type": "audio/ogg"}))
    assert bot.sent[-1][1] == "要不要接着读章鱼？"
    system, context = client.prompts[-1]
    assert "Simplified Chinese" in system and "invent one" in system
    assert "What an Octopus Does in Its Sleep" in context and "乌贼睡觉" in context
    assert "Reader: 想读点动物的" in context
    log = (home / "chat.jsonl").read_text(encoding="utf-8")
    assert "想读点动物的" in log and "要不要接着读章鱼？" in log


def test_commands(home):
    lib, bot, _ = paired()
    lib.handle(message(ME, "/tonight"))
    assert "还没有要读的" in bot.sent[-1][1]
    library.new_reading(Lesson.load(OCTOPUS))
    lib.handle(message(ME, "/tonight"))
    assert "今晚读《What an Octopus Does in Its Sleep》" in bot.sent[-1][1]
    lib.handle(message(ME, "/records"))
    assert "待读" in bot.sent[-1][1]
    lib.handle(message(ME, "/report"))
    assert "还没有读完" in bot.sent[-1][1]


def test_the_daily_round(home):
    lib, bot, _ = paired(clock="2026-10-08T09:00")
    lib.tick()
    assert bot.sent == []                                  # too early
    lib.now = lambda: dt.datetime.fromisoformat("2026-10-08T12:05")
    lib.tick()
    lib.tick()
    assert [t for _, t in bot.sent].count(bot.sent[0][1]) == 1 and "今晚想读点什么" in bot.sent[0][1]
    library.new_reading(Lesson.load(OCTOPUS))
    lib.now = lambda: dt.datetime.fromisoformat("2026-10-08T19:00")
    lib.tick()
    assert "今晚读《What an Octopus" in bot.sent[-1][1]
    lib.now = lambda: dt.datetime.fromisoformat("2026-10-09T23:30")     # started late at night: nothing is sent
    count = len(bot.sent)
    lib.tick()
    assert len(bot.sent) == count


def test_a_finished_session_sends_its_report_once(home):
    lesson = Lesson.load(OCTOPUS)
    old = library.new_reading(lesson)
    Ledger(old, lesson).record("end")                     # read before the bot existed
    lib, bot, _ = paired(clock="2026-10-08T08:00")
    lib.tick()
    assert bot.files == []                                 # old reports are not re-sent
    folder = library.new_reading(lesson)
    ledger = Ledger(folder, lesson)
    ledger.record("start", lesson=lesson)
    ledger.record("exchange", question="会做梦吗？", answer="没人知道。", focus="p6.s1")
    lib.tick()
    assert bot.files == []                                 # not finished yet
    ledger.record("end")
    lib.tick()
    lib.tick()
    assert bot.files == [(ME, "report.md", "《What an Octopus Does in Its Sleep》的读书报告。今晚你问了 1 个问题。")]


def test_long_messages_are_split():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(200))
    pieces = telegram.split(text)
    assert len(pieces) > 1 and all(len(p) <= 3900 for p in pieces)
    assert "\n".join(pieces).replace("\n", "") == text.replace("\n", "")


def test_bot_speaks_the_bot_api(tmp_path):
    import http.server
    import threading

    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            seen.append((self.path, self.headers["Content-Type"], body))
            method = self.path.rsplit("/", 1)[-1]
            result = {"getFile": {"file_path": "voice/1.ogg"}}.get(method, True)
            ok = method != "sendSticker"
            self._reply({"ok": ok, "result": result, "description": "Bad Request: nope"}, 200 if ok else 400)

        def do_GET(self):
            seen.append((self.path, None, b""))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OGG")

        def _reply(self, data, code):
            raw = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        bot = telegram.Bot("T0KEN", timeout=5)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        bot.base, bot.files = f"{base}/botT0KEN", f"{base}/file/botT0KEN"
        bot.send(ME, "你好")
        path, kind, body = seen[-1]
        assert path == "/botT0KEN/sendMessage" and json.loads(body)["text"] == "你好"
        report_file = tmp_path / "report.md"
        report_file.write_text("# 报告\n", encoding="utf-8")
        bot.send_file(ME, report_file, "caption")
        path, kind, body = seen[-1]
        assert path.endswith("/sendDocument") and kind.startswith("multipart/form-data")
        assert 'filename="report.md"' in body.decode() and "# 报告" in body.decode()
        assert bot.download("abc") == b"OGG" and seen[-1][0] == "/file/botT0KEN/voice/1.ogg"
        with pytest.raises(telegram.TelegramError, match="nope"):
            bot.call("sendSticker", chat_id=ME)
    finally:
        server.shutdown()


def test_a_rehearsed_demo_goes_the_same_way_every_take(home):
    lib, bot, prepared = paired()
    folder = library.new_reading(Lesson.load(OCTOPUS))
    (home / "demo.json").write_text(json.dumps({"next": 0, "steps": [
        {"reply": "你好，今晚想读什么？"},
        {"reply": "好，就准备这篇。", "open": folder.name}]}, ensure_ascii=False), encoding="utf-8")
    lib.handle(message(ME, "随便打的字"))
    assert bot.sent[-1][1] == "你好，今晚想读什么？"
    lib.handle(message(ME, "好"))
    assert bot.sent[-2][1] == "好，就准备这篇。" and bot.sent[-1][1].startswith("备好了") and prepared == []
    assert json.loads((home / "demo.json").read_text(encoding="utf-8"))["next"] == 2


def test_an_empty_account_is_named_not_called_a_connection_problem(home):
    class Broke(FakeClient):
        def chat_json(self, system, user, **_):
            raise RuntimeError('429 from /chat/completions: {"code": "credit_balance_exhausted", "type": "insufficient_quota"}')

    lib, bot, _ = paired(client=Broke())
    lib.handle(message(ME, "今晚读什么"))
    assert "余额用完" in bot.sent[-1][1]


def test_on_pairing_it_introduces_itself_and_asks_when_you_read(home):
    bot = FakeBot()
    lib = telegram.Librarian(bot, FakeClient(), explain="Simplified Chinese")
    lib.handle(message(ME, f"/start {lib.pairing_code()}"))
    intro = bot.sent[-1][1]
    assert "私人图书管理员" in intro and "OpenAlex" in intro and "批注" in intro and "什么时候读" in intro
    lib.handle(message(ME, "今晚读什么"))                  # not an answer to the question: a normal chat
    assert lib.read_at is None
    lib.handle(message(ME, "一般晚上10点半"))
    assert lib.read_at == "22:30" and "晚安" in bot.sent[-1][1] and "/time" in bot.sent[-1][1]
    lib.handle(message(ME, "/time 早上7点"))
    assert lib.read_at == "07:00" and "早上好" in bot.sent[-1][1]


def test_reading_times_are_understood():
    p = telegram.parse_time
    assert [p("晚上10点"), p("早上7点半"), p("22:15"), p("10pm"), p("睡前"), p("午休12点半"), p("九点半"),
            p("晚上12点"), p("明天再说")] == ["22:00", "07:30", "22:15", "22:00", "22:30", "12:30", "21:30",
                                              "00:00", None]


def test_the_round_follows_an_evening_readers_time(home):
    lib, bot, _ = paired(clock="2026-10-08T09:00")
    lib.state["read_at"] = "22:00"
    lib.tick()
    assert bot.sent == []                                  # before 12:00 nothing yet
    lib.now = lambda: dt.datetime.fromisoformat("2026-10-08T12:30")
    lib.tick()
    lib.tick()
    assert sum("今晚想读点什么" in t for _, t in bot.sent) == 1
    library.new_reading(Lesson.load(OCTOPUS))
    lib.now = lambda: dt.datetime.fromisoformat("2026-10-08T21:20")
    lib.tick()
    lib.tick()
    delivered = [t for _, t in bot.sent if "今晚读这篇" in t]
    assert len(delivered) == 1 and delivered[0].startswith("晚上好！") and "备好了" in delivered[0]


def test_a_morning_reader_is_asked_the_evening_before_and_greeted_in_the_morning(home):
    lib, bot, _ = paired(clock="2026-10-08T21:40")
    lib.state["read_at"] = "07:30"
    lib.tick()
    assert "明天早上想读点什么" in bot.sent[-1][1]
    library.new_reading(Lesson.load(OCTOPUS))
    lib.now = lambda: dt.datetime.fromisoformat("2026-10-09T06:50")
    lib.tick()
    assert bot.sent[-1][1].startswith("早上好！今天早上读这篇。")


def test_someone_paired_before_the_introduction_gets_it_once(home):
    lib, bot, _ = paired(clock="2026-10-08T09:00")
    lib.state.pop("introduced")
    lib.tick()
    lib.tick()
    assert sum("私人图书管理员" in t for _, t in bot.sent) == 1 and lib.state["setup"] == "read_at"
