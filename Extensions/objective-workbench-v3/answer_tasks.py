import json
from decimal import Decimal,ROUND_HALF_EVEN

def build(seed):
    # Expected values calculated at fixture construction, never included in public packages.
    rows=[{'id':'a','qty':1,'unit':'0.025'},{'id':'b','qty':3,'unit':'0.015'},{'id':'c','qty':2,'unit':str(seed)+'.125'}]
    totals=[(Decimal(r['unit'])*r['qty']).quantize(Decimal('.01'),rounding=ROUND_HALF_EVEN) for r in rows]
    invoice={'id':'Q02','title':'Счёт: точное округление','track':'answer','prompt':'В invoice.json цены заданы десятичными строками в RUB. Для каждой строки умножь qty на unit и округли HALF_EVEN до двух десятичных знаков. Затем сложи уже округлённые строки. Верни JSON {"line_totals":["0.00",...],"total":"0.00","currency":"RUB"}; порядок line_totals как во входе. Все суммы — строки с ровно2знаками, только эти3ключа. Других оценок/письма не требуется.','files':{'invoice.json':json.dumps(rows)},'expected':{'line_totals':[format(x,'.2f') for x in totals],'total':format(sum(totals),'.2f'),'currency':'RUB'},'provenance':{'motif_id':'decimal-line-half-even','template_id':'Q02'}}
    sources={'s1':{'author':'A','quote':f'Сначала проверь {seed} фактов.'},'s2':{'author':'B','quote':'Пауза не равна ответу.'},'s3':{'author':'C','quote':'Число без основания — догадка.'}}
    candidates=[{'id':'q1','author':'A','quote':sources['s1']['quote'],'source':'s1'},{'id':'q2','author':'A','quote':sources['s2']['quote'],'source':'s2'},{'id':'q3','author':'C','quote':sources['s3']['quote'],'source':'s3'},{'id':'q4','author':'B','quote':sources['s2']['quote'],'source':'s2'},{'id':'q5','author':'A','quote':'Неподтверждённое высказывание.','source':'s1'}]
    quotes={'id':'Q03','title':'Отбор подтверждённых цитат','track':'answer','prompt':'Из candidates.json выбери ВСЕ новые подтверждённые цитаты: author и quote должны точно совпадать с записью source в sources.json. В published.json указаны уже опубликованные source IDs: исключи их. Верни {"selected":[{"id":string,"source":string,"quote":string},...]}, selected сортировать id ASC. Не исправляй атрибуцию, ничего не добавляй; единственный ключ selected.','files':{'sources.json':json.dumps(sources,ensure_ascii=False),'candidates.json':json.dumps(candidates,ensure_ascii=False),'published.json':'["s3"]'},'expected':{'selected':[{'id':'q1','source':'s1','quote':sources['s1']['quote']},{'id':'q4','source':'s2','quote':sources['s2']['quote']}]},'provenance':{'motif_id':'source-exact-match','template_id':'Q03'}}
    base=seed+10; updated=seed+20
    doclines=[f'S{i:03}: Служебная запись, отдельного лимита не устанавливает.' for i in range(1,401)]
    doclines.insert(21,f'R1: retry_limit = {base}.')
    doclines.insert(201,f'R2: Для retry_limit вместо R1 действует {updated}.')
    doclines.insert(351,'R3: timeout_s = 45.')
    qa={'id':'Q04','title':'Документ: поздняя редакция и неизвестное','track':'answer','prompt':'По spec.txt верни {"retry_limit":{"value":integer,"source":string},"timeout_s":{"value":integer,"source":string},"region":{"value":null,"source":null}}. Для retry_limit позднее явное замещение R2 отменяет R1; служебные строки ничего не устанавливают. Для поля, не указанного нигде, value и source равны null; не угадывай. source — ID строки (до двоеточия), не её текст. Только3ключа, у каждого ровно value/source.','files':{'spec.txt':'\n'.join(doclines)},'expected':{'retry_limit':{'value':updated,'source':'R2'},'timeout_s':{'value':45,'source':'R3'},'region':{'value':None,'source':None}},'provenance':{'motif_id':'amendment-priority','template_id':'Q04'}}
    facts={'one':{'workers':seed,'region':'north'},'two':{'deadline':'2026-11-18'},'three':None}
    partial={'id':'Q05','title':'Частичный результат без выдумки','track':'answer','prompt':'available.json — результаты чтения источников. null означает, что источник недоступен, других фактов о нём нет. Заполни {"workers":{"value":integer,"source":"one"},"region":{"value":string,"source":"one"},"deadline":{"value":string,"source":"two"},"budget":{"value":null,"source":null},"missing_sources":["three"]}. budget известен только из недоступного three, поэтому null. Только перечисленные5ключей, во вложенных объектах только value/source. Полезный частичный ответ и есть полный результат задания.','files':{'available.json':json.dumps(facts)},'expected':{'workers':{'value':seed,'source':'one'},'region':{'value':'north','source':'one'},'deadline':{'value':'2026-11-18','source':'two'},'budget':{'value':None,'source':None},'missing_sources':['three']},'provenance':{'motif_id':'explicit-missing-source','template_id':'Q05'}}
    events=[{'id':'historical','rid':'other','at':'2026-11-14T23:59:00+00:00','code':401},{'id':'a','rid':f'r{seed}','at':'2026-11-15T08:00:00+08:00','code':200},{'id':'b','rid':f'r{seed}','at':'2026-11-15T00:00:01+00:00','code':429},{'id':'c','rid':f'r{seed}','at':'2026-11-15T03:00:02+03:00','code':503}]
    timeline={'id':'Q06','title':'Корреляция времени без догадки о причине','track':'answer','prompt':f'Выбери события rid == "r{seed}" из events.json. Нормализуй aware ISO timestamps к UTC, отсортируй по времени ASC (при равенстве id ASC). Верни {{"event_ids":[string,...],"utc":["YYYY-MM-DDTHH:MM:SSZ",...],"codes":[integer,...]}} в одном порядке. Только3ключа. Не устанавливай корневую причину по HTTP-коду: она не запрашивается и во входе не доказана.','files':{'events.json':json.dumps(events[::-1])},'expected':{'event_ids':['a','b','c'],'utc':['2026-11-15T00:00:00Z','2026-11-15T00:00:01Z','2026-11-15T00:00:02Z'],'codes':[200,429,503]},'provenance':{'motif_id':'aware-time-correlation','template_id':'Q06'}}
    return [invoice,quotes,qa,partial,timeline]

