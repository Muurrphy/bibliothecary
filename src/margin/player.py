"""Plays a lesson onto the bus: speaks each step and moves the e-reader along.

One worker thread does all the talking, so the order of what reaches the
screen is always the order it was said. Anything that wants to cut in
(a question, pause, skip) sets ``_stop`` to silence the current sentence and
leaves a command in the queue.
"""

from __future__ import annotations

import inspect
import queue
import threading
import time
import traceback
from collections.abc import Callable

from .bus import Bus
from .lesson import Lesson, Step


def _join(a: str, b: str) -> str:
    """Join spoken sentences: no space after Chinese/Japanese punctuation."""
    if not a:
        return b
    return a + ("" if a[-1] in "。！？；，、…」』）" or b[:1] in "。！？，" else " ") + b


# answerer(lesson, question, focused sentence[, position in the plan]) returns a list of steps, or
# {"steps": [...], "then": "continue" | "pause" | "back" | "skip" | "restart"}.
Answerer = Callable[..., "list[Step] | dict | None"]


def default_fillers(explain_language: str) -> list[str]:
    lang = (explain_language or "").lower()
    if "chin" in lang or lang.startswith("zh") or "中文" in lang:
        return ["嗯——", "我看看。", "嗯，好。"]
    return ["Hmm—", "Let me see.", "Okay—"]


