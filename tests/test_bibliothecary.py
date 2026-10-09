import json
import time
from pathlib import Path

import pytest

from bibliothecary import cli, library, report
from bibliothecary.records import Ledger
from margin import brain
from margin.bus import Bus
from margin.lesson import Lesson, Step
from margin.player import Player

ROOT = Path(__file__).resolve().parents[1]
OCTOPUS = ROOT / "examples" / "octopus.lesson.json"


class QuickVoice:
    name = "quick"

    def __init__(self):
        self.said = []

    def speak(self, text, stop):
        self.said.append(text)
        stop.wait(0.005)


class FakeClient:
    def __init__(self, data):
        self.data, self.calls = data, []

    def chat_json(self, system, user, **_):
        self.calls.append((system, user))
        return self.data


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIBLIOTHECARY_HOME", str(tmp_path / "lib"))
    return tmp_path / "lib"


def _wait(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_three_parts_are_assembled_in_order():
    lesson = Lesson.load(OCTOPUS)
    data = {"preview": [{"say": "Background.", "focus": "p1.s1", "mark": "Octopuses"}],
            "steps": [{"say": "Reading.", "focus": "p1.s1"}],
            "review": [{"question": "Q1?", "answer": "A1"}, {"question": "Q2?", "answer": "A2"}, {"answer": "no q"}],
            "goodbye": "Good night."}
    steps = brain.assemble(lesson, data, review=1)
    assert [(s.part, s.say) for s in steps] == [("preview", "Background."), (None, "Reading."),
                                               ("review", "Q1?"), ("review", "Good night.")]
    assert steps[0].focus is None and steps[0].mark is None      # background is not about one sentence
    assert steps[2].expect == "A1" and steps[3].expect is None
    assert [s.part for s in brain.assemble(lesson, data, preview=False, review=0)] == [None, "review"]


def test_parts_survive_saving(tmp_path):
    lesson = Lesson.load(OCTOPUS)
    lesson.save(tmp_path / "l.json")
    again = Lesson.load(tmp_path / "l.json")
    assert [(s.part, s.expect) for s in again.steps] == [(s.part, s.expect) for s in lesson.steps]
    assert sum(1 for s in again.steps if s.expect) == 2 and again.problems() == []


def test_answer_prompt_knows_the_review_question():
    lesson = Lesson.load(OCTOPUS)
    _system, user = brain._answer_prompt(lesson, "它会变白", None, 3, None, None,
                                        {"question": "两种睡眠有什么不一样？", "expect": "变白；变色"})
    assert "两种睡眠有什么不一样？" in user and "变白；变色" in user


def _session(answer_for_review):
    """Read the octopus lesson; ask one question during the reading, then handle each review question."""
    bus, voice, events = Bus(), QuickVoice(), []
    seen_reviews = []

    def answerer(lesson, question, current, position=None, history=None, review=None):
        seen_reviews.append(review)
        if question == "go on":
            return {"steps": [], "then": "continue"}
        return {"steps": [Step(say=f"answer to {question}")], "then": "continue"}

    player = Player(bus, voice, answerer, record=lambda kind, **data: events.append((kind, data)))
    lesson = Lesson.load(OCTOPUS)
    player.load(lesson)
    player.play()
    first_review = next(i for i, s in enumerate(lesson.steps) if s.expect)
    assert _wait(lambda: player.index >= 6)
    player.ask("why pale?")
    for n in range(2):
        asked = lesson.steps[first_review + n].say
        assert _wait(lambda q=asked: (player.review or {}).get("question") == q), n
        assert _wait(lambda: bus.screen()["screen"]["status"] == "waiting"), n
        player.ask(answer_for_review(n))
        assert _wait(lambda n=n: sum(1 for _k, d in events if d.get("review")) == n + 1)
    assert _wait(lambda: bus.screen()["screen"]["status"] == "done")
    assert _wait(lambda: events and events[-1][0] == "end")
    return lesson, events, seen_reviews


def test_player_waits_for_review_answers_and_records_everything():
    lesson, events, seen = _session(lambda n: f"my answer {n}")
    kinds = [k for k, _ in events]
    assert kinds == ["start", "exchange", "exchange", "exchange", "end"]
    question = events[1][1]
    assert question["question"] == "why pale?" and question["answer"] == "answer to why pale?"
    assert question["review"] is None
    review = events[2][1]
    assert review["question"] == "my answer 0" and review["review"].startswith("讲完了")
    assert review["expect"] == lesson.steps[next(i for i, s in enumerate(lesson.steps) if s.expect)].expect
    assert seen[0] is None and seen[1]["question"].startswith("讲完了")   # the answerer gets the review context


def test_saying_go_on_skips_a_review_question():
    _lesson, events, _ = _session(lambda n: "go on" if n == 0 else "my answer")
    kinds = [k for k, _ in events]
    assert kinds == ["start", "exchange", "review_skipped", "exchange", "end"]


def test_ledger_and_report(home):
    lesson = Lesson.load(OCTOPUS)
    folder = library.new_reading(lesson)
    assert library.status(folder) == "prepared" and library.next_unread() == folder
    prepared = report.write(folder).read_text(encoding="utf-8")
    assert "## 导读：读之前要知道的" in prepared and "色素细胞" in prepared
    assert "## 要点笔记" in prepared and "> A resting octopus turns pale" in prepared
    assert "今晚读完以后" in prepared and "status: \"prepared\"" in prepared

    ledger = Ledger(folder, lesson)
    q1, q2 = [s for s in lesson.steps if s.expect]
    ledger.record("start", lesson=lesson)
    ledger.record("exchange", question="为什么会变白？", answer="色素细胞收起来了。", focus="p1.s3")
    assert library.status(folder) == "started"
    ledger.record("exchange", question="一个变白一个变色", answer="对，还有眼睛会动。", focus=None,
                  review=q1.say, expect=q1.expect)
    ledger.record("review_skipped", review=q2.say, expect=q2.expect)
    ledger.record("end")
    assert library.status(folder) == "read" and library.next_unread() is None

    text = (folder / "report.md").read_text(encoding="utf-8")
    assert "**我：** 为什么会变白？" in text and "**图书管理员：** 色素细胞收起来了。" in text
    assert "> A resting octopus turns pale, its pupils narrow to thin slits, and it stops moving." in text
    assert "**我的回答：** 一个变白一个变色" in text and "**我的回答：** （跳过了）" in text
    assert f"**参考答案：** {q2.expect}" in text
    assert "questions: 1" in text and 'review: "1/2"' in text and "## 我还没弄懂的" in text
    lines = (folder / "session.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["kind"] for line in lines] == ["start", "exchange", "exchange", "review_skipped", "end"]


def test_report_summary_sits_next_to_the_verbatim_record(home):
    lesson = Lesson.load(OCTOPUS)
    folder = library.new_reading(lesson)
    ledger = Ledger(folder, lesson)
    ledger.record("start", lesson=lesson)
    ledger.record("exchange", question="章鱼会做梦吗？", answer="没人知道。", focus="p6.s1")
    client = FakeClient({"unclear": ["做梦和活跃睡眠的关系"], "threads": ["乌贼也有活跃睡眠吗"],
                         "concepts": ["活跃睡眠", "伪装"]})
    text = report.write(folder, client=client).read_text(encoding="utf-8")
    assert "- 做梦和活跃睡眠的关系" in text and "- 乌贼也有活跃睡眠吗" in text
    assert 'concepts: ["活跃睡眠", "伪装"]' in text and "**我：** 章鱼会做梦吗？" in text
    assert "章鱼会做梦吗？" in client.calls[0][1]
    again = report.write(folder).read_text(encoding="utf-8")   # no model now: the kept summary is reused
    assert "- 乌贼也有活跃睡眠吗" in again


def test_english_report_and_a_cut_off_log_line(home):
    lesson = Lesson.load(ROOT / "examples" / "village.lesson.json")
    lesson.explain_language = "English"
    folder = library.new_reading(lesson)
    Ledger(folder, lesson).record("start", lesson=lesson)
    with open(folder / "session.jsonl", "a", encoding="utf-8") as f:
        f.write('{"t": "2026-10-08T22:0')                     # the laptop closed mid-write
    text = report.write(folder).read_text(encoding="utf-8")
    assert "## What I asked and what it answered (verbatim)" in text and "No questions this time." in text


def test_cli_files_lists_and_rewrites(home, capsys):
    lesson = Lesson.load(OCTOPUS)
    folder = library.new_reading(lesson)
    assert library.new_reading(lesson).name.endswith("-2")       # same title, same day: a second folder
    assert cli.main(["report", folder.name, "--no-summary"]) == 0
    assert (folder / "report.md").is_file()
    assert cli.main(["records"]) == 0
    out = capsys.readouterr().out
    assert "2 readings" in out and "prepared" in out and lesson.title in out
    with pytest.raises(SystemExit):
        cli.main(["report", "no-such-reading"])


def test_slug_keeps_chinese_titles():
    assert library.slug("What an Octopus Does in Its Sleep") == "what-an-octopus-does-in-its-sleep"
    assert library.slug("章鱼怎么睡觉？") == "章鱼怎么睡觉"
    assert library.slug("???") == "reading"


def test_build_lesson_asks_for_three_parts():
    client = FakeClient({"preview": [{"say": "背景。"}], "steps": [{"say": "正文。", "focus": "p1.s1"}],
                         "review": [{"question": "问题？", "answer": "答案。"}], "goodbye": "晚安。"})
    lesson = brain.build_lesson(client, "T", "First sentence here. Second one.\n\nThird.",
                                explain_language="Simplified Chinese", bedtime=True, review=2,
                                known="REM sleep")
    system = client.calls[0][0]
    assert '"preview"' in system and "2 questions" in system and "good night" in system
    assert "already understands: REM sleep" in system
    assert [s.part for s in lesson.steps] == ["preview", None, "review", "review"]
    brain.build_lesson(client, "T", "One.", preview=False, review=0)
    assert "0 step objects" in client.calls[1][0] and "0 questions" in client.calls[1][0]


def test_plain_string_parts_are_kept():
    # a real model wrote the preview as plain sentences, which used to be dropped
    lesson = Lesson.load(OCTOPUS)
    steps = brain.assemble(lesson, {"preview": ["逃逸速度超过光速。", "事件视界是一条边界。"],
                                    "steps": ["正文。"], "review": ["什么是事件视界？"]})
    assert [(s.part, s.say) for s in steps] == [("preview", "逃逸速度超过光速。"), ("preview", "事件视界是一条边界。"),
                                               (None, "正文。"), ("review", "什么是事件视界？")]


def test_web_page_keeps_only_the_article():
    from margin.ingest import from_html

    article = " ".join(f"Black holes bend light and time in sentence number {i}." for i in range(40))
    page = f"""<html><head><title>Black Holes - NASA Science</title></head><body>
      <nav><ul><li>Missions</li><li>Humans in Space</li><li>Learning Resources for Students</li></ul></nav>
      <main><article><h1>Black Holes</h1><p>{article}</p><p>{article}</p></article></main>
      <footer><p>NASA Opens Applications for Next Class of Flight Directors and more news</p></footer>
    </body></html>"""
    title, text = from_html(page)
    assert title == "Black Holes"
    assert "Missions" not in text and "Flight Directors" not in text and "sentence number 39" in text
    assert not text.startswith("Black Holes")          # the title is not read twice


def test_reasoning_models_get_room_to_think(monkeypatch):
    from margin import llm

    client = llm.OpenAICompatible(api_key="k", model="gpt-5-mini")
    sent = []
    replies = [{"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
               {"choices": [{"message": {"content": '{"reply": "好"}'}, "finish_reason": "stop"}]}]
    monkeypatch.setattr(client, "_post", lambda path, body, kind: (sent.append(json.loads(body)),
                                                                     json.dumps(replies[len(sent) - 1]).encode())[1])
    assert client.chat_json("s", "u", max_tokens=600) == {"reply": "好"}
    assert sent[0]["max_completion_tokens"] == 600 + llm.REASONING_ALLOWANCE
    assert "max_completion_tokens" not in sent[1]                # an empty, cut-off reply is asked again
    assert "reasoning_effort" not in sent[0]
    assert client._body("s", "u", "gpt-4.1-mini", 600)["max_completion_tokens"] == 600
    assert llm.reasons("o3-mini") and llm.reasons("openai/gpt-5") and not llm.reasons("gpt-4o-mini")


def test_ask_me_again_goes_back_to_the_review_questions():
    assert brain.quick_intent("能不能重新问我一遍那三个问题") == "review"
    assert brain.quick_intent("再问一遍") == "review"
    assert brain.quick_intent("ask me again") == "review"
    assert brain.quick_intent("你卡了刷新一下页面") == "refresh"
    bus, voice, events = Bus(), QuickVoice(), []

    def answerer(lesson, question, current, position=None, history=None, review=None):
        command = brain.quick_intent(question)
        if command:
            return {"steps": [], "then": command}
        return {"steps": [Step(say=f"answer to {question}")], "then": "continue"}

    player = Player(bus, voice, answerer, record=lambda kind, **data: events.append((kind, data)))
    lesson = Lesson.load(OCTOPUS)
    player.load(lesson)
    player.play()
    first = next(i for i, s in enumerate(lesson.steps) if s.expect)
    for n in range(2):
        asked = lesson.steps[first + n].say
        assert _wait(lambda q=asked: (player.review or {}).get("question") == q), n
        player.ask(f"my answer {n}")
        assert _wait(lambda n=n: sum(1 for _k, d in events if d.get("review")) == n + 1)
    assert _wait(lambda: bus.screen()["screen"]["status"] == "done")
    player.ask("再问一遍")
    assert _wait(lambda: (player.review or {}).get("question") == lesson.steps[first].say)
    assert _wait(lambda: bus.screen()["screen"]["status"] == "waiting")
