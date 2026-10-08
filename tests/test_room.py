import argparse
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from bibliothecary import library, telegram
from bibliothecary.room import ReadingRoom
from margin import cli as margin_cli
from margin.lesson import Lesson

ROOT = Path(__file__).resolve().parents[1]
OCTOPUS = ROOT / "examples" / "octopus.lesson.json"
VILLAGE = ROOT / "examples" / "village.lesson.json"
ME = 111


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIBLIOTHECARY_HOME", str(tmp_path / "lib"))
    monkeypatch.setenv("MARGIN_REALTIME", "0")
    return tmp_path / "lib"


@pytest.fixture
def room(home):
    parser = argparse.ArgumentParser()
    margin_cli.add_serve_options(parser)
    args = parser.parse_args(["--host", "127.0.0.1", "--port", str(free_port()), "--https-port", "0"])
    reading_room = ReadingRoom(args, None)
    yield reading_room
    reading_room.close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def test_one_phone_reads_and_a_link_opens_the_reading(room):
    octopus = library.new_reading(Lesson.load(OCTOPUS))
    base = "http://127.0.0.1:" + room.room.urls["base"].rsplit(":", 1)[1]
    page = urllib.request.urlopen(base + "/phone").read().decode()
    assert 'src="/reader?phone=1"' in page and 'allow="microphone; autoplay"' in page
    assert room.link(octopus).endswith("/open/" + octopus.name)
    opener = urllib.request.build_opener(NoRedirect)
    with pytest.raises(urllib.error.HTTPError) as answer:
        opener.open(base + "/open/" + octopus.name)
    assert answer.value.code == 303 and answer.value.headers["Location"] == "/phone"
    assert room.folder == octopus
    end = time.time() + 3
    while time.time() < end and (room.room.player.lesson is None):
        time.sleep(0.02)
    assert room.room.player.lesson.title == "What an Octopus Does in Its Sleep"
    with pytest.raises(urllib.error.HTTPError) as missing:
        urllib.request.urlopen(base + "/open/..%2F..%2Fetc")
    assert missing.value.code == 404


def test_switching_readings_files_the_last_one(room):
    octopus = library.new_reading(Lesson.load(OCTOPUS))
    village = library.new_reading(Lesson.load(VILLAGE))
    assert room.open(octopus.name) and room.open(octopus.name)          # opening it again changes nothing
    first = room.ledger
    room.room.player._note("exchange", question="会做梦吗？", answer="没人知道。", focus=None)
    assert room.open(village.name) and room.ledger is not first
    end = time.time() + 3
    while time.time() < end and "会做梦吗" not in (octopus / "report.md").read_text(encoding="utf-8"):
        time.sleep(0.02)
    assert "会做梦吗" in (octopus / "report.md").read_text(encoding="utf-8")   # filed when it was left
    assert (village / "report.md").is_file()
    assert not room.open("no-such-reading")


class FakeBot:
    def __init__(self):
        self.sent = []

    def send(self, chat, text, buttons=None):
        self.sent.append((text, buttons))

    def typing(self, chat):
        pass


def test_the_chat_gives_a_button_that_opens_the_reading(room):
    bot = FakeBot()

    def prepare(article):
        return library.new_reading(Lesson.load(OCTOPUS))

    lib = telegram.Librarian(bot, None, explain="Simplified Chinese", prepare=prepare, room=room)
    lib.handle({"message": {"chat": {"id": ME}, "text": f"/start {lib.pairing_code()}"}})
    lib.handle({"message": {"chat": {"id": ME}, "text": "https://example.org/octopus"}})
    for job in lib.jobs:
        job.join(5)
    text, buttons = bot.sent[-1]
    assert text.startswith("备好了") and room.kindle in text and "同一个 Wi-Fi" in text
    assert buttons == [("📖 在手机上读", room.link(room.folder))]          # and it is already open for the Kindle
    lib.handle({"message": {"chat": {"id": ME}, "text": "/tonight"}})
    text, buttons = bot.sent[-1]
    assert "今晚读《What an Octopus" in text and buttons[0][1].endswith("/open/" + room.folder.name)


def test_a_refused_button_becomes_a_plain_link(monkeypatch):
    bot = telegram.Bot("T")
    calls = []

    def call(method, **params):
        calls.append(params)
        if "reply_markup" in params:
            raise telegram.TelegramError("sendMessage: Bad Request: BUTTON_URL_INVALID")

    monkeypatch.setattr(bot, "call", call)
    bot.send(ME, "备好了", [("📖 在手机上读", "http://192.168.1.5:8765/open/x")])
    assert "reply_markup" in calls[0] and calls[1]["text"].endswith("📖 在手机上读: http://192.168.1.5:8765/open/x")
