"""A shared catalogue, deterministic exclusion and reusable article extraction."""
from __future__ import annotations
import datetime as dt
import hashlib
import shlex
from pathlib import Path
from . import library, safe
from .store import Store, canonical, tokens, stamp
from margin.lesson import Lesson


def items(store=None):
    store=store or Store(); out=[]
    for folder in library.readings():
        try: lesson=Lesson.load(folder/'lesson.json')
        except (OSError,ValueError,KeyError): continue
        marker=safe.read_json(folder/'book.json')
        summary=store.get('summary',folder.name) or safe.read_json(folder/'summary.json')
        text='\n'.join(' '.join(p) for p in lesson.paragraphs)
        row={'id':folder.name,'title':lesson.title,'source':lesson.source,'url':canonical(lesson.source),
             'kind':'book' if marker else 'paper' if any(x in lesson.source for x in ('arxiv','doi.org','.pdf')) else 'article',
             'language':lesson.language,'status':library.status(folder),'mode':marker.get('mode','digest'),
             'topics':summary.get('concepts',[]), 'difficulty':'unassessed',
             'minutes':max(1,round(len(text)/(400 if lesson.language.startswith('zh') else 900))),
             'fingerprint':hashlib.sha256(' '.join(text.split()).encode()).hexdigest()}
        if marker:
            book=store.get('book',marker.get('book',''))
            if book.get('status')=='paused': row['status']='paused'
        custom=store.get('catalogue',row['id'])
        row.update({k:v for k,v in custom.items() if k in ('topics','difficulty','minutes')})
        out.append(row)
    # Include books not prepared yet.
    present={safe.read_json(f/'book.json').get('book') for f in library.readings()}
    for key,book in store.all('book'):
        if key in present: continue
        out.append({'id':'book:'+key,'title':book['title'],'kind':'book','source':book.get('source',''),
                    'url':canonical(book.get('source','')),'language':book.get('language',''),'mode':book.get('mode','text'),
                    'status':book.get('status','reading'),'topics':[],'difficulty':'unassessed','minutes':20})
    return out


def acceptable(url, store=None):
    store=store or Store(); key=canonical(url)
    if store.get('rejected',key): return False
    return not any(row['url']==key and row['status'] in ('read','paused','started','prepared') for row in items(store))


def reject(url, reason='', store=None):
    (store or Store()).put('rejected',canonical(url),{'reason':reason,'at':stamp()})


def cached_article(where):
    from margin.ingest import load_article
    if not where.startswith(('http://','https://')): return load_article(where)
    store=Store(); key=canonical(where); entry=store.get('article_cache',key)
    if entry and dt.datetime.fromisoformat(entry['expires'])>dt.datetime.now(dt.timezone.utc):
        return entry['title'],entry['text'],where
    title,text,source=load_article(where)
    store.put('article_cache',key,{'title':title,'text':text,'source':source,
        'expires':(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=1)).isoformat()})
    return title,text,source


def search(query, store=None):
    filters={}; words=[]
    for part in shlex.split(query):
        key,sep,value=part.partition('=')
        if sep: filters[key]=value
        else: words.append(part)
    allowed={'status','kind','language','mode','difficulty','source','topic','minutes'}
    if set(filters)-allowed: raise ValueError('筛选项：'+', '.join(sorted(allowed)))
    result=[]; wanted=tokens(' '.join(words))
    for row in items(store):
        if wanted and not wanted & tokens(row['title']+' '+' '.join(row['topics'])): continue
        keep=True
        for k,v in filters.items():
            if k=='minutes': keep=keep and row['minutes']<=int(v)
            elif k=='topic': keep=keep and v.lower() in ' '.join(row['topics']).lower()
            elif k=='source': keep=keep and v.lower() in row['source'].lower()
            else: keep=keep and row.get(k)==v
        if keep: result.append(row)
    return result


def command(store,text):
    head,_,arg=text.partition(' ')
    if head=='/reject':
        url,_,why=arg.partition(' ')
        if not url: raise ValueError('/reject 链接 不想读的原因')
        reject(url,why,store); return '记下了，不再主动推荐这篇。'
    if head=='/less':
        if not arg: raise ValueError('/less 希望少推荐的主题')
        store.memory('少推荐：'+arg,category='preference',basis='explicit',source='reader command')
        store.export_profile(); return '会减少这个方向的推荐。'
    if text.startswith('少推这个方向：'): return command(store,'/less '+text.partition('：')[2])
    if head=='/shelf':
        rows=search(arg,store)
        return '\n'.join(f"{r['id']} · {r['title']} [{r['status']}; {r['mode']}; {r['language']}; 约{r['minutes']}分钟; 难度:{r['difficulty']}]" for r in rows[:20]) or '没有匹配的馆藏。可用 status=read language=zh-CN minutes=20 等条件。'
    if head=='/tag':
        key,_,rest=arg.partition(' ')
        if key not in {r['id'] for r in items(store)}: raise ValueError('先用 /shelf 找到条目编号')
        data=store.get('catalogue',key)
        for field in shlex.split(rest):
            k,sep,v=field.partition('=')
            if not sep or k not in ('topics','difficulty','minutes'): raise ValueError('支持 topics=主题1,主题2 difficulty=难度 minutes=分钟')
            data[k]=v.split(',') if k=='topics' else int(v) if k=='minutes' else v
        store.put('catalogue',key,data);return '馆藏标签已更新。'
    return None
