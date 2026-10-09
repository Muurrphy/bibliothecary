import datetime as dt
import json
import threading
import time
from pathlib import Path
import pytest
from bibliothecary import library
from bibliothecary.records import Ledger
from bibliothecary.store import Store
from bibliothecary.jobs import Worker, checkpoint, Cancelled
from bibliothecary.annotations import save, listing
from bibliothecary.telegram import Librarian
from margin.lesson import Lesson,Step
from margin.player import Player
from margin.bus import Bus
from margin import brain

class Voice:
    def speak(self,text,stop): pass

def lesson():
    return Lesson(title='Reading',paragraphs=[['First.'],['Second.']],steps=[Step(focus='p1.s1',pause=10),Step(focus='p2.s1',pause=10)],manual=True)

def until(fn):
    end=time.monotonic()+3
    while time.monotonic()<end:
        if fn(): return True
        time.sleep(.01)
    return False

def test_manual_reading_requires_turning_and_explicit_finish():
    source=lesson(); folder=library.new_reading(source); ledger=Ledger(folder,source)
    p=Player(Bus(),Voice(),record=ledger.record);p.load(source);p.play()
    assert p.wait_idle(3) and p.index==1
    assert library.status(folder)=='started'
    time.sleep(.1);assert p.index==1
    p.next();assert p.wait_idle(3) and p.index==2
    assert library.status(folder)=='started'
    p.finish();assert p.wait_idle(3)
    assert library.status(folder)=='read'

def test_cancellation_discards_late_background_result():
    store=Store(); started=threading.Event();release=threading.Event();writes=[]
    def dispatch(kind,data):
        started.set();release.wait(2);checkpoint();writes.append(data)
    worker=Worker(store,dispatch);worker.start()
    key=worker.submit('test',{'text':'x'});assert started.wait(2)
    store.cancel(key);release.set()
    assert until(lambda:not worker.thread.is_alive() or store.jobs()[0]['status']=='cancelled')
    time.sleep(.05);worker.close()
    assert writes==[]

def test_slow_chat_does_not_block_control_and_duplicate_update_is_not_executed_twice():
    class Bot:
        def __init__(self): self.sent=[]
        def send(self,chat,text,buttons=None): self.sent.append(text)
        def typing(self,chat): pass
    class Client:
        def __init__(self): self.start=threading.Event();self.release=threading.Event();self.calls=0
        def chat_json(self,*args,**kwargs):
            self.calls+=1;self.start.set();self.release.wait(2);return {'reply':'late'}
    bot=Bot();client=Client();lib=Librarian(bot,client,background=True)
    lib.state={'owner':1,'introduced':True};lib.save()
    update={'update_id':500,'message':{'chat':{'id':1},'text':'hello'}}
    try:
        start=time.monotonic();lib.handle(update);assert time.monotonic()-start<1
        assert client.start.wait(2)
        lib.handle(update)
        lib.handle({'message':{'chat':{'id':1},'text':'/cancel'}})
        client.release.set();time.sleep(.1)
        assert client.calls==1 and 'late' not in bot.sent
    finally: client.release.set();lib.queue.close()

def test_annotations_validate_original_and_keep_authorship():
    source=lesson();folder=library.new_reading(source)
    with pytest.raises(ValueError): save(folder,source,{'focus':'p1.s1','kind':'quote','text':'Invented quotation'})
    for kind,text in [('quote','First.'),('thought','My thought'),('explanation','Model explanation')]:
        save(folder,source,{'focus':'p1.s1','kind':kind,'text':text})
    assert {r['kind'] for r in listing(folder)}=={'quote','thought','explanation'}
    assert (folder/'excerpts.md').exists()

def test_no_spoilers_across_realtime_text_and_web():
    source=lesson();source.guide='[NO_SPOILERS] first time'
    source.steps.append(Step(say='SECRET ENDING'))
    class Client:
        def __init__(self): self.calls=[]
        def chat_json(self,system,user,**kwargs):
            self.calls.append((system,user));return {'search':'ending', 'steps':[{'say':'Only the first paragraph.'}]}
        def web_search(self,*a,**kw): raise AssertionError('protected book must not search the plot')
    client=Client();brain.answer(client,source,'who dies?',current='p1.s1',position=0)
    prompt=brain.live_instructions(source,'p1.s1',0)
    assert 'Second.' not in prompt and 'SECRET' not in prompt
    assert all('Second.' not in user and 'SECRET' not in user for _,user in client.calls)

def test_readable_check_timeout_is_unknown_not_verified(monkeypatch):
    from bibliothecary import desk,search
    release=threading.Event()
    monkeypatch.setattr(search,'readable',lambda url: release.wait(2))
    monkeypatch.setattr(desk,'wait',lambda futures,timeout:None)
    try:
        good,bad=desk.Desk(None).openable([{'url':'https://example.org/x','title':'x'}])
        assert good==[] and bad[0]['availability']=='unknown'
    finally:release.set()
