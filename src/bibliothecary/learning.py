"""Evidence-led learning: hearing something is not evidence of understanding."""
from __future__ import annotations
import datetime as dt
import re
import uuid
from .store import Store, stamp

RHYTHM = ('goal','explore','goal','explore','goal','review','flex')
LABELS = {'goal':'目标阅读','explore':'自由探索','review':'回顾','flex':'弹性阅读'}
INTERVALS = (1,3,7,14)


def local_day(store):
    from zoneinfo import ZoneInfo
    zone = store.get('settings','telegram').get('timezone')
    return dt.datetime.now(ZoneInfo(zone)).date() if zone else dt.date.today()


def schedule(store, day):
    override = store.get('plan',day.isoformat())
    return override.get('mode') or RHYTHM[day.weekday()]


def observe(store: Store, reading, event):
    # Preserve the observed behaviour, never infer mastery from completion or silence.
    if event.get('review'):
        kind='answered'
        text=event['review']
    else:
        text=event.get('question','')
        kind='asked' if re.search(r'[?？]|为什么|什么|怎么|哪|是否|是不是|\b(?:why|what|how|where|who|when)\b',text,re.I) else 'comment'
    key=uuid.uuid4().hex[:12]
    store.put('evidence',key,{'reading':reading,'kind':kind,'question':text,'answer':event.get('question') if kind=='answered' else None,
        'response':event.get('answer'),'focus':event.get('focus'),'at':event.get('t',stamp()),'mastery':'unassessed'})
    if kind=='asked' and text:
        store.put('review',key,{'question':text,'source':reading,'focus':event.get('focus'), 'stage':0,
            'due':(local_day(store)+dt.timedelta(days=1)).isoformat(),'status':'active','evidence':key})


def goal(store, text):
    key=uuid.uuid4().hex[:8]
    store.put('goal',key,{'question':text,'status':'active','created':stamp(), 'basis':'explicit',
                        'foundation':[], 'open_questions':[text], 'next_material':None,'evidence':[]})
    store.memory(text,category='goal',source='goal:'+key,basis='explicit')
    return key


def due(store, day):
    key=day.isoformat()
    shown=store.get('review_day',key)
    if shown:
        return [(k,store.get('review',k)) for k in shown['ids'] if store.get('review',k).get('due','')<=key]
    rows=[(k,r) for k,r in store.all('review') if r.get('status')=='active' and r.get('due','')<=key][:2]
    if rows: store.put('review_day',key,{'ids':[k for k,_ in rows]})
    return rows


def review_answer(store, key, judgement, day):
    item=store.get('review',key)
    if not item: raise ValueError('没有这道复习题')
    if judgement not in ('懂了','不懂','跳过','应用过','understood','again','skip','applied'):
        raise ValueError('使用 懂了 / 不懂 / 跳过 / 应用过，后面可以补充你的回答')
    skip=judgement in ('跳过','skip'); again=judgement in ('不懂','again')
    stage=item.get('stage',0)
    if not skip: stage=0 if again else min(stage+1,3)
    item.update(stage=stage,due=(day+dt.timedelta(days=1 if skip else INTERVALS[stage])).isoformat(),
                last_judgement=judgement,assessed_by='reader')
    store.put('review',key,item)
    evidence=store.get('evidence',item.get('evidence',''))
    if evidence and not skip:
        evidence['mastery']='needs_work' if again else ('self_reported_application' if judgement in ('应用过','applied') else 'self_reported_understanding')
        store.put('evidence',item['evidence'],evidence)


def plan_context(store, day):
    goals=[(k,g) for k,g in store.all('goal') if g.get('status')=='active']
    override=store.get('plan',day.isoformat())
    mode=override.get('mode') or RHYTHM[day.weekday()]
    return ('Today: '+LABELS.get(mode,mode)+'. '+override.get('note','')+'\nExplicit active goals:\n'+
            '\n'.join(f"{k}: {g['question']}; known foundation: {g.get('foundation',[])}; open questions: {g.get('open_questions',[])}; next material: {g.get('next_material')}" for k,g in goals)+
            '\nNever call an exposure or a skipped review mastery. Free exploration and rest remain legitimate choices.')


def weekly(store, day):
    since=(day-dt.timedelta(days=7)).isoformat()
    evidence=[(k,e) for k,e in store.all('evidence') if e.get('at','')>=since]
    progressed=[e for _,e in evidence if e.get('mastery','').startswith('self_reported')]
    unresolved=[e for _,e in evidence if e.get('mastery') in ('unassessed','needs_work')]
    lines=['本周阅读回顾', '有理解或应用反馈的线索：']
    lines += [f"· {e['question']}（{e['mastery']}；{e['reading']}）" for e in progressed] or ['· 暂无明确反馈，不能据此认定已掌握。']
    lines += ['仍值得追问：']+[f"· {e['question']}（{e['reading']}）" for e in unresolved[:8]]
    lines += ['下周安排：继续当前目标与在读书，穿插两次自由探索；优先回顾上述未解问题。',plan_context(store,day)]
    return '\n'.join(lines)


