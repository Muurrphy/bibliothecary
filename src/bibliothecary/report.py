"""The reading report: one Markdown file per reading, for people and for agents.

Written in two stages. Before the session (``prepare``) it holds the guide: the
background and the notes. After the session it adds every question and answer
verbatim, the review questions with your answers, and, when a model is
available, a short account of what is still unclear and which threads are worth
following. Summaries never replace the verbatim record; they sit next to it.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from margin.lesson import Lesson

from . import library

ZH = {
    "source": "来源", "guide": "导读：读之前要知道的", "notes": "要点笔记",
    "asked": "我问了什么、它怎么答（逐条原文）", "review": "复习提问和我的回答",
    "unclear": "我还没弄懂的", "threads": "值得追的线索",
    "me": "我", "librarian": "图书管理员", "my_answer": "我的回答", "reference": "参考答案",
    "skipped": "（跳过了）", "at": "讲到", "none_asked": "这次没有提问。",
    "later": "今晚读完以后，这里会补上问答和复习。", "no_summary": "（还没有生成：需要一个可用的模型，之后可以运行 `biblio report` 补上。）",
}
EN = {
    "source": "Source", "guide": "Before you read: background", "notes": "Notes on the main points",
    "asked": "What I asked and what it answered (verbatim)", "review": "Review questions and my answers",
    "unclear": "What I still don't understand", "threads": "Threads worth following",
    "me": "Me", "librarian": "Librarian", "my_answer": "My answer", "reference": "A good answer",
    "skipped": "(skipped)", "at": "at", "none_asked": "No questions this time.",
    "later": "After tonight's reading, the questions and the review are added here.",
    "no_summary": "(Not written yet: it needs a model. Run `biblio report` later to add it.)",
}

SUMMARY_SYSTEM = """You keep a reader's reading reports. Below are an article, the explanation they heard,
and everything they asked and answered. Return JSON, written in {explain}:
{{"unclear": [...], "threads": [...], "concepts": [...]}}
"unclear": things they still seem not to understand, judging from their questions and review answers
  (0-4 short items; [] if nothing suggests it). Do not invent doubts they did not show.
