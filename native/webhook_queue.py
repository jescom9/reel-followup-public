"""Normalize signed queue transport aliases to one account's delivery identity."""
import hashlib
import json


def queued_event(event, account_id):
    payload = {**event['payload'], 'received': float(event['received']),
               'queue_account_id': event.get('ig_account_id') or account_id,
               'queue_event_id': event['event_id']}
    key = event['event_id']
    if payload['kind'] == 'message':
        value = payload['value']
        postback = value.get('postback') or {}
        message = value.get('message') or {}
        if postback.get('payload'):
            identity = [(value.get('sender') or {}).get('id'), account_id, value.get('timestamp'),
                        postback.get('payload'), postback.get('title'), message.get('mid') or postback.get('mid')]
            encoded = json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode()
            key = 'postback:' + hashlib.sha256(encoded).hexdigest()
        payload['value'] = {**value, 'recipient': {**(value.get('recipient') or {}), 'id': account_id}}
    return key, payload
