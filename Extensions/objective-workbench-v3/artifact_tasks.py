from pathlib import Path
from contextlib import closing
import json,hashlib,csv,io

def build(seed):
    files={'worker.ini':'# Worker\ntimeout_s = 20\nmode = safe\n','other.ini':'timeout_s = 20\n'}
    edit=dict(id='S01',title='Точечная правка',track='artifact',prompt='В worker.ini замени ровно строку timeout_s = 20 на timeout_s = 35. Другие байты обоих файлов и их имена сохрани. Новые файлы не создавай. Способ правки любой.',files=files,expected={**files,'worker.ini':files['worker.ini'].replace('20','35')},provenance={'motif_id':'scoped-edit','template_id':'S01'})
    clients=[(i, f'c{i}', '' if i%2==0 else f'old{i}@example.test') for i in range(1,13)]
    updates=[(i,f'new{i}-{seed}@example.test') for i in range(1,6)]
    importer='''import sqlite3,csv,sys
if sys.argv[1:] != ['--fill-empty-only']: raise SystemExit('use --fill-empty-only')
with sqlite3.connect('data.db') as db:
    for r in csv.DictReader(open('updates.csv',newline='')):
        db.execute("UPDATE clients SET email=? WHERE id=? AND email=''",(r['email'],int(r['id'])))
'''
    expclients=[list(r) for r in clients]
    for i,email in updates:
        if not expclients[i-1][2]:expclients[i-1][2]=email
    schema=['CREATE TABLE clients(id INTEGER PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL)','CREATE TABLE orders(id INTEGER PRIMARY KEY,client_id INTEGER REFERENCES clients(id),amount INTEGER NOT NULL)']
    text='id,email\n'+''.join(f'{i},{e}\n' for i,e in updates)
    imp=dict(id='S02',title='Готовый импорт SQLite',track='artifact',prompt='Примени готовый importer.py командой python3 importer.py --fill-empty-only к data.db из текущей папки. Он обновляет только пустые email по updates.csv. Повтори ту же команду для проверки идемпотентности. Сохрани ID/имена/непустые email/orders и всю схему БД, importer.py и updates.csv побайтно. Разрешено менять только data.db, новые файлы к завершению отсутствуют. Итог оценивается по состоянию, факт повторного запуска этой проверкой НЕ подтверждается.',files={'importer.py':importer,'updates.csv':text},initial={'clients':clients,'orders':[(i,i,seed*10+i) for i in range(1,13)],'schema':schema},expected={'clients':expclients,'orders':[[i,i,seed*10+i] for i in range(1,13)],'schema':schema},provenance={'motif_id':'sqlite-fill-empty','template_id':'S02'})
    data={f'data/f{i:02}.txt':f'content {seed} {i}\n' for i in range(24)}
    allowed=[f'data/f{i:02}.txt' for i in (1,3,5,7,9,11,13)]
    cleanup=dict(id='S03',title='Архив и ограниченная очистка',track='artifact',prompt='manifest.json задаёт7файлов для очистки. Создай archive.tar (обычный несжатый tar) в корне workspace, с ровно этими7обычными файлами, относительные имена как в manifest, содержимое побайтно исходное; порядок/mtime/права tar не важны. Затем удали только эти файлы из data/. Остальные данные и manifest.json сохрани побайтно. Никаких иных файлов. Проверяется итог, НЕ порядок архивации и удаления; без доверенного trace нельзя доказать временную последовательность.',files={**data,'manifest.json':json.dumps(allowed)},expected={'allowed':allowed,'original':data},provenance={'motif_id':'archive-scoped-delete','template_id':'S03'})
    orders=[(f'o{i}',str(i%4),seed+i) for i in range(20)]
    ordercsv='id,region_id,amount_cents\n'+''.join(f'{a},{b},{c}\n' for a,b,c in orders)
    regioncsv='region_id,name\n0,North\n1,South\n2,East\n'
    groups={name:0 for name in ('North','South','East')};missing=[]
    for id,reg,amt in orders:
        if reg=='3':missing.append(id)
        else:groups[('North','South','East')[int(reg)]]+=amt
    report=dict(id='S04',title='Отчёт CSV по регионам',track='artifact',prompt='Прочитай orders.csv и regions.csv. Напиши report.json с ровно2ключами: totals — объект name региона → integer сумма amount_cents; unmatched — массив id заказов, чей region_id отсутствует в справочнике, в порядке исходного orders.csv. Все регионы справочника включить, даже при сумме0. Входы не меняй. Единственный новый файл report.json. JSON object key order и whitespace не важны. Это JSON/CSV-отчёт, не XLSX и не проверка Excel.',files={'orders.csv':ordercsv,'regions.csv':regioncsv},expected={'totals':groups,'unmatched':missing},provenance={'motif_id':'region-join-report','template_id':'S04'})
    return [edit,imp,cleanup,report]

