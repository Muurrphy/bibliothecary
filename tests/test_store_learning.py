import datetime as dt
import json
import sqlite3
from bibliothecary.store import Store, canonical
from bibliothecary.learning import command, observe, due
from bibliothecary.desk import Desk
from bibliothecary import library
from bibliothecary.collection import acceptable, reject
from margin.lesson import Lesson


def test_migration_preserves_verbatim_and_is_repeatable(tmp_path):
    raw='{"who":"reader","text":"半年前我不懂什么是涌现","t":"2026-04-01"}\n'
    (tmp_path/'chat.jsonl').write_text(raw)
    (tmp_path/'reader.json').write_text(json.dumps({'notes':[{'text':'读科学书','t':'2026-04-01'}]}))
    first=Store(tmp_path); second=Store(tmp_path)
    assert first.events('chat')==second.events('chat') and len(first.events('chat'))==1
    manifest=first.get('system','migration')
    assert ( __import__('pathlib').Path(manifest['backup'])/'chat.jsonl').read_text()==raw
    assert first.memories()[0]['created']=='2026-04-01'
    assert first.retrieve('涌现')[0]['source'].startswith('chat#event-')


def test_correction_and_forgetting_never_reenter_context():
    desk=Desk(None); desk.remember('reader','我不喜欢科幻'); desk.learn(['我不喜欢科幻'])
    store=Store(); number=store.memories()[0]['id']
    store.revise_memory(number,'我现在想读科幻')
    desk.learn(['我不喜欢科幻'])
    assert '我不喜欢科幻' not in desk.context('科幻')
    assert '我现在想读科幻' in desk.context('科幻')
    new=store.memories()[0]['id']; store.revise_memory(new)
    assert store.memories()==[]
    assert store.events('chat')[0]['text']=='我不喜欢科幻'  # raw history is not destroyed


def test_reviews_distinguish_exposure_from_understanding():
    store=Store(); day=dt.date.today()
    observe(store,'book-one',{'question':'涌现是什么意思','answer':'...', 't':day.isoformat()})
    key,evidence=store.all('evidence')[0]
    assert evidence['mastery']=='unassessed'
    r=store.get('review',key); r['due']=day.isoformat();store.put('review',key,r)
    assert len(due(store,day))==1
    command(store,f'/review {key} 跳过',day)
    assert store.get('evidence',key)['mastery']=='unassessed'
    command(store,f'/review {key} 应用过 我在项目中用过',day)
    assert store.get('evidence',key)['mastery']=='self_reported_application'
    assert store.events('review')[0]['question']=='我在项目中用过'


def test_goals_plans_and_rest_are_shared_intents():
    store=Store()
    assert '目标' in command(store,'我想系统学习科学哲学')
    assert '科学哲学' in command(store,'/plan')
    assert '弹性阅读' in command(store,'今晚太累了')
    assert '明天' in command(store,'/review')


def test_jobs_survive_restart_and_do_not_resend_uncertain_delivery():
    store=Store(); key=store.enqueue('chat',{'text':'hello'},key='one')
    assert store.enqueue('chat',{'text':'hello'},key='one')==key
    assert store.claim()['id']==key and store.claim() is None
    store.recover(); assert store.jobs()[0]['status']=='uncertain'
    store.job_state(key,'pending');store.cancel(key)
    store.job_state(key,'succeeded')
    assert store.jobs()[0]['status']=='cancelled'


def test_link_canonicalization_and_rejection():
    assert canonical('http://Example.org/a/?utm_source=x#here')=='https://example.org/a'
    assert canonical('https://doi.org/10.1234/ABC')=='doi:10.1234/abc'
    assert canonical('https://arxiv.org/abs/2601.12345v2')==canonical('https://arxiv.org/pdf/2601.12345.pdf')
    reject('https://example.org/a')
    assert not acceptable('https://example.org/a?utm_medium=tracking')


def test_backup_restores_records(tmp_path):
    store=Store();store.append('chat',{'who':'reader','text':'original'})
    destination=tmp_path/'export'
    store.backup(destination)
    recovered=Store(destination)
    assert recovered.events('chat')==store.events('chat')
    with recovered.connect() as db: assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