"threads": questions or topics worth reading about next, grown from what they asked (0-4 short items).
"concepts": the 3-8 key concepts this reading was about, as short noun phrases."""


def chinese(language: str) -> bool:
    lang = (language or "").lower()
    return "chin" in lang or lang.startswith("zh") or "中文" in lang


def _clock(stamp: str) -> str:
    return stamp[11:16] if len(stamp) >= 16 else stamp


def _yaml_value(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in value) + "]"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _quote(text: str) -> str:
    return "\n".join("> " + line for line in text.splitlines() or [""])


def render(lesson: Lesson, events: list[dict], *, prepared: dt.date | None = None,
           summary: dict | None = None) -> str:
    words = ZH if chinese(lesson.explain_language) else EN
    colon = "：" if words is ZH else ":"
    starts = [e for e in events if e.get("kind") == "start"]
    exchanges = [e for e in events if e.get("kind") == "exchange" and not e.get("review")]
    reviews = [e for e in events if e.get("review") and e.get("kind") in ("exchange", "review_skipped")]
    read = bool(starts)
    day = starts[0]["t"][:10] if read else (prepared or library.today()).isoformat()
    minutes = 0
    if read and len(events) > 1:
        first, last = dt.datetime.fromisoformat(starts[0]["t"]), dt.datetime.fromisoformat(events[-1]["t"])
        minutes = max(0, round((last - first).total_seconds() / 60))
    asked = [s for s in lesson.steps if s.expect]
    answered = sum(1 for e in reviews if e.get("kind") == "exchange")

    head = {"date": day, "title": lesson.title, "source": lesson.source, "language": lesson.language,
            "explain_language": lesson.explain_language,
            "status": ("read" if any(e.get("kind") == "end" for e in events) else "started") if read else "prepared"}
    if read:
        head.update(minutes=minutes, questions=len(exchanges), review=f"{answered}/{len(asked)}")
    if summary and summary.get("concepts"):
        head["concepts"] = list(summary["concepts"])
    out = ["---", *(f"{k}: {_yaml_value(v)}" for k, v in head.items() if v not in ("", None)), "---", "",
           f"# {day} · {lesson.title}", ""]
    if lesson.source:
        out += [f"{words['source']}{colon}{lesson.source}" if words is ZH else f"{words['source']}: {lesson.source}", ""]

    preview = [s.say for s in lesson.steps if s.part == "preview" and s.say]
    if preview:
        out += [f"## {words['guide']}", "", *(f"- {say}" for say in preview), ""]

    notes = []
    for step in lesson.steps:
        if step.note and step.part is None:
            line = f"- {step.note}"
            if step.focus:
                try:
                    line += f"\n  {_quote(lesson.sentence(step.focus))}"
                except KeyError:
                    pass
            notes.append(line)
    if notes:
        out += [f"## {words['notes']}", "", *notes, ""]

    if not read:
        out += [f"_{words['later']}_", ""]
        return "\n".join(out)

    out += [f"## {words['asked']}", ""]
    if not exchanges:
        out += [words["none_asked"], ""]
    for n, e in enumerate(exchanges, 1):
        where = f" · {words['at']} {e['focus']}" if e.get("focus") else ""
        out += [f"### {n}. {_clock(e['t'])}{where}", ""]
        if e.get("sentence"):
            out += [_quote(e["sentence"]), ""]
        out += [f"**{words['me']}{colon}** {e['question']}", "", f"**{words['librarian']}{colon}** {e['answer']}", ""]

    if asked:
        out += [f"## {words['review']}", ""]
        by_question = {}
        for e in reviews:
            by_question.setdefault(e["review"], e)
        for n, step in enumerate(asked, 1):
            out += [f"### {n}. {step.say}", ""]
            e = by_question.get(step.say)
            if e and e.get("kind") == "exchange":
                out += [f"**{words['my_answer']}{colon}** {e['question']}", ""]
                if e["answer"] != step.expect:          # without a model the reply is the good answer itself
                    out += [f"**{words['librarian']}{colon}** {e['answer']}", ""]
            else:
                out += [f"**{words['my_answer']}{colon}** {words['skipped']}", ""]
            out += [f"**{words['reference']}{colon}** {step.expect}", ""]

    for key in ("unclear", "threads"):
        out += [f"## {words[key]}", ""]
        if summary is None:
            out += [f"_{words['no_summary']}_", ""]
        else:
            out += [f"- {item}" for item in summary.get(key) or []] or ["-"]
            out.append("")
    return "\n".join(out)


def summarize(client, lesson: Lesson, events: list[dict]) -> dict:
    talk = "\n".join(f"- {s.say}" for s in lesson.steps if s.say)
    said = "\n".join(
        (f"- Review question: {e['review']}\n  Their answer: {e.get('question', '(skipped)')}"
         if e.get("review") else f"- They asked: {e['question']}\n  Answer: {e['answer']}")
        for e in events if e.get("kind") in ("exchange", "review_skipped"))
    data = client.chat_json(SUMMARY_SYSTEM.format(explain=lesson.explain_language),
                            f"{lesson.context()}\n\nWhat they heard:\n{talk}\n\nWhat they said:\n{said or '(nothing)'}")
    return {key: [str(x).strip() for x in (data.get(key) or []) if str(x).strip()][:8]
            for key in ("unclear", "threads", "concepts")}


def write(folder: Path, *, client=None) -> Path:
    """(Re)write ``report.md`` from the folder's lesson and session log.

    With a client, the summary is made (again) and kept in ``summary.json``; without one,
    an earlier summary is reused."""
    folder = Path(folder)
    lesson = Lesson.load(folder / "lesson.json")
    events = library.events(folder)
    summary_file = folder / "summary.json"
    summary = None
    if client is not None and events:
        summary = summarize(client, lesson, events)
        summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif summary_file.is_file():
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
    prepared = None
    try:
        prepared = dt.date.fromisoformat(folder.name[:10])
    except ValueError:
        pass
    path = folder / "report.md"
    path.write_text(render(lesson, events, prepared=prepared, summary=summary) + "\n", encoding="utf-8")
    return path