def command(store, text, day=None):
    """Shared Telegram/CLI intent handler. None means normal librarian conversation."""
    day=day or local_day(store); text=text.strip()
    # Explicit natural-language actions, without allowing a model or book text to mutate goals.
    for prefix,cmd in [('我的学习目标是','/goals add '),('我想系统学习','/goals add '),('记住：','/profile add '),
                       ('忘记记忆 ','/profile forget '),('本周计划','/plan'),('开始复习','/review'),('本周回顾','/weekly')]:
        if text.startswith(prefix): text=cmd+text[len(prefix):].strip(); break
    if text in ('今晚太累了','今天太累','今晚休息'):
        store.put('plan',day.isoformat(),{'mode':'flex','note':'读者今天想轻松阅读或休息；不安排测试。'})
        return '今天改成弹性阅读，复习顺延，不补欠账。想读的话，我可以找一篇轻松的。'
    head,_,arg=text.partition(' ')
    if head=='/profile':
        action,_,tail=arg.partition(' ')
        if action in ('forget','忘记'):
            store.revise_memory(tail); return '这条记忆已停用，后续检索和推荐不再使用。原始记录保留供你查阅。'
        if action in ('edit','纠正'):
            number,_,replacement=tail.partition(' ')
            if not replacement: raise ValueError('/profile edit 编号 正确内容')
            store.revise_memory(number,replacement); return '已纠正；旧记忆不再参与推荐。'
        if action in ('add','记住'):
            if not tail: raise ValueError('/profile add 内容')
            store.memory(tail,basis='explicit',source='reader command');store.export_profile();return '记下了，标记为你明确告诉我的。'
        rows=store.memories()
        return '\n'.join(f"{r['id']}. {r['text']} [{r['basis']}; {r['created'][:10]}; {r['source']}]" for r in rows) or '还没有记忆。用 /profile add 添加，edit 纠正，forget 忘记。'
    if head=='/goals':
        action,_,tail=arg.partition(' ')
        if action in ('add','新增') and tail: return f'已建立目标 {goal(store,tail)}：{tail}。用 /plan 看安排。'
        if action in ('pause','resume','done'):
            item=store.get('goal',tail)
            if not item: raise ValueError('没有这个目标编号')
            item['status']={'pause':'paused','resume':'active','done':'complete'}[action];store.put('goal',tail,item);return '目标状态已更新。'
        if action in ('foundation','next','question','evidence'):
            key,_,value=tail.partition(' '); item=store.get('goal',key)
            if not item or not value: raise ValueError('/goals '+action+' 目标编号 内容')
            if action=='next': item['next_material']=value
            else: item.setdefault({'foundation':'foundation','question':'open_questions','evidence':'evidence'}[action],[]).append(value)
            store.put('goal',key,item);return '已更新学习路径。'
        return '\n'.join(f"{k} [{g['status']}] {g['question']}" for k,g in store.all('goal')) or '用 /goals add 你想持续解决的问题，建立学习路径。'
    if head=='/plan':
        if arg:
            store.put('plan',day.isoformat(),{'mode':'flex','note':arg});return '今天按你的选择安排：'+arg
        start=day-dt.timedelta(days=day.weekday())
        return '\n'.join(f"{(start+dt.timedelta(days=i)).isoformat()} · {LABELS[m]}" for i,m in enumerate(RHYTHM))+'\n'+plan_context(store,day)+'\n随时 /plan 今天想怎么读；跳过不会补欠账。'
    if head=='/review':
        if arg:
            key,_,rest=arg.partition(' '); judgement,_,answer=rest.partition(' ')
            review_answer(store,key,judgement,day)
            if answer: store.append('review',{'t':stamp(),'kind':'self_assessment','review':key,'question':answer,'judgement':judgement})
            return '已记录你的反馈并调整复习时间。'
        if store.get('plan',day.isoformat()).get('mode')=='flex': return '今天是弹性阅读，复习可以明天再来。'
        return '\n'.join(f"{k}: {r['question']}（{r['source']}）" for k,r in due(store,day))+'\n回答：/review 编号 懂了|不懂|跳过|应用过 你的解释' if due(store,day) else '今天没有到期的复习题。'
    if head=='/weekly': return weekly(store,day)
    return None