class Player:
    def __init__(self, bus: Bus, voice, answerer: Answerer | None = None, *, autoplay: bool = False,
                 log: Callable[[str], None] | None = None) -> None:
        self.bus, self.voice, self.answerer = bus, voice, answerer
        self.lesson: Lesson | None = None
        self.index = 0
        self.playing = autoplay
        self.focus: str | None = None
        self._cmds: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._log = log or (lambda _msg: None)
        self.fillers: list[str] = []          # short sounds ("嗯——") to fill the wait for an answer
        self.filler_after = 0.5               # seconds without an answer before one is used
        self._filler_turn = 0
        self._t_asked: float | None = None
        self.history: list[dict] = []        # recent questions and answers, for follow-ups
        self.forced = None                    # (lesson, question) -> steps that must be used, or None
        self._t_sound: float | None = None
        self._playback_failed = False
        if hasattr(voice, "on_start"):
            voice.on_start = self._sound_started
        self._thread = threading.Thread(target=self._run, daemon=True, name="margin-player")
        self._thread.start()

    # ---- commands (any thread) -------------------------------------------------------
    def load(self, lesson: Lesson) -> None:
        self._command("load", lesson)

    def play(self) -> None:
        self._command("play")

    def pause(self) -> None:
        self._command("pause", interrupt=True)

    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def next(self) -> None:
        self._command("seek", +1, interrupt=True)

    def prev(self) -> None:
        self._command("seek", -1, interrupt=True)

    def restart(self) -> None:
        self._command("restart", interrupt=True)

    def listening(self, hold: float = 15.0) -> None:
        """Someone started to speak: stop talking at once and wait for the question."""
        self._held_until = time.monotonic() + hold
        self._stop.set()
        self.bus.publish("status", state="listening")
        self._cmds.put(("noop", ()))

    def cancel_listening(self) -> None:
        self._held_until = 0.0
        self._cmds.put(("resume_status", ()))

    def ask(self, question: str, since: float | None = None) -> None:
        """``since``: when the question was received (``time.monotonic()``), for timing logs."""
        self._command("ask", question, since, None, interrupt=True)

    def ask_live(self, live, since: float | None = None) -> None:
        """A question already on its way to a realtime model (see ``live.LiveQuestion``)."""
        self._command("ask", "", since, live, interrupt=True)

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """For tests: wait until the queue is empty and nothing is playing."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self._cmds.empty() and not self.playing and not self._busy:
                return True
            time.sleep(0.01)
        return False

    def _command(self, name: str, *args, interrupt: bool = False) -> None:
        if interrupt:
            self._stop.set()
        self._cmds.put((name, args))

    # ---- worker ----------------------------------------------------------------------
    _busy = False
    _held_until = 0.0
    _cut: int | None = None

    def _run(self) -> None:
        while True:
            now = time.monotonic()
            if self._held_until > now:
                timeout = self._held_until - now
            elif self._held_until:
                self._held_until = 0.0
                self.bus.publish("status", state="reading" if self.playing else "paused")
                timeout = 0 if self._can_step() else None
            else:
                timeout = 0 if self._can_step() else None
            try:
                name, args = self._cmds.get(timeout=timeout)
            except queue.Empty:
                name, args = "step", ()
            self._busy = True
            try:
                if name == "step":
                    if self._can_step() and self._held_until <= time.monotonic():
                        self._step()
                else:
                    self._handle(name, *args)
            except Exception as err:  # keep the companion alive whatever happens
                self._log("error: " + "".join(traceback.format_exception(err)).strip())
                self.bus.publish("status", state="paused")
                self.bus.publish("caption", text=f"(something went wrong: {err})")
                self.playing = False
            finally:
                self._busy = False

    def _can_step(self) -> bool:
        return self.playing and self.lesson is not None and self.index < len(self.lesson.steps)

    def _handle(self, name: str, *args) -> None:
        self._stop.clear()
        if name == "load":
            self.lesson, self.index, self.focus, self._cut = args[0], 0, None, None
            self.fillers = default_fillers(self.lesson.explain_language) if self._wants_fillers() else []
            self._prepare([Step(say=f) for f in self.fillers])
            # planned moments ("always" questions) are voiced ahead, so they start without a wait
            self._prepare([Step(say=st.get("say", "")) for q in self.lesson.questions if q.get("always")
                           for st in q.get("steps", []) if st.get("say")])
            self.bus.publish("lesson", **self.lesson.reader_payload())
            self.bus.publish("status", state="reading" if self.playing else "paused")
        elif name == "play":
            if self.lesson and self.index >= len(self.lesson.steps):
                self.index = 0
            self.playing = True
            self.bus.publish("clear_answer")
            self.bus.publish("status", state="reading")
        elif name == "pause":
            self.playing = False
            self.bus.publish("status", state="paused")
        elif name == "seek" and self.lesson:
            self.index = max(0, min(len(self.lesson.steps) - 1, self.index + args[0]))
            self._cut = None
            self.bus.publish("clear_answer")
        elif name == "restart" and self.lesson:
            self.index, self.focus, self._cut = 0, None, None
            self.bus.publish("lesson", **self.lesson.reader_payload())
            self.playing = True
            self.bus.publish("status", state="reading")
        elif name == "ask":
            self._held_until = 0.0
            self._answer(args[0], args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None)
        elif name == "resume_status":
            self.bus.publish("status", state="reading" if self.playing else "paused")

    def _step(self) -> None:
        assert self.lesson is not None
        self._busy = True
        try:
            self.bus.publish("progress", step=self.index + 1, of=len(self.lesson.steps))
            self._prepare(self.lesson.steps[self.index:self.index + 3])
            if self._perform(self.lesson.steps[self.index]):
                self._cut = None
                self._advance()
            else:
                self._cut = self.index
        finally:
            self._busy = False

    def _prepare(self, steps: list[Step]) -> None:
        """Let a voice synthesize what comes next while the current line plays."""
        prepare = getattr(self.voice, "prepare", None)
        if prepare:
            for step in steps:
                if step.say:
                    prepare(step.say)

    def _perform(self, step: Step, *, answer: dict | None = None) -> bool:
        """Show and say one step. False when it was interrupted."""
        self._stop.clear()
        if step.focus and step.focus != self.focus:
            if self.focus is None or step.focus.split(".")[0] != self.focus.split(".")[0]:
                self.bus.publish("clear_note")
                self.bus.publish("clear_figure")
            self.bus.publish("clear_marks")
            self.focus = step.focus
            self.bus.publish("focus", sentence=step.focus)
        if step.clear_note:
            self.bus.publish("clear_note")
            self.bus.publish("clear_figure")
        if step.mark:
            self.bus.publish("mark", sentence=step.mark.get("sentence") or self.focus, phrase=step.mark["phrase"])
        if step.note:
            self.bus.publish("note", text=step.note, sentence=self.focus)
        if step.figure:
            self.bus.publish("figure", sentence=self.focus, **step.figure)
        if step.cue:
            self.bus.publish("cue", name=step.cue, text=step.say)
        if step.say:
            if answer is not None:
                answer["text"] = _join(answer["text"], step.say)
                self.bus.publish("answer", question=answer["question"], text=answer["text"], done=False)
            self.bus.publish("caption", text=step.say)
            try:
                self.voice.speak(step.say, self._stop)
            except Exception as err:
                self._playback_failed = True
                self._log(f"playback paused: {err}")
                self.playing = False
                self._stop.set()
                self.bus.publish("playback_error", message=str(err))
                self.bus.publish("status", state="paused")
        if step.pause and not self._stop.is_set():
            self._stop.wait(step.pause)
        return not self._stop.is_set()

    def _advance(self) -> None:
        self.index += 1
        if self.index >= len(self.lesson.steps):
            self.playing = False
            self.bus.publish("status", state="done")

    def _ask_answerer(self, question: str):
        if not self.answerer:
            return None
        try:
            params = inspect.signature(self.answerer).parameters
            takes_position = len(params) >= 4 or any(p.kind == p.VAR_POSITIONAL for p in params.values())
        except (TypeError, ValueError):
            takes_position = False
        args = (self.lesson, question, self.focus) + ((self.index,) if takes_position else ())
        if len(params) >= 5:
            args += (list(self.history),)
        return self.answerer(*args)

    def _sound_started(self) -> None:
        if self._t_asked is not None and self._t_sound is None:
            self._t_sound = time.monotonic()

    def _wants_fillers(self) -> bool:
        import os

        return hasattr(self.voice, "prepare") and os.environ.get("MARGIN_FILLERS", "0") == "1"

    def _filler(self, stream) -> bool:
        """Say "嗯——" if the answer is slow to start, so the silence does not feel like nobody heard."""
        if not self.fillers or stream.wait_first(self.filler_after):
            return False
        text = self.fillers[self._filler_turn % len(self.fillers)]
        self._filler_turn += 1
        self.voice.speak(text, self._stop)
        self._prepare([Step(say=text)])            # ready for next time
        return True

    def _answer(self, question: str, since: float | None = None, live=None) -> None:
        """Answer, then go back to the plan on our own unless asked not to.

        A question cuts into the line being read: you asked because you were looking at it,
        so once answered we go on with the next line instead of reading it again."""
        if not self.lesson:
            return
        skip_cut = self._cut is not None and self._cut == self.index
        self._cut = None
        self._playback_failed = False
        resume_focus = self.focus
        t0 = since or time.monotonic()
        self._t_asked, self._t_sound = t0, None
        self.bus.publish("status", state="thinking")
        result = None
        if live is not None:
            result = live.stream
        else:
            try:
                result = self._ask_answerer(question)
            except Exception as err:
                self._log(f"answer failed: {err}")
        then, command_only, stream, filled = "continue", False, None, False
        if hasattr(result, "start") and hasattr(result, "wait_first"):     # streamed: steps arrive as written
            stream = result.start(on_step=lambda st: self._prepare([st]))
            if live is not None:
                # wait (briefly) for what you said: to show it, and to be sure it was not our own voice
                heard = live.wait_heard(max(0.0, 1.6 - (time.monotonic() - t0)))
                if heard is None:
                    self._log(f"ignored what the microphone heard: {live.turn.transcript!r}")
                    live.cancel()
                    self._cut = self.index if skip_cut else self._cut
                    self.bus.publish("status", state="reading" if self.playing else "paused")
                    return
                question = heard or "…"
                if heard:
                    self._log(f"question: {heard}")
                planned = self.forced(self.lesson, heard) if (heard and self.forced) else None
                if planned:                       # a planned moment (e.g. for filming): use it as written
                    live.cancel()
                    steps, stream = list(planned), None
            if stream is not None:
                filled = self._filler(stream)
                steps = stream
        elif isinstance(result, dict):
            steps, then = list(result.get("steps") or []), result.get("then") or "continue"
            command_only = not steps
        else:
            steps = list(result or [])
        sorry = Step(say="I'm not sure about that one. Let's keep going, and ask me again in other words?")
        if not command_only:
            if isinstance(steps, list):
                steps = steps or [sorry]
                self._prepare(steps)
            answer = {"question": question, "text": ""}
            spoken, t_first = 0, None
            for step in steps:
                if not spoken:
                    t_first = time.monotonic()
                    self.bus.publish("answer", question=question, text="", done=False)
                    self.bus.publish("status", state="answering")
                spoken += 1
                if not self._perform(step, answer=answer):
                    break
            if stream is not None:
                then = stream.then
                if live is not None and live.turn.transcript and question == "…":
                    question = live.turn.transcript
                    self._log(f"question: {question}")
                if stream.error:
                    self._log(f"answer failed: {stream.error}")
                if not spoken and stream.error and not self._stop.is_set():
                    self.bus.publish("answer", question=question, text="", done=False)
                    self._perform(sorry, answer=answer)
                    spoken = 1
            if not spoken:
                command_only = True                   # e.g. "go on" (or nothing said to us): just do it
            if not command_only:
                self.bus.publish("answer", question=question, text=answer["text"], done=True)
                if answer["text"]:
                    self.history = (self.history + [{"q": question, "a": answer["text"]}])[-3:]
            if t_first is not None:
                sound = f"{self._t_sound - t0:.1f}s" if self._t_sound else "?"
                model = ""
                if live is not None and live.turn.t_first_text and live.turn.t_commit:
                    model = f"realtime model started writing {live.turn.t_first_text - live.turn.t_commit:.1f}s, "
                self._log(f"answer timing ({'realtime' if live is not None else 'text'}): {model}"
                          f"first line written {t_first - t0:.1f}s, first sound {sound}"
                          f"{' (after a filler)' if filled else ''}")
        self._t_asked = None
        interrupted = self._stop.is_set()
        n = len(self.lesson.steps)
        if self._playback_failed:
            self.playing = False
            self.bus.publish("status", state="paused")
            return
        if then == "restart":
            self.index, self.focus = 0, None
            self.bus.publish("lesson", **self.lesson.reader_payload())
        elif then == "back":
            if not skip_cut:
                self.index = max(0, min(n - 1, self.index - 1))
        elif then == "skip":
            self.index = self._next_paragraph(self.index + (1 if skip_cut else 0))
        elif skip_cut and then != "ignore":
            self.index += 1
        if then == "pause":
            self.playing = False
        elif then == "ignore":
            pass                                     # nothing was said to us: change nothing
        elif self.index < n:
            self.playing = True                     # by default you want to keep listening
        if not command_only and not interrupted and self.playing and resume_focus:
            self._stop.wait(1.2)
            self.bus.publish("clear_answer")
            self.focus = None
        elif command_only:
            self.bus.publish("clear_answer")
        if self.index >= n:
            self.playing = False
        self.bus.publish("status", state="reading" if self.playing else ("done" if self.index >= n else "paused"))

    def _next_paragraph(self, index: int) -> int:
        """First step at or after ``index`` that starts a new paragraph."""
        steps = self.lesson.steps
        para = lambda st: st.focus.split(".")[0] if st.focus else None
        current = para(steps[min(index, len(steps) - 1)]) if steps else None
        for i in range(index, len(steps)):
            p = para(steps[i])
            if p and p != current:
                return i
        return len(steps)
