"""Writing lessons and answering questions with a language model.

The model never talks to the e-reader directly. It returns the same small
steps a hand-written lesson uses (say / focus / mark / note), and the player
checks them against the article before anything reaches the screen.
"""

from __future__ import annotations

import json
import queue
import re
import threading
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from .lesson import Lesson, Step
from .llm import OpenAICompatible

STEP_SHAPE = """Each step is an object:
  "say":   what you say aloud now, in {explain}; 1-3 short spoken sentences.
  "focus": the id of the sentence on screen this step is about, e.g. "p2.s1" (optional).
  "mark":  a word or short phrase copied EXACTLY from the focused sentence, to circle (optional).
  "note":  a margin note, at most 25 words, in {explain} (optional). Use it for a translation,
           a key term with its meaning, or a fact worth keeping. Not every step needs one.
  "figure": a small diagram drawn on the e-reader (optional, rare: only when seeing the structure
           helps more than hearing it). Keep every label to a few words. One of:
           {{"type": "compare", "title": "...", "rows": [{{"label": "...", "items": ["...", ...], "hi": [2]}}]}}
             rows of boxes side by side, "hi" = indexes of boxes to highlight (e.g. word orders)
           {{"type": "flow", "title": "...", "items": ["...", "...", "..."]}}       a → b → c
           {{"type": "timeline", "title": "...", "items": [{{"when": "...", "what": "..."}}]}}
           {{"type": "terms", "title": "...", "items": [{{"term": "...", "meaning": "..."}}]}}"""

LESSON_SYSTEM = """You are a calm, curious reading companion. You walk someone through an article on an
e-ink reader, the way a good friend who already read it would: you tell them
what it says, translate when they read in a second language, point at the words that matter, and
skip what does not. You are not a summarizer and not a lecturer.

Return JSON: {{"preview": [ ... ], "steps": [ ... ], "review": [ ... ], "goodbye": "..."}}.
{shape}

"preview": {n_preview} step objects ({{"say": "..."}}) said BEFORE the reading, in {explain}, without "focus": the background
knowledge someone needs to follow this piece and may not have. Terms, people, places, the field, how
something works. Only what the article relies on; not a summary of the article. [] if nothing is needed.
{known}
"review": {n_review} questions asked AFTER the reading, to check the main points stuck:
  [{{"question": "...", "answer": "..."}}], both in {explain}. Short questions that can be answered
  aloud in a sentence or two; "answer" is what a good answer says. [] when asked for none.
"goodbye": one short line said at the very end, after the review{goodnight}.

Rules for "steps" (the reading itself):
- It is a short talk with a clear arc: say what the piece is and why it is interesting (no focus),
  give whatever background the preview did not, walk through the main points in the order of the article, and close
  with why it matters. Someone who never interrupts should still get the whole story.
- Go through the article in order, one idea per step. A step usually covers several sentences or a
  whole paragraph: focus the sentence that carries the idea. Skip what adds nothing (asides, credits,
  repetition); a paragraph that adds nothing new can be passed over.
- Retell, do not translate. Say what it means in your own words, the way you would tell a friend over
  dinner, not sentence by sentence. Never narrate the structure of the article ("this paragraph",
  "next it says", "the heading", "the section begins", "it then turns to"); just tell the content.
- Notes are for what is worth keeping on paper: a key term with its meaning, a number, a name, a
  translation of a phrase. Never a note about the structure ("transition", "data coming up") and never
  a vague label. Most steps need no note; a note must be correct on its own.
- Numbers, names and claims must come from the article. Do not invent facts.
{style}
- Mark at most one phrase per step, and only when pointing at it helps.
- End with one short step that says what to remember.
- About {n_steps} reading steps at most; fewer is fine for a short piece."""

