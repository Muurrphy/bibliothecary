import json
import threading
from types import SimpleNamespace

from bibliothecary import library
from bibliothecary.records import Ledger
from margin import brain
from margin.bus import Bus
from margin.lesson import Lesson, Step
from margin.player import Player


def make_player(answer=None, client=None):
    lesson = Lesson('An interview', [['First original sentence.', 'Second sentence.']],
                    [Step(say='goodbye')], explain_language='Simplified Chinese')
    folder = library.new_reading(lesson)
    ledger = Ledger(folder, lesson, client=client)
    voice = SimpleNamespace(speak=lambda *args: None)
    player = Player(Bus(), voice, answer or (lambda *args: {'steps': [Step(say='A reply')], 'then': 'pause'}), record=ledger.record)
    player.load(lesson)
    assert player.wait_idle(3)
    return player, ledger, folder


def test_interrupted_goodbye_does_not_skip_filing_or_goodbye():
    player, ledger, folder = make_player()
    player._start_reading()
    player._cut = 0  # user interrupted final line to ask another question
    player.ask('What does that mean?')
    assert player.wait_idle(3)
    assert player.index == 0  # keep the interrupted ending available
    assert (folder / 'transcript.md').exists()  # filing never waits for goodbye
    player.play()
    assert player.wait_idle(3)
    assert any(e['kind'] == 'end' for e in library.events(folder))


def test_stream_keeps_librarian_tool_call():
    lesson = Lesson('A', [['Original']], [])
    data = {'then': 'pause', 'steps': [], 'librarian': {'action': 'explore', 'query': 'Anne Carson poetry original'}}
    stream = brain.StreamedAnswer(lambda: iter([json.dumps(data)]), lesson, None).start()
    assert list(stream) == []
    assert stream.librarian == data['librarian']


def test_side_conversation_stays_quiet_until_explicit_resume():
    player, ledger, folder = make_player()
    player.ask('我不是在和你说话，你先不用管我。')
    assert player.wait_idle(3)
    player.ask('这是我和另一个人的聊天。')
    assert player.wait_idle(3)
    assert not player.history and not player.playing
    assert len([e for e in library.events(folder) if e['kind']=='utterance']) == 2
    player.ask('回来吧，继续')
    assert player.wait_idle(3)
    assert not player.quiet


def navigator_for(player, ledger, client=None):
    from bibliothecary.navigation import Navigator
    opened=[]
    def open_reading(name):
        folder=library.readings_dir()/name
        lesson=Lesson.load(folder/'lesson.json')
        player.load(lesson, record=Ledger(folder,lesson).record)
        opened.append(name)
        return True
    room=SimpleNamespace(room=SimpleNamespace(player=player),client=client,open=open_reading)
    nav=Navigator(room)
    jobs=[]
    nav.submit=lambda kind,data,key=None:jobs.append(data)
    return nav,jobs,opened


def test_original_request_uses_exact_source_and_different_work_queues_real_job():
    player,ledger,folder=make_player()
    nav,jobs,opened=navigator_for(player,ledger)
    player.focus='p1.s1'
    assert nav.direct('我要看这句原文')=='这一句原文是：First original sentence.'
    assert not jobs
    reply=nav.direct('我要他的诗歌本身，不是介绍')
    assert len(jobs)==1 and jobs[0]['original']
    assert '找到后' in reply and not player.playing
    assert jobs[0]['reading']==folder.name


def test_semantic_tool_is_executed_instead_of_falling_back_to_old_script():
    player,ledger,folder=make_player(lambda *args: {'then':'pause','steps':[], 'librarian':{'action':'explore','query':'another work','original':True}})
    nav,jobs,opened=navigator_for(player,ledger)
    player.ask('好，就读你刚说的那首')
    assert player.wait_idle(3)
    assert len(jobs)==1 and jobs[0]['query']=='another work'
    assert player.index==0 and not player.playing