def setup(task,workspace):
    import sqlite3
    w=Path(workspace);w.mkdir(parents=True,exist_ok=True)
    if any(w.iterdir()):raise ValueError('workspace must be empty')
    for name,content in task['files'].items():
        p=w/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content,encoding='utf-8')
    if task['id']=='S02':
        with closing(sqlite3.connect(w/'data.db')) as db, db:
            for sql in task['initial']['schema']:db.execute(sql)
            db.executemany('INSERT INTO clients VALUES(?,?,?)',task['initial']['clients'])
            db.executemany('INSERT INTO orders VALUES(?,?,?)',task['initial']['orders'])

def grade(task,workspace):
    import sqlite3,tarfile
    from bench import exact,load_answer
    w=Path(workspace);checks={}
    try:
        if w.is_symlink() or not w.is_dir():raise ValueError('unsafe root')
        items=list(w.rglob('*'))
        if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in items):raise ValueError('unsafe node')
        if sum(p.stat().st_size for p in items if p.is_file())>2_000_000:raise ValueError('too large')
        names={str(p.relative_to(w)) for p in items if p.is_file()}
        id=task['id'];exp=task['expected']
        if id=='S01':
            checks['inventory']=names==set(exp)
            checks['bytes']=all((w/n).read_bytes()==s.encode() for n,s in exp.items())
        else:
            protected=task['files'] if id!='S03' else {'manifest.json':task['files']['manifest.json']}
            checks['protected']=all((w/n).read_bytes()==s.encode() for n,s in protected.items())
            if id=='S02':
                checks['inventory']=names==set(task['files'])|{'data.db'}
                with closing(sqlite3.connect((w/'data.db').resolve().as_uri()+'?mode=ro',uri=True)) as db:
                    db.execute('PRAGMA trusted_schema=OFF')
                    schema=[r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name")]
                    checks['schema']=schema==exp['schema']
                    if checks['schema']:
                        checks['clients']=exact([list(r) for r in db.execute('SELECT * FROM clients ORDER BY id')],exp['clients'])
                        checks['orders']=exact([list(r) for r in db.execute('SELECT * FROM orders ORDER BY id')],exp['orders'])
                        checks['fk']=not list(db.execute('PRAGMA foreign_key_check'))
            elif id=='S03':
                remaining=set(exp['original'])-set(exp['allowed'])
                checks['inventory']=names==remaining|{'manifest.json','archive.tar'}
                checks['remaining']=all((w/n).read_bytes()==exp['original'][n].encode() for n in remaining)
                with tarfile.open(w/'archive.tar','r:') as tf:
                    members=tf.getmembers();membernames=[m.name for m in members]
                    checks['archive_members']=len(members)==len(exp['allowed']) and set(membernames)==set(exp['allowed']) and all(m.isfile() for m in members)
                    checks['archive_bytes']=checks['archive_members'] and all(tf.extractfile(m).read()==exp['original'][m.name].encode() for m in members)
            elif id=='S04':
                checks['inventory']=names==set(task['files'])|{'report.json'}
                checks['report']=exact(load_answer((w/'report.json').read_text()),exp)
        return {'passed':bool(checks) and all(checks.values()),'checks':checks}
    except (OSError,ValueError,KeyError,sqlite3.Error,tarfile.TarError,UnicodeError):
        checks['readable_valid_artifacts']=False
        return {'passed':False,'checks':checks}


def reference(task,workspace):
    import sqlite3,subprocess,sys,tarfile
    w=Path(workspace);id=task['id']
    if id=='S01':
        p=w/'worker.ini';p.write_text(p.read_text().replace('timeout_s = 20','timeout_s = 35'))
    elif id=='S02':
        for _ in range(2):subprocess.run([sys.executable,'importer.py','--fill-empty-only'],cwd=w,check=True,timeout=10)
    elif id=='S03':
        names=json.loads((w/'manifest.json').read_text())
        with tarfile.open(w/'archive.tar','w') as tf:
            for name in names:tf.add(w/name,arcname=name,recursive=False)
        for name in names:(w/name).unlink()
    elif id=='S04':
        with (w/'regions.csv').open() as f:regions={r['region_id']:r['name'] for r in csv.DictReader(f)}
        totals={name:0 for name in regions.values()};unmatched=[]
        with (w/'orders.csv').open() as f:
            for row in csv.DictReader(f):
                if row['region_id'] in regions:totals[regions[row['region_id']]]+=int(row['amount_cents'])
                else:unmatched.append(row['id'])
        (w/'report.json').write_text(json.dumps({'totals':totals,'unmatched':unmatched}))
