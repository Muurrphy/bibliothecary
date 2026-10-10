import datetime as dt
import json
import threading
from pathlib import Path

import pytest
from bibliothecary import books, library
from bibliothecary.desk import Desk
from bibliothecary.records import Ledger
from bibliothecary.telegram import Librarian
from margin.brain import _answer_prompt
from margin.bus import Bus
from margin.lesson import Lesson, Step
from margin.player import Player

@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('BIBLIOTHECARY_HOME', str(tmp_path))
    return tmp_path

def lesson(title='A'):
    return Lesson(title=title, language='en', explain_language='en', paragraphs=[['Opening.'], ['SECRET ENDING.']],
                  steps=[Step(say='Opening.', focus='p1.s1'), Step(say='Ending.', focus='p2.s1')])

class Voice:
    def speak(self, text, stop): pass

def test_switch_serializes_recorder_and_discards_previous_history(home):
    class HeldVoice:
        def __init__(self): self.started=threading.Event(); self.release=threading.Event()
        def speak(self, text, stop): self.started.set(); self.release.wait(2)
    voice=HeldVoice(); a,b=[],[]
    p=Player(Bus(),voice,record=lambda kind,**data:a.append(kind))
    p.load(lesson()); p.play(); assert voice.started.wait(2)
    p.history=[{'q':'old book','a':'old answer'}]
    p.load(lesson('B'), record=lambda kind,**data:b.append(kind))
    voice.release.set(); p.pause(); assert p.wait_idle(3)
    assert 'end' not in b and not p.history

def test_checkpoint_restores_position_and_opening_is_not_start(home):
    first=lesson(); folder=library.new_reading(first)
    ledger=Ledger(folder,first)
    p=Player(Bus(),Voice(),record=ledger.record)
    p.load(first); assert p.wait_idle(2)
    assert library.status(folder)=='prepared'
    p.next(); assert p.wait_idle(2)
    q=Player(Bus(),Voice(),record=Ledger(folder,first).record)
    q.load(first); assert q.wait_idle(2)
    assert q.index==1

def test_stale_book_update_cannot_unpause(home):
    folder=home/'books'/'test'; folder.mkdir(parents=True)
    books.Book(folder,{'title':'test','chapters':[], 'mode':'text','status':'reading','sessions':[]}).save()
    a,b=books.shelf()[0],books.shelf()[0]
    books.set_status(a,'paused'); books.set_mode(b,'digest')
    assert books.shelf()[0].data['status']=='paused'

def test_corrupt_summary_does_not_break_chat(home):
    folder=library.new_reading(lesson()); (folder/'summary.json').write_text('{broken')
    assert 'A' in Desk(None).context()

def test_memory_keeps_provenance(home):
    d=Desk(None); d.learn(['first']); before=json.loads((home/'reader.json').read_text())['notes'][0]
    d.learn(['second']); after=json.loads((home/'reader.json').read_text())['notes'][0]
    assert before['t']==after['t']

def test_text_answer_context_excludes_future_text_and_plan():
    book=lesson(); book.guide='The reader is reading this book for the first time. Never reveal later events.'
    _,prompt=_answer_prompt(book,'Who?', 'p1.s1',0,None)
    assert 'SECRET' not in prompt and 'Ending.' not in prompt

def test_failed_daily_message_is_retryable(home):
    class Bot:
        def send(self,*a,**kw): raise RuntimeError('offline')
    lib=Librarian(Bot(),None,now=lambda:dt.datetime(2026,10,9,12))
    lib.state={'owner':1,'introduced':True}
    with pytest.raises(RuntimeError): lib.tick()
    assert lib.state.get('asked')!='2026-10-09'
