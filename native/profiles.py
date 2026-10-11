"""Private per-account worker profiles; delivery history never crosses accounts."""
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


def read_values(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write(text)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def link_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or '\n' in value or '\r' in value:
        raise ValueError('Use an HTTPS destination URL without embedded credentials.')
    return value


class Profiles:
    def __init__(self, project, defaults=None):
        self.project = Path(project)
        self.base = self.project / 'native' / '.local'
        self.folder = self.base / 'profiles'
        self.defaults = defaults or {}

    def location(self, profile_id):
        if profile_id == 'default':
            return self.project / '.env', self.base
        if not re.fullmatch(r'ig-[0-9a-f]{20}', profile_id):
            raise ValueError('Unknown account profile.')
        data = self.folder / profile_id
        if not (data / 'config.json').is_file() or not (data / '.env').is_file():
            raise ValueError('This account profile is not configured.')
        return data / '.env', data

    def listing(self):
        active = 'default'
        identifiers = ['default']
        if self.folder.exists():
            identifiers += sorted(path.name for path in self.folder.iterdir() if path.is_dir() and re.fullmatch(r'ig-[0-9a-f]{20}', path.name) and (path/'config.json').is_file() and (path/'.env').is_file())
        rows = []
        for identifier in identifiers:
            _, folder = self.location(identifier)
            path = folder / 'config.json'
            config = json.loads(path.read_text()) if path.exists() else {}
            rows.append({'profile_id': identifier, 'username': config.get('username', ''),
                         'account_id': config.get('account_id', ''), 'active': identifier == active})
        return rows

    def create(self, credentials, profile):
        account_id = str(profile.get('user_id') or profile.get('id') or '')
        if not account_id or not profile.get('username'):
            raise ValueError('Instagram did not return an account identity.')
        if any(row['account_id'] == account_id for row in self.listing()):
            raise ValueError('This account is already saved. Select it from the account list.')
        token = str(credentials.get('access_token') or '').strip()
        if not token or len(token) > 8192 or any(c in token for c in '\r\n\x00'):
            raise ValueError('Use the single-line Instagram token returned by the connection page.')
        keyword = str(credentials.get('keyword') or 'Fit').strip()
        if not 1 <= len(keyword) <= 50:
            raise ValueError('Use a keyword between 1 and 50 characters.')
        destination = link_url(str(credentials.get('link_url') or 'https://example.com/').strip())
        identifier = 'ig-' + hashlib.sha256(account_id.encode()).hexdigest()[:20]
        folder = self.folder / identifier
        # Reuse server-side app/database settings; keep the account token isolated.
        allowed = {'IG_APP_ID','IG_APP_SECRET','IG_ACCESS_TOKEN','REEL_FOLLOWUP_DATABASE_URL',
                   'IG_WEBHOOK_VERIFY_TOKEN','IG_WEBHOOK_APP_SECRET','REEL_WEBHOOK_URL','REEL_LINK_URL','REEL_STORAGE','REEL_WEBHOOK_DELIVERY','REEL_CONNECTOR_URL'}
        values = {key: value for key, value in read_values(self.project / '.env').items() if key in allowed}
        values['IG_ACCESS_TOKEN'] = token
        values['REEL_LINK_URL'] = destination
        values['IG_APP_ID'] = str(credentials['app_id'])
        if any('\n' in value or '\r' in value for value in values.values()):
            raise ValueError('Invalid credential configuration.')
        folder.mkdir(parents=True, exist_ok=False, mode=0o700)
        config = {**self.defaults, 'account_id': account_id, 'username': profile['username'],
                  'app_id': values['IG_APP_ID'], 'account_aliases': sorted({str(profile[key]) for key in ('user_id', 'id') if profile.get(key)}),
                  'verified': True, 'enabled': False, 'workflow_mode': 'manychat',
                  'keyword': keyword, 'link_url': destination,
                  'flows':[{'id':'starter','name':'New flow','keywords':['INFO'],'enabled':False,'require_follow':True,'link_button':True,'link_url':'','opening_text':'Follow this account and press Following 👇','follow_text':'Follow this account, then press Following 👇','link_text':'Your link','button_text':'Open link','public_reply':True,'public_reply_text':'Sent you a message! Check your DMs.','followup_enabled':False,'followup_delay_minutes':60,'followup_text':'Did the link help? Let us know!'}],
                  'verify_token': values.get('IG_WEBHOOK_VERIFY_TOKEN', ''), 'webhook_verified': False}
        private_write(folder / '.env', '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
        private_write(folder / 'config.json', json.dumps(config))
        return identifier