ANSWER_SYSTEM = """You are a reading companion on an e-ink reader, going through an article with a friend.
You were following a plan you prepared (below), and they just said something. Usually it is a question.

How to answer:
- Answer the question itself in your first sentence. No warm-up, no restating the question,
  no "good question".
- Use everything you know, not only the article. People reading a paper ask about things around
  it all the time; that is how they learn. Never reply that the article does not mention
  something, and never say you will not go into it: say what is known, and if it is uncertain
  or debated, say so in a few words.
- Be brief: usually one or two sentences, at most four short ones, unless they ask for detail.
{style}
- Afterwards you go back to your plan on your own: do not ask them anything, do not offer to
  continue, and do not explain in depth what the plan covers next.

Return JSON with "then" first: {{"then": "continue", "steps": [ ... ]}}.
"steps": 0-3 steps. The first step is ONE short sentence that answers directly (it is spoken while
you are still writing the rest); details come in the next steps. The first step should usually
"focus" the sentence the question is about, so the screen jumps there, and may "mark" the words
that answer it. If they want to look at a part of the text ("scroll up to...", "show me the part
about..."), focus that sentence. A "figure" helps when the answer is about structure, order, or a
sequence.
{shape}
"then" says what happens after your steps:
  "continue": go on with the plan where you left it (default, also when they say go on/start).
  "pause":    they want you to stop or be quiet for now (e.g. "wait", "stop", "let me think").
  "back":     they want the last part of the plan again ("say that again", "I missed that").
  "skip":     they want to move on past the current part.
  "restart":  they want to start the article over.
  "ignore":   nothing was said to you (noise, other people talking, or your own voice reading).
When they only ask you to go on (or where you were), one very short step is enough, or none.
The listener may speak any language; answer in {explain}."""

STYLE = """- Talk like a person, not like an AI: plain words, concrete facts and examples, short sentences.
  Do not label, praise or frame things; just say what they are. Never use phrases like
  "a fascinating finding", "a very stable rule", "interestingly", "it is worth noting",
  "in summary", "simply put", or in Chinese 神奇的是、有意思的是、值得注意的是、总的来说、
  简单来说、其实、一个很……的规律/规矩、这正是最有意思的地方."""

_CONTINUE = re.compile(r"继续|接着|往下讲|开始吧|开始讲|讲吧|go on|keep going|continue|carry on|let'?s start|^start", re.IGNORECASE)
_PAUSE = re.compile(r"暂停|停一下|停一停|先停|停下|别讲了|别说了|等一下|等等|安静|pause|stop|hold on|wait|^停", re.IGNORECASE)
_BACK = re.compile(r"再说一遍|再讲一遍|重复一下|没听清|repeat|say (that|it) again", re.IGNORECASE)
_SKIP = re.compile(r"跳过|下一段|skip", re.IGNORECASE)
_RESTART = re.compile(r"从头|重头|重新讲|重新开始|start over|from the (top|beginning)", re.IGNORECASE)
_REFRESH = re.compile(r"刷新|刷一下|refresh|reload", re.IGNORECASE)
_QUESTIONISH = re.compile(r"[?？]|为什么|什么|怎么|哪|吗|呢|是不是|\b(why|what|how|where|which|who)\b", re.IGNORECASE)
# speech-to-text sometimes writes Mandarin in traditional characters ("你繼續講"): read both
_TRADITIONAL = str.maketrans("繼續講說頭開從聽別靜過暫這麼樣嗎為讓來還沒話問遍幾點", "继续讲说头开从听别静过暂这么样吗为让来还没话问遍几点")


def quick_intent(text: str) -> str | None:
    """Short commands ("继续", "等一下", "再说一遍", "从头讲") need no model: do them at once."""
    t = text.strip().translate(_TRADITIONAL)
    size = len(re.sub(r"[\W_]+", "", t))
    if t and size <= 30 and _REFRESH.search(t):
        return "refresh"                          # "the page is stuck, refresh it"
    if not t or size > 20 or _QUESTIONISH.search(t):
        return None
    for name, rx in (("restart", _RESTART), ("pause", _PAUSE), ("back", _BACK), ("skip", _SKIP),
                     ("continue", _CONTINUE)):
        if rx.search(t):
            return name
    return None


THEN = {"continue", "pause", "back", "skip", "restart", "ignore", "refresh"}


