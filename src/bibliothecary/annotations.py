"""Annotations keep quotations, reader thoughts and model explanations separate."""
import uuid
from .store import Store, stamp
from . import safe

def save(folder, lesson, data):
    kind=data.get('kind','quote')
    if kind not in ('quote','thought','explanation'): raise ValueError('Unknown annotation kind')
    focus=str(data.get('focus','')); text=str(data.get('text','')).strip()
    if not text or len(text)>10000: raise ValueError('Annotation must contain 1–10000 characters')
    if focus not in lesson.sentence_ids(): raise ValueError('Select a sentence in this reading')
    original=lesson.sentence(focus)
    if kind=='quote' and text not in original: raise ValueError('A quotation must match the original sentence exactly')
    entry={'id':uuid.uuid4().hex[:12],'reading':folder.name,'kind':kind,'focus':focus,'text':text,
           'original':original,'source':lesson.source,'at':stamp(), 'basis':'reader_saved' if kind!='explanation' else 'model_explanation'}
    store=Store();store.put('annotation',entry['id'],entry)
    rows=listing(folder)
    safe.atomic(folder/'excerpts.md', '# 摘抄与想法\n\n'+'\n\n'.join(f"## {r['kind']} · {r['focus']}\n\n{r['text']}\n\n原文：{r['original']}\n\n来源：{r['source']}" for r in rows))
    return entry

def listing(folder):
    return [r for _,r in Store().all('annotation') if r['reading']==folder.name]
