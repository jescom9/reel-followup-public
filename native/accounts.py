"""A single Python service with separate account credentials and worker data."""
import threading
from pathlib import Path
try:
    from .profiles import Profiles,read_values
except ImportError:
    from profiles import Profiles,read_values

class AccountRegistry:
    def __init__(self,project,app_factory,graph_factory,defaults):
        self.project=Path(project);self.profiles=Profiles(project,defaults)
        self.factory,self.graph=app_factory,graph_factory
        self.apps={};self.lock=threading.RLock();self.running=False
        for row in self.profiles.listing():self.load(row['profile_id'])
    def load(self,identifier):
        env,data=self.profiles.location(identifier);app=self.factory(data,env)
        app.engine.workflows.reply_resolver=lambda selected,app=app:self.reply_sender(selected,app)
        self.apps[identifier]=app
        if self.running:self.start_app(app)
        return app
    def get(self,identifier):
        with self.lock:
            if identifier not in self.apps:raise ValueError('Unknown account workspace. Refresh the account list.')
            return self.apps[identifier]
    def listing(self):
        with self.lock:return [{'profile_id':identifier,'username':app.store.config.get('username',''),
            'account_id':app.store.config.get('account_id',''),'verified':app.store.config.get('verified',False),
            'enabled':app.store.config.get('enabled',False)} for identifier,app in self.apps.items()]
    def create(self,credentials):
        with self.lock:
            root=self.get('default').store.config
            app_id=str(credentials.get('app_id') or root.get('app_id') or '')
            if not app_id:raise ValueError('Configure the automation app ID first.')
            if root.get('app_id') and app_id!=root['app_id']:raise ValueError('Use the same automation Meta app as the connection page.')
            profile=self.graph({**root,'access_token':credentials['access_token'],'app_id':app_id}).call('GET','me',fields='user_id,username')
            if any(str(profile.get('user_id'))==app.store.config.get('account_id') for app in self.apps.values()):raise ValueError('This Instagram account is already connected.')
            if not str(profile.get('user_id') or '').isdigit():raise ValueError('Instagram did not return a professional account identity.')
            subscribed=self.graph({**root,'access_token':credentials['access_token'],'app_id':app_id}).call('POST',str(profile['user_id'])+'/subscribed_apps',{'subscribed_fields':'comments,messages,messaging_postbacks'})
            if subscribed.get('success') is not True:raise ValueError('Instagram did not confirm the webhook subscription.')
            identifier=self.profiles.create({**credentials,'app_id':app_id},profile)
            self.load(identifier);return identifier
    def start_app(self,app):
        for task in [app.worker,app.archive_worker,app.dashboard_worker,app.webhook_worker]:threading.Thread(target=task,daemon=True).start()
    def start(self):
        with self.lock:
            if self.running:return
            self.running=True
            for app in self.apps.values():self.start_app(app)
    def stop(self):
        for app in self.apps.values():app.stop.set()
    def ingest(self,body):
        for app in list(self.apps.values()):app.store.ingest(body)
    def reply_sender(self,selected,source):
        target=source if selected=='self' else self.get(selected)
        if not target.store.config.get('verified'):raise ValueError('The reminder sender is not verified.')
        if not target.store.config.get('enabled'):raise ValueError('The reminder sender workspace is paused.')
        return dict(target.store.config),target.store.flow_once
