def exact(a,b):
    if type(a) is not type(b):
        return False
    if isinstance(b,dict):
        return a.keys()==b.keys() and all(exact(a[k],v) for k,v in b.items())
    if isinstance(b,list):
        return len(a)==len(b) and all(exact(x,y) for x,y in zip(a,b))
    return a==b

def grade_answer(task, answer):
    ok=exact(answer,task['expected'])
    return {'passed':ok,'checks':{'exact_contract':ok}}


import json, random


def load_answer(text):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('duplicate key')
            result[k]=v
        return result
    def nonfinite(value):raise ValueError('nonfinite JSON')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=nonfinite)


def card(id,title,prompt,files,expected,motif):
    return dict(id=id,title=title,track='answer',prompt=prompt+'\nОтвет: один JSON-объект, без Markdown. Только объявленные ключи; без дополнительных. Порядок ключей не важен. Типы значений обязательны.',files=files,expected=expected,provenance={'motif_id':motif,'template_id':id,'status':'development'})


def build(seed=11):
    rng=random.Random(seed)
    a,b=f'req-{seed}-a',f'req-{seed}-b'
    events=[{'id':a,'status':'failed','message':'timeout'}, {'id':'noise','status':'ok','message':'failed'}, {'id':a,'status':'failed','message':'duplicate'}, {'id':b,'status':'failed','message':'error'}]
    for i in range(30):
        events.insert(rng.randrange(len(events)+1),{'id':f'ok-{i}','status':'ok','message':'failed in message'})
    # Build expected by first failed occurrence, solver uses a different approach.
    ids=[]
    for row in events:
        if row['status']=='failed' and row['id'] not in ids:ids.append(row['id'])
    return [card('Q01','Журнал: события и уникальные запросы','Прочитай events.jsonl. Считай только status == "failed", не текст message. failed_events — число строк таких событий (int), failed_ids — уникальные id ТОЛЬКО failed-событий в порядке первого появления (array of strings). Верни {"failed_events":integer,"failed_ids":[string,...]}.',{'events.jsonl':'\n'.join(json.dumps(x) for x in events)}, {'failed_events':3,'failed_ids':ids},'log-selection')]


def reference_answer(task):
    if task['id']=='Q01':
        rows=[json.loads(line) for line in task['files']['events.jsonl'].splitlines()]
        failed=[r for r in rows if r['status']=='failed']
        return {'failed_events':len(failed),'failed_ids':list(dict.fromkeys(r['id'] for r in failed))}
    raise ValueError('unknown task')