def reference(task):
    from datetime import datetime,timezone
    import re
    f=task['files']; id=task['id']
    if id=='Q02':
        # Integer rational arithmetic independent of generator Decimal oracle.
        vals=[]
        for r in json.loads(f['invoice.json']):
            d=Decimal(r['unit']); num,den=d.as_integer_ratio()
            q,rem=divmod(num*r['qty']*100,den)
            if 2*rem>den or (2*rem==den and q%2):q+=1
            vals.append(q)
        money=lambda n:f'{n//100}.{n%100:02d}'
        return {'line_totals':[money(v) for v in vals],'total':money(sum(vals)),'currency':'RUB'}
    if id=='Q03':
        src=json.loads(f['sources.json']); published=json.loads(f['published.json'])
        chosen=[]
        for c in json.loads(f['candidates.json']):
            if c['source'] in published:continue
            s=src[c['source']]
            if (s['author'],s['quote'])==(c['author'],c['quote']):chosen.append({k:c[k] for k in ('id','source','quote')})
        return {'selected':sorted(chosen,key=lambda c:c['id'])}
    if id=='Q04':
        lines=f['spec.txt'].splitlines();out={k:{'value':None,'source':None} for k in ('retry_limit','timeout_s','region')}
        for line in lines:
            if line.startswith('R2:'):
                out['retry_limit']={'value':int(re.findall(r'\d+',line)[-1]),'source':'R2'}
            elif line.startswith('R3:'):
                out['timeout_s']={'value':int(line.split('=')[1].strip(' .')),'source':'R3'}
        return out
    if id=='Q05':
        src=json.loads(f['available.json']);out={}
        for field in ('workers','region','deadline','budget'):
            found=[(sid,data[field]) for sid,data in src.items() if data and field in data]
            out[field]={'value':found[0][1],'source':found[0][0]} if found else {'value':None,'source':None}
        out['missing_sources']=sorted(k for k,v in src.items() if v is None)
        return out
    if id=='Q06':
        rid=re.search(r'rid == "([^"]+)"',task['prompt'])[1]
        rows=[r for r in json.loads(f['events.json']) if r['rid']==rid]
        rows.sort(key=lambda r:(datetime.fromisoformat(r['at']),r['id']))
        return {'event_ids':[r['id'] for r in rows],'utc':[datetime.fromisoformat(r['at']).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') for r in rows],'codes':[r['code'] for r in rows]}
    raise ValueError(id)
