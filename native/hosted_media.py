"""Account-owned Reel previews from Instagram; credentials never reach the UI."""
import re,time
from urllib.parse import urlsplit,urlunsplit

FIELDS='id,caption,permalink,media_type,media_product_type,thumbnail_url,timestamp,comments_count'

def permalink(value):
    try:
        url=urlsplit(str(value or ''))
        if url.scheme=='https' and url.hostname in ('www.instagram.com','instagram.com') and not url.username and not url.password:
            return urlunsplit((url.scheme,url.netloc,url.path,'',''))
    except ValueError:pass
    return None

def thumbnail(value):
    try:
        url=urlsplit(str(value or ''));host=url.hostname or ''
        if url.scheme=='https' and not url.username and not url.password and (host.endswith('.cdninstagram.com') or host.endswith('.fbcdn.net')) and 'access_token' not in url.query:
            return url.geturl()
    except ValueError:pass
    return None

def clean(row):
    link=permalink(row.get('permalink'));identifier=str(row.get('id') or '')
    if not re.fullmatch(r'\d{1,32}',identifier) or not link or row.get('media_product_type')!='REELS':return None
    count=row.get('comments_count')
    return {'id':identifier,'caption':str(row.get('caption') or '')[:500],'permalink':link,
        'thumbnail_url':thumbnail(row.get('thumbnail_url')),'timestamp':str(row.get('timestamp') or ''),
        'comments_count':count if isinstance(count,int) and not isinstance(count,bool) and count>=0 else None}

def list_media(app, factory, data, now=None):
    if not isinstance(data,dict):raise ValueError('Invalid Reel request.')
    cursor=data.get('after','')
    if not isinstance(data.get('refresh',False),bool):raise ValueError('Invalid Reel refresh setting.')
    if not isinstance(cursor,str) or len(cursor)>4096 or (cursor and not re.fullmatch(r'[A-Za-z0-9_\-+.=/]+',cursor)):raise ValueError('Invalid Reel page.')
    config=app.store.config
    if not config.get('verified') or not config.get('access_token'):raise ValueError('Reconnect Instagram to load your Reels.')
    now=time.time() if now is None else now
    cache=getattr(app,'_reel_pages',{})
    if not data.get('refresh') and cursor in cache and now-cache[cursor]['time']<60:return cache[cursor]['data']
    query={'fields':FIELDS,'limit':24}
    if cursor:query['after']=cursor
    response=factory(dict(config)).call('GET',str(config['account_id'])+'/media',**query)
    rows=[preview for row in response.get('data',[]) if (preview:=clean(row))]
    paging=response.get('paging') or {};after=(paging.get('cursors') or {}).get('after')
    next_cursor=after if paging.get('next') and isinstance(after,str) and re.fullmatch(r'[A-Za-z0-9_\-+.=/]{1,4096}',after) else None
    result={'rows':rows,'next_cursor':next_cursor,'source':'instagram_api','fetched_at':now}
    if len(cache)>=40:cache={}
    cache[cursor]={'time':now,'data':result};app._reel_pages=cache
    owned=getattr(app,'_owned_reels',{});owned.update({row['id']:row for row in rows});app._owned_reels=owned
    return result

def verify_new_selections(app, factory, new_flows, previous):
    saved={flow['id']:set(flow.get('media_ids',[])) if flow.get('media_scope')=='selected' else set() for flow in previous}
    owned=getattr(app,'_owned_reels',{})
    for flow in new_flows:
        for identifier in set(flow.get('media_ids',[]))-saved.get(flow['id'],set()):
            if identifier in owned:continue
            config=app.store.config
            row=factory(dict(config)).call('GET',identifier,fields='id,owner,media_product_type')
            owner=row.get('owner') or {};owner=owner.get('id') if isinstance(owner,dict) else owner
            if str(row.get('id'))!=identifier or str(owner) not in {str(config['account_id']),*map(str,config.get('account_aliases',[]))} or row.get('media_product_type')!='REELS':
                raise ValueError('Choose Reels owned by this Instagram account.')
