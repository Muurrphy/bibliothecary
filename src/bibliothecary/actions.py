"""Reader-requested actions, shared by typed and transcribed speech.

Only the reader's utterance is routed here. Book text and model output cannot
perform writes. A confirmation is spoken only after the local operation succeeds.
"""
import re

from . import annotations, learning
from .store import Store


def install(app):
    app.player.action = lambda text: execute(app, text)
    prefs = Store().get('settings', 'reading')
    app.reading_preferences = prefs
    app.reading_rate = app.hub.reading_rate = prefs.get('rate', 1)


def execute(app, text):
    player = app.player
    text = text.strip()
    # Negated requests must not accidentally save or change anything.
    if re.search(r"不要保存|不要记|别保存|别记|不用|do not|don't", text, re.I):
        return None
    prefs = Store().get('settings', 'reading')
    changed = {}
    if re.search(r"(?:收起|隐藏|关掉|不要显示).*(?:嘴|口型)|(?:嘴型|嘴巴).*(?:收起来|隐藏|关掉)|hide.*mouth", text, re.I):
        changed['folded'] = True
    elif re.search(r"(?:显示|展开|打开).*(?:嘴|口型)|show.*mouth", text, re.I):
        changed['folded'] = False
    elif re.search(r"(?:字|字号).*(?:大一点|调大|放大)|larger.*text", text, re.I):
        changed['font'] = min(28, prefs.get('font', 18) + 2)
    elif re.search(r"(?:字|字号).*(?:小一点|调小|缩小)|smaller.*text", text, re.I):
        changed['font'] = max(16, prefs.get('font', 18) - 2)
    elif re.search(r"夜间模式|深色模式|dark mode", text, re.I):
        changed['theme'] = 'dark'
    elif re.search(r"白天模式|浅色模式|light mode", text, re.I):
        changed['theme'] = 'light'
    elif re.search(r"说慢|讲慢|语速.*慢|speak slower", text, re.I):
        changed['rate'] = max(.75, prefs.get('rate', 1) - .25)
    elif re.search(r"说快|讲快|语速.*快|speak faster", text, re.I):
        changed['rate'] = min(1.5, prefs.get('rate', 1) + .25)
    if changed:
        prefs.update(changed)
        Store().put('settings', 'reading', prefs)
        app.reading_preferences = prefs
        app.reading_rate = app.hub.reading_rate = prefs.get('rate', 1)
        app.bus.publish('preferences', **prefs)
        return '调好了。'

    owner = getattr(player._record, '__self__', None)
    if owner is None or not hasattr(owner, 'folder'):
        return None
    if re.search(r"(?:这段|这次|本次).*(?:读完了|读好了)|finish this reading", text, re.I):
        if player.index < len(player.lesson.steps):
            return '这次阅读还有后面的内容。现在停下会保存位置，暂不标记读完。'
        player.finish()
        return '这次阅读已经完成，进度和问答都留下了。'
    thought = re.search(r"(?:记下我的想法|记一下我的想法|帮我记下[：:]|记个想法[：:])\s*[：:]?\s*(.+)", text)
    kind = content = None
    if thought:
        kind, content = 'thought', thought[1].strip()
    elif re.search(r"(?:保存|存下|留下|记下).*(?:解释|回答)|(?:解释|回答).*(?:保存|存下|留下|记下)|save.*explanation", text, re.I):
        answer = app.bus.screen()['screen'].get('answer') or {}
        kind, content = 'explanation', answer.get('text')
        if not content:
            return '还没有上一段解释可以保存。'
    elif re.search(r"(?:保存|存下|摘下|记下|摘抄|收藏).*(?:这句|这一句|原句)|(?:这句|这一句).*(?:保存|存|摘抄|收藏)|save this (?:line|sentence)", text, re.I):
        kind = 'quote'
        content = player.lesson.sentence(player.focus) if player.focus else None
    if kind:
        if not player.focus or not content:
            return '先告诉我是哪一句，我再把它和原文位置一起留下。'
        annotations.save(owner.folder, player.lesson, {'kind':kind, 'text':content, 'focus':player.focus})
        return {'quote':'这句原文存好了。', 'thought':'你的想法按原话存好了。',
                'explanation':'刚才的解释存好了，和原文、你的想法分开。'}[kind]
    if text.startswith(('我的学习目标是', '我想系统学习', '记住：', '忘记记忆 ', '本周计划', '开始复习', '本周回顾')) or text in ('今晚太累了','今天太累','今晚休息'):
        return learning.command(owner.store, text)
    return None