def test_late_detour_cannot_hijack_new_reading_and_return_restores_checkpoint(monkeypatch):
    player,ledger,folder=make_player()
    nav,jobs,opened=navigator_for(player,ledger)
    other=library.new_reading(Lesson('Poem',[['A real poem.']],[Step(say='A real poem.',focus='p1.s1')]))
    monkeypatch.setattr(nav,'prepare_query',lambda data:other)
    nav.execute({'action':'explore','query':'poetry'},'read it')
    nav.run(jobs[-1]);assert player.wait_idle(3)
    assert opened==[other.name]
    assert nav.store.get('reading_connection',other.name)['from']==folder.name
    nav.execute({'action':'return'},'back');assert player.wait_idle(3)
    assert opened[-1]==folder.name
    nav.execute({'action':'explore','query':'other'},'other')
    stale=jobs[-1]
    player.load(Lesson('Elsewhere',[['Elsewhere']],[]));assert player.wait_idle(3)
    nav.run(stale);assert player.wait_idle(3)
    assert opened==[other.name,folder.name]


def test_source_request_never_reveals_unread_future():
    player,ledger,folder=make_player()
    player.lesson.guide='NO SPOILERS'
    # Protection uses reading mode metadata; exercise its actual boundary.
    player.lesson.no_spoilers=True
    from unittest.mock import patch
    nav,jobs,_=navigator_for(player,ledger)
    visible=Lesson('Visible',[['First original sentence.']],[])
    with patch.object(brain,'bounded',return_value=visible):
        assert '还没有读到' in nav.execute({'action':'source','focus':'p1.s2'},'原文')
    assert not any(e.get('text')=='Second sentence.' for e in library.events(folder))


def test_idle_and_early_finish_file_without_marking_unread_content_complete():
    player,ledger,folder=make_player()
    ledger.capture_utterance('text','p1.s1')('童年的事情也要留下。')
    ledger.file_idle()
    assert '童年的事情' in (folder/'transcript.md').read_text()
    assert library.status(folder)!='read'
    nav,_,_=navigator_for(player,ledger)
    assert '晚安' in nav.direct('今晚到这里吧')
    assert any(e['kind']=='session_end' for e in library.events(folder))
    assert library.status(folder)!='read'
    assert player.quiet


def test_notes_adjust_behavior_only_with_reader_evidence_and_are_idempotent():
    from bibliothecary import adaptation
    player,ledger,folder=make_player()
    ledger.capture_utterance('text',None)('我希望先读原文，再顺着问题多聊一点。')
    ledger.capture_utterance('text',None)('小时候我和奶奶住在一起。')
    class Client:
        calls=0
        def chat_json(self,system,user):
            self.calls+=1
            rows=json.loads(user)['turns']
            return {'adjustments':[
                {'style':'source_first','source_id':rows[0]['id'],'evidence':'先读原文'},
                {'style':'execute_shell','source_id':rows[1]['id'],'evidence':'奶奶'},
                {'style':'depth','source_id':'invented','evidence':'假的'}],
                'interests':[{'query':'poetry and religion','source_id':rows[0]['id'],'evidence':'顺着问题'}]}
    client=Client();data=adaptation.analyze(folder,client)
    assert len(data['adjustments'])==1
    assert 'exact source passage' in adaptation.context()
    assert '奶奶' not in adaptation.context()
    adaptation.analyze(folder,client)
    assert client.calls==1
    assert adaptation.leads()[0]['basis']=='tentative_interest'


def test_exploration_rejects_review_and_opens_only_verified_body(monkeypatch):
    from bibliothecary import collection
    class Client:
        def chat_json(self,system,user):
            if 'public author' in system:return {'query':'A poet original poem'}
            return {'matches':json.loads(user)['title']=='Poem'}
        def web_search(self,query):
            return {'sources':[{'url':'https://example.test/review'},{'url':'https://example.test/poem'}]}
    player,ledger,folder=make_player()
    nav,_,_=navigator_for(player,ledger,Client())
    monkeypatch.setattr(collection,'cached_article',lambda url:('Poem' if url.endswith('poem') else 'Review', 'These are retrieved source words. '*10,url))
    result=nav.prepare_query({'query':'read the poem','original':True})
    lesson=Lesson.load(result/'lesson.json')
    assert lesson.title=='Poem' and lesson.source.endswith('/poem')
    assert all(s.say==lesson.sentence(s.focus) for s in lesson.steps)


