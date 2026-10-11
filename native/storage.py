"""Explicit SQLite default; optional Neon never silently replaces local storage."""
from pathlib import Path
try:
    from .profiles import read_values
    from .local_storage import LocalStorage
    from .neon_http import NeonHTTP,ArchiveError
except ImportError:
    from profiles import read_values
    from local_storage import LocalStorage
    from neon_http import NeonHTTP,ArchiveError

def backend_name(env_file):
    values=read_values(Path(env_file))
    return values.get('REEL_STORAGE') or ('neon' if values.get('REEL_FOLLOWUP_DATABASE_URL') else 'sqlite')
def delivery_mode(env_file):
    values=read_values(Path(env_file))
    return values.get('REEL_WEBHOOK_DELIVERY') or ('neon' if values.get('REEL_FOLLOWUP_DATABASE_URL') and not values.get('REEL_STORAGE') else 'direct')

class StorageBridge:
    def __init__(self,env_file=None,folder=None):
        self.env_file=Path(env_file or Path(__file__).resolve().parent.parent/'.env')
        self.folder=Path(folder or (self.env_file.parent if self.env_file.parent.name.startswith('ig-') else self.env_file.parent/'native/.local'))
        self.backend=backend_name(self.env_file)
        if self.backend not in ('sqlite','neon'):raise ArchiveError('REEL_STORAGE must be sqlite or neon.')
    def __enter__(self):
        self.adapter=NeonHTTP(self.env_file) if self.backend=='neon' else LocalStorage(self.folder)
        self.adapter.__enter__();return self
    def request(self,data):return self.adapter.request(data)
    def __exit__(self,*args):return self.adapter.__exit__(*args)