def plan_summary(lesson: Lesson, position: int | None, width: int = 90) -> str:
    """The prepared lines, marked done / next, so an answer knows where the talk stands."""
    if position is None:
        return ""
    lines = []
    for i, step in enumerate(lesson.steps):
        if not step.say:
            continue
        tag = "done" if i < position else ("NEXT" if i == position else "    ")
        text = step.say if len(step.say) <= width else step.say[:width] + "…"
        lines.append(f"[{tag}] {i + 1}. {text}")
    return "\n\nYour plan:\n" + "\n".join(lines)


def _history(history: list[dict] | None) -> str:
    if not history:
        return ""
    lines = [f"- They asked: {h['q']}\n  You said: {h['a']}" for h in history[-3:] if h.get("q")]
    return "\n\nEarlier tonight:\n" + "\n".join(lines) if lines else ""


def _shape(explain: str) -> str:
    return STEP_SHAPE.format(explain=explain)


def build_lesson(client: OpenAICompatible, title: str, text: str, *, explain_language: str = "English",
                 source: str = "", language: str = "en", bedtime: bool = False, preview: bool = True,
                 review: int = 3, known: str = "") -> Lesson:
    """A session in three parts: background first (preview), the reading, then a few questions (review).

    ``known``: what the reader is already known to understand, so the preview can skip it."""
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    lesson = Lesson.from_dict({"title": title, "source": source, "language": language,
                               "explain_language": explain_language, "paragraphs": paragraphs, "steps": []})
    n = max(4, min(24, len(lesson.sentence_ids()) // 3 + 3))
    system = LESSON_SYSTEM.format(
        shape=_shape(explain_language), explain=explain_language, n_steps=n, style=STYLE,
        n_preview="2-4" if preview else "0", n_review=str(max(0, review)),
        known=f"The listener already understands: {known}. Do not explain these again.\n" if known else "",
        goodnight=", and wish them good night" if bedtime else "")
    data = client.chat_json(system, lesson.context())
    lesson.steps = assemble(lesson, data, preview=preview, review=review)
    return lesson


def _as_steps(raw: Any) -> list[Any]:
    """Models sometimes give a part as plain sentences instead of step objects: accept both."""
    if isinstance(raw, str):
        raw = [raw]
    return [{"say": item} if isinstance(item, str) else item for item in raw or []] if isinstance(raw, list) else []


def assemble(lesson: Lesson, data: dict[str, Any], *, preview: bool = True, review: int = 3) -> list[Step]:
    """The model's three parts as one list of steps: preview, reading, review questions, goodbye."""
    steps = []
    if preview:
        for step in clean_steps(lesson, _as_steps(data.get("preview"))):
            step.focus, step.mark, step.part = None, None, "preview"
            if step.say:
                steps.append(step)
    steps += clean_steps(lesson, _as_steps(data.get("steps")))
    reviews = data.get("review") or []
    for item in (reviews if isinstance(reviews, list) else [])[:max(0, review)]:
        if isinstance(item, str):
            item = {"question": item}
        if isinstance(item, dict) and str(item.get("question") or "").strip():
            steps.append(Step(say=str(item["question"]).strip(), part="review",
                              expect=str(item.get("answer") or "").strip() or None))
    if str(data.get("goodbye") or "").strip():
        steps.append(Step(say=str(data["goodbye"]).strip(), part="review"))
    return steps


def _review(review: dict | None) -> str:
    if not review:
        return ""
    good = f"\nA good answer says: {review['expect']}" if review.get("expect") else ""
    return (f"\n\nYou have finished reading and just asked them a review question: {review['question']}{good}"
            "\nWhat they say now is most likely their answer. In one or two sentences, tell them plainly what"
            " they got right and add what is missing; if it was wrong, give the right answer kindly. Then"
            " \"then\": \"continue\". If they did not answer (they want to skip, or go on), handle it as usual.")


def _answer_prompt(lesson: Lesson, question: str, current: str | None, position: int | None,
                   explain_language: str | None, history: list[dict] | None = None,
                   review: dict | None = None) -> tuple[str, str]:
    explain = explain_language or lesson.explain_language
    system = ANSWER_SYSTEM.format(shape=_shape(explain), explain=explain, style=STYLE)
    where = f"\n\nYou were explaining {current}: {lesson.sentence(current)}" if current else ""
    where += _review(review)
    context = f"{lesson.context()}{plan_summary(lesson, position)}{_history(history)}{where}"
    if lesson.cues:
        system += ("\nYou can also show things on the computer screen: add \"cue\": \"<name>\" to the step "
                   "that talks about it, only when they ask to see it or it clearly helps. Available:\n"
                   + "\n".join(f"  {k}: {v}" for k, v in lesson.cues.items()))
    return system, f"{context}\n\nThe listener said: {question}"


def live_instructions(lesson: Lesson, current: str | None, position: int | None,
                      history: list[dict] | None = None, review: dict | None = None) -> str:
    """Everything a realtime model needs; the listener's words come as audio."""
    system, user = _answer_prompt(lesson, "(see the audio)", current, position, None, history, review)
    return (system + "\nReply with the JSON object only.\n\n" + user.replace(
        "The listener said: (see the audio)", "What the listener said is the audio input."))


def _then(value: Any) -> str:
    then = str(value or "continue").lower()
    return then if then in THEN else "continue"


def answer(client: OpenAICompatible, lesson: Lesson, question: str, *, current: str | None,
           position: int | None = None, explain_language: str | None = None,
           history: list[dict] | None = None, review: dict | None = None) -> dict[str, Any]:
    """{"steps": [Step, ...], "then": "continue" | "pause" | "back" | "skip" | "restart" | "ignore"}"""
    system, user = _answer_prompt(lesson, question, current, position, explain_language, history, review)
    data = client.chat_json(system, user, max_tokens=900)
    return {"steps": clean_steps(lesson, data.get("steps", []), current=current), "then": _then(data.get("then"))}


class _StepScanner:
    """Pulls each complete object out of ``"steps": [ ... ]`` while the JSON is still arriving."""

    def __init__(self) -> None:
        self.text = ""
        self.pos = -1          # where to continue scanning inside the steps array
        self.start = -1        # start of the object being read
        self.depth = 0
        self.in_str = self.esc = False

    def feed(self, piece: str) -> list[dict]:
        self.text += piece
        found = []
        if self.pos < 0:
            m = re.search(r'"steps"\s*:\s*\[', self.text)
            if not m:
                return found
            self.pos = m.end()
        t = self.text
        while self.pos < len(t):
            ch = t[self.pos]
            if self.in_str:
                if self.esc:
                    self.esc = False
                elif ch == "\\":
                    self.esc = True
                elif ch == '"':
                    self.in_str = False
            elif ch == '"':
                self.in_str = True
            elif ch == "{":
                if self.depth == 0:
                    self.start = self.pos
                self.depth += 1
            elif ch == "}":
                self.depth -= 1
                if self.depth == 0 and self.start >= 0:
                    try:
                        obj = json.loads(t[self.start:self.pos + 1])
                        if isinstance(obj, dict):
                            found.append(obj)
                    except json.JSONDecodeError:
                        pass
                    self.start = -1
            elif ch == "]" and self.depth == 0:
                self.pos = len(t) + 10 ** 9      # the array is over
                break
            self.pos += 1
        return found


class StreamedAnswer:
    """An answer whose steps arrive while the model is still writing.

    ``start(on_step)`` reads the stream in the background; iterate to get the steps in
    order; ``then`` is final once iteration ends. If the stream fails before the first
    step, ``fallback`` (a plain request) is tried instead."""

    def __init__(self, pieces: Callable[[], Iterable[str]], lesson: Lesson, current: str | None,
                 fallback: Callable[[], dict] | None = None) -> None:
        self._pieces, self.lesson, self.current, self._fallback = pieces, lesson, current, fallback
        self._queue: queue.Queue = queue.Queue()
        self._first = threading.Event()
        self.then = "continue"
        self.error: Exception | None = None
        self.count = 0

    def start(self, on_step: Callable[[Step], None] | None = None) -> StreamedAnswer:
        threading.Thread(target=self._run, args=(on_step,), daemon=True, name="margin-answer").start()
        return self

    def _emit(self, step: Step, on_step) -> None:
        self.count += 1
        if on_step:
            on_step(step)
        self._queue.put(step)
        self._first.set()

    def _run(self, on_step) -> None:
        scanner = _StepScanner()
        try:
            try:
                for piece in self._pieces():
                    for obj in scanner.feed(piece):
                        for step in clean_steps(self.lesson, [obj], current=self.current):
                            self.current = step.focus or self.current
                            self._emit(step, on_step)
                try:
                    self.then = _then(json.loads(scanner.text).get("then"))
                except json.JSONDecodeError:
                    m = re.search(r'"then"\s*:\s*"(\w+)"', scanner.text)
                    self.then = _then(m.group(1) if m else None)
            except Exception as err:
                self.error = err
                if self.count == 0 and self._fallback is not None:
                    data = self._fallback()
                    self.then = _then(data.get("then"))
                    for step in data.get("steps") or []:
                        self._emit(step, on_step)
                    self.error = None
        except Exception as err:
            self.error = err
        finally:
            self._first.set()
            self._queue.put(None)

    def wait_first(self, timeout: float) -> bool:
        """True once the first step (or the end) is there."""
        return self._first.wait(timeout)

    def __iter__(self) -> Iterator[Step]:
        while True:
            step = self._queue.get()
            if step is None:
                return
            yield step


def answer_stream(client: OpenAICompatible, lesson: Lesson, question: str, *, current: str | None,
                  position: int | None = None, explain_language: str | None = None,
                  history: list[dict] | None = None, review: dict | None = None) -> StreamedAnswer:
    """Like ``answer`` but streamed. If streaming fails: a plain request, then the lesson's own answers."""
    system, user = _answer_prompt(lesson, question, current, position, explain_language, history, review)

    def fallback() -> dict:
        try:
            return answer(client, lesson, question, current=current, position=position,
                          explain_language=explain_language, history=history, review=review)
        except Exception:
            return {"steps": scripted_answer(lesson, question) or [], "then": "continue"}

    return StreamedAnswer(lambda: client.chat_json_stream(system, user, max_tokens=900), lesson, current,
                          fallback=fallback)


def clean_steps(lesson: Lesson, raw: list[Any], current: str | None = None) -> list[Step]:
    """Keep what is valid: unknown sentence ids are dropped, marks must be in their sentence."""

    ids, steps = set(lesson.sentence_ids()), []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        step = Step.from_dict(item, current)
        if step.focus and step.focus not in ids:
            step.focus = None
        current = step.focus or current
        if step.mark:
            sid, phrase = step.mark.get("sentence") or current, step.mark.get("phrase", "")
            step.mark = {"sentence": sid, "phrase": phrase} if sid in ids and phrase and phrase in lesson.sentence(sid) else None
        if step.cue and step.cue not in lesson.cues:
            step.cue = None
        if step.say or step.note or step.focus or step.cue:
            steps.append(step)
    return steps


def _matches(item: dict, q: str) -> int:
    """How well a scripted question fits: ``match`` (any word counts) and ``match_all``
    (a list of word groups that must each be hit)."""
    groups = item.get("match_all")
    if groups and not all(any(w.lower() in q for w in group) for group in groups):
        return 0
    hits = sum(1 for word in item.get("match", []) if word.lower() in q)
    return hits + (len(groups) if groups else 0)


def scripted_answer(lesson: Lesson, question: str, *, forced_only: bool = False) -> list[Step] | None:
    """Answers written into the lesson (``questions``). With ``forced_only``, only those marked
    ``"always": true``, which are used even when a model is available (for a planned moment)."""

    q = question.lower()
    best, score = None, 0
    for item in lesson.questions:
        if forced_only and not item.get("always"):
            continue
        hits = _matches(item, q)
        if hits > score:
            best, score = item, hits
    if best is None and not forced_only and len(lesson.questions) == 1 and not lesson.questions[0].get("match"):
        best = lesson.questions[0]
    if best is None:
        return None
    return clean_steps(lesson, best.get("steps", []))


def forced_answer(lesson: Lesson, question: str) -> list[Step] | None:
    return scripted_answer(lesson, question, forced_only=True)