def test_forgetting_interaction_memory_removes_derived_guidance():
    from bibliothecary import adaptation
    from bibliothecary.store import Store
    store=Store()
    number=store.memory('交互偏好：source_first',category='interaction')
    store.put('adaptation','reading',{'adjustments':[{'style':'source_first','memory':number,'at':'2026-01-01','source':'reading#turn-1'}]})
    assert adaptation.context()
    store.revise_memory(number)
    assert not adaptation.context()


def test_slow_summary_does_not_block_pause_or_raw_transcript(monkeypatch):
    from bibliothecary import report, adaptation
    player,ledger,folder=make_player()
    entered=threading.Event();release=threading.Event()
    real_write=report.write
    def slow(folder,client=None):
        if client:entered.set();release.wait(3)
        return real_write(folder)
    monkeypatch.setattr(report,'write',slow)
    monkeypatch.setattr(adaptation,'analyze',lambda *a:None)
    ledger.client=object()
    ledger.capture_utterance('text',None)('第一句')
    ledger._write_report_later();assert entered.wait(1)
    ledger.capture_utterance('text',None)('后台整理时我又说了一句')
    player.pause();assert player.wait_idle(.8)
    assert '后台整理时我又说了一句' in (folder/'transcript.md').read_text()
    release.set();ledger.close()


def test_partial_report_delivers_again_after_more_discussion():
    import datetime as dt
    from bibliothecary.telegram import Librarian
    player,ledger,folder=make_player()
    bot=SimpleNamespace(send_file=lambda *a:files.append(a),send=lambda *a:None)
    files=[]
    librarian=Librarian(bot,now=lambda:dt.datetime(2026,10,9,2,0).astimezone())
    librarian.state.update(chat=111,introduced=True,watching=True)
    # Owner key used by existing Telegram state.
    librarian.state['owner']=111
    ledger.record('session_idle')
    librarian.tick();librarian.tick()
    assert len(files)==1
    ledger.capture_utterance('text',None)('后来又想到了这一点')
    ledger.record('session_end')
    librarian.tick();librarian.tick()
    assert len(files)==2
    assert '后来又想到了这一点' in (folder/'report.md').read_text()


def test_pause_snapshot_does_not_prevent_idle_delivery_or_duplicate_goodnight():
    player,ledger,folder=make_player()
    ledger.capture_utterance('text',None)('我有一个想法。')
    ledger.record('discussion_pause')
    ledger.file_idle()
    assert sum(e['kind']=='session_idle' for e in library.events(folder))==1
    ledger.file_idle()
    assert sum(e['kind']=='session_idle' for e in library.events(folder))==1
    ledger.capture_utterance('text',None)('晚安。')
    ledger.record('session_end')
    ledger.companion('晚安。',None,'explanation')
    ledger.file_idle()
    assert sum(e['kind']=='session_idle' for e in library.events(folder))==1


def test_bare_original_request_is_resolved_in_context_not_forced_to_current_interview():
    player,ledger,folder=make_player()
    nav,jobs,_=navigator_for(player,ledger)
    player.history=[{'q':'她的诗歌本身呢？','a':'可以读她的一首诗。'}]
    assert nav.direct('你直接给我原文。') is None  # semantic tool resolves the reference
    assert not jobs


def test_requested_web_search_is_required_and_keeps_uncited_source_links():
    from margin.llm import OpenAICompatible
    client=OpenAICompatible(api_key='test-placeholder')
    bodies=[]
    def post(path,body,ctype):
        bodies.append(json.loads(body))
        return json.dumps({'output':[{'type':'web_search_call','action':{'sources':[{'type':'url','url':'https://example.test/original','title':'Original'}]}},{'type':'message','content':[{'type':'output_text','text':'Found source.','annotations':[]}]}]}).encode()
    client._post=post
    found=client.web_search('Find an original work')
    assert bodies[0]['tool_choice']=='required'
    assert found['sources'][0]['url']=='https://example.test/original'
