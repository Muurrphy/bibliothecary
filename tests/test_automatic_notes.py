import json
import threading
import time
from bibliothecary import library, organize, report
from bibliothecary.records import Ledger
from bibliothecary.store import Store
from margin.lesson import Lesson, Step
from margin.player import Player
from margin.bus import Bus
from margin.live import Ears


def setup():
    lesson=Lesson(title='童年与阅读',paragraphs=[['原文。']],steps=[Step(focus='p1.s1')],manual=True)
    folder=library.new_reading(lesson);ledger=Ledger(folder,lesson)
    class Voice:
        def speak(self,text,stop): pass
    def failure(*args): raise RuntimeError('offline')
    player=Player(Bus(),Voice(),failure,record=ledger.record)
    player.load(lesson);assert player.wait_idle(3)
    return lesson,folder,ledger,player


def test_every_remark_is_kept_before_answer_even_without_a_save_command():
    lesson,folder,ledger,p=setup()
    remarks=['读这里让我想到了童年，奶奶也这样说。','但我不同意作者的解释。','为什么他会这么选？','刚才的比喻让我想到另一本书。']
    for text in remarks:
        p.ask(text);assert p.wait_idle(3)
    ledger.close()
    captured=[e['text'] for e in library.events(folder) if e['kind']=='utterance']
    assert captured==remarks
    for name in ('transcript.md','notes.md'):
        assert all(text in (folder/name).read_text() for text in remarks)
    assert not list(folder.rglob('*.wav')) and not list(folder.rglob('*.pcm'))


def test_summary_cannot_drop_small_talk_change_authorship_or_invent_quotes():
    lesson,folder,ledger,p=setup()
    for text in ('我小时候和爷爷一起读过这本书。','我觉得作者在逃避责任。','为什么？'):
        ledger.capture_utterance('voice','p1.s1')(text)
    ledger.companion('你觉得责任是什么？','p1.s1','question')
    class Client:
        def chat_json(self,system,user):
            rows=json.loads(user)
            return {'items':[
                {'id':rows[0]['id'],'categories':['personal'],'summary':'童年与爷爷共读的回忆。','evidence':'我小时候和爷爷一起读过这本书。'},
                {'id':rows[1]['id'],'categories':['ai_explanation'],'summary':'错归给 AI','evidence':rows[1]['text']},
                {'id':rows[2]['id'],'categories':['question'],'summary':'捏造','evidence':'并没有说过的话'},
            ]}
    result=organize.write(folder,Client())
    assert len(result['items'])==4 and result['status']=='pending'
    assert result['items'][0]['categories']==['personal']
    assert result['items'][1]['who']=='reader' and result['items'][1]['basis']=='original_only'
    assert result['items'][3]['categories']==['ai_question']
    assert '并没有说过的话' not in (folder/'notes.md').read_text()
    before=(folder/'transcript.md').read_bytes()
    organize.write(folder)
    assert (folder/'transcript.md').read_bytes()==before


def test_late_transcription_belongs_to_original_reading_and_is_kept_without_answer():
    lesson,folder,ledger,p=setup()
    started=threading.Event();release=threading.Event()
    def transcribe(*a): started.set();release.wait(3);return '我小时候也有这样的经历。'
    ears=Ears(p,None,transcribe,lambda t:False,lambda:'',lambda m:None)
    ears.audio('one',b'\0\0'*100)
    thread=threading.Thread(target=lambda:ears.end('one'));thread.start();assert started.wait(2)
    second=library.new_reading(lesson);other=Ledger(second,lesson)
    p.load(lesson,record=other.record);assert p.wait_idle(3)
    release.set();thread.join(3)
    assert any(e.get('text')=='我小时候也有这样的经历。' for e in library.events(folder))
    assert not any(e.get('text')=='我小时候也有这样的经历。' for e in library.events(second))


def test_transcription_failure_is_an_explicit_gap_not_an_empty_success():
    lesson,folder,ledger,p=setup()
    def fail(*a): raise RuntimeError('offline')
    ears=Ears(p,None,fail,lambda t:False,lambda:'',lambda m:None)
    ears.audio('one',b'\0\0'*100);ears.end('one');ledger.close()
    assert 'transcription_failed' in (folder/'transcript.md').read_text()
    assert '转写缺口' in (folder/'notes.md').read_text()


def test_slow_organizer_preserves_the_later_remark():
    lesson,folder,ledger,p=setup()
    ledger.capture_utterance('text',None)('先说一句。')
    class Client:
        def chat_json(self,system,user):
            ledger.capture_utterance('text',None)('后来想到的也不能丢。')
            return {'items':[]}
    organize.write(folder,Client())
    assert '后来想到的也不能丢。' in (folder/'transcript.md').read_text()
    assert '后来想到的也不能丢。' in (folder/'notes.md').read_text()


def test_failed_model_summary_leaves_original_and_unclassified_notebook():
    lesson,folder,ledger,p=setup()
    ledger.capture_utterance('text',None)('一句普通闲聊也要留下。')
    class Client:
        def chat_json(self,*args): raise RuntimeError('offline')
    try: report.write(folder,client=Client())
    except RuntimeError: pass
    assert '一句普通闲聊也要留下。' in (folder/'transcript.md').read_text()
    assert '一句普通闲聊也要留下。' in (folder/'notes.md').read_text()
