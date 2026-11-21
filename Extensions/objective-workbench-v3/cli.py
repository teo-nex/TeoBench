import argparse,json,sys
from pathlib import Path
import bench,answer_tasks,artifact_tasks

GLOBAL_CONTRACT='Общий контракт: корректный JSON UTF-8 без duplicate keys/NaN/Infinity. Никаких дополнительных полей. Для artifact-задач разрешены обычные файлы/папки, без symlink/special nodes; общий размер файлов <=2000000байт, служебные логи вне workspace. Конечное состояние стабильно (процессы записи остановлены). Проверка не является security sandbox.'

def tasks(seed):return bench.build(seed)+answer_tasks.build(seed)+artifact_tasks.build(seed)

def emit(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['export','reference','grade']);p.add_argument('id',nargs='?');p.add_argument('--seed',type=int,default=11);p.add_argument('--out',type=Path);p.add_argument('--submission',type=Path);args=p.parse_args()
    corpus=tasks(args.seed)
    if args.command=='export':
        if args.out is None:p.error('--out required')
        if args.out.exists():p.error('output already exists; refusing overwrite')
        args.out.mkdir(parents=True)
        for t in corpus:
            dst=args.out/'public'/t['id'];dst.mkdir(parents=True)
            emit(dst/'task.json',{k:t[k] for k in ('id','title','track','prompt','provenance')})
            (dst/'CONTRACT.txt').write_text(GLOBAL_CONTRACT)
            if t['track']=='artifact':artifact_tasks.setup(t,dst/'workspace')
            else:
                for name,content in t['files'].items():(dst/name).write_text(content,encoding='utf-8')
            emit(args.out/'private'/f"{t['id']}.json",t)
        emit(args.out/'manifest.json',{'seed':args.seed,'task_templates':len(corpus),'development_only':True,'private_not_for_candidate':True,'ids':[t['id'] for t in corpus]})
        print(json.dumps({'exported':str(args.out),'templates':len(corpus)}));return 0
    matches=[t for t in corpus if t['id']==args.id]
    if not matches:p.error('known task ID required')
    t=matches[0]
    if args.command=='reference':
        if args.out is None or args.out.exists():p.error('unused --out required')
        if t['track']=='artifact':artifact_tasks.setup(t,args.out);artifact_tasks.reference(t,args.out)
        else:emit(args.out,bench.reference_answer(t) if t['id']=='Q01' else answer_tasks.reference(t))
        print(json.dumps({'reference':str(args.out)}));return 0
    if args.submission is None:p.error('--submission required')
    if t['track']=='artifact':result=artifact_tasks.grade(t,args.submission)
    else:
        try:
            if args.submission.stat().st_size>2_000_000:raise ValueError('too big')
            result=bench.grade_answer(t,bench.load_answer(args.submission.read_text(encoding='utf-8')))
        except (OSError,ValueError,UnicodeError):result={'passed':False,'checks':{'valid_json_input':False}}
    print(json.dumps(result));return 0 if result['passed'] else 1

if __name__=='__main__':sys.exit(main())
