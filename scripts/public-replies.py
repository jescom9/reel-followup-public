#!/usr/bin/env python3
"""Create, inspect and pause a public reply batch on the Pi. Local account data only."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from native.app import Store
from native.public_replies import PublicReplies

def run():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account',required=True)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    for action in ('resume','pause'):
        cmd=sub.add_parser(action);cmd.add_argument('id')
    create=sub.add_parser('create');create.add_argument('id');create.add_argument('--targets',type=Path,required=True)
    create.add_argument('--keyword',required=True);create.add_argument('--message',required=True)
    create.add_argument('--skip',action='append',default=[]);create.add_argument('--dedupe-text',action='append',default=[])
    create.add_argument('--exclude-author',action='append',default=[])
    args=parser.parse_args()
    if not args.account.startswith('ig-') or not all(c in '0123456789abcdef' for c in args.account[3:]):
        raise ValueError('Use an existing Instagram account workspace ID.')
    folder=ROOT/'native/.local/profiles'/args.account
    if not (folder/'config.json').exists():raise ValueError('Account workspace does not exist.')
    queue=PublicReplies(Store(folder,ROOT/'.env'))
    if args.command=='create':
        data=json.loads(args.targets.read_text())
        result=queue.create(args.id,data['media_id'],args.keyword,args.message,data['matching'],args.skip,dedupe_texts=args.dedupe_text,excluded_authors=args.exclude_author)
    elif args.command=='status':result=queue.status()
    else:result=queue.control(args.id,args.command)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':
    try:run()
    except ValueError as error:raise SystemExit(str(error))
