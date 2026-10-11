#!/usr/bin/env python3
"""Run the Pi worker and userspace VPN as the owning Linux user, with restart."""
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / 'native' / '.local'
TOOLS = ROOT / '.local-tools'


def command(kind):
    if kind == 'worker':
        return [sys.executable, str(ROOT / 'native' / 'app.py')]
    if kind == 'tailscale':
        return [str(TOOLS / 'tailscale' / 'tailscaled'), '--tun=userspace-networking',
                '--state=' + str(STATE / 'tailscale.state'),
                '--socket=' + str(STATE / 'tailscale.sock'), '--port=0']
    raise SystemExit('Choose worker or tailscale.')


def paths(kind):
    command(kind)
    return STATE / (kind + '-service.json'), STATE / (kind + '-service.lock'), STATE / (kind + '-service.log')


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def matches(pid, required):
    if not alive(pid):
        return False
    try:
        arguments = Path('/proc/' + str(int(pid)) + '/cmdline').read_bytes().decode().split('\0')
        return all(part in arguments for part in required)
    except (OSError, ValueError, UnicodeError):
        return False


def status(kind):
    record, _, _ = paths(kind)
    data = json.loads(record.read_text()) if record.exists() else {}
    return {**data, 'kind': kind,
            'supervisor_running': matches(data.get('supervisor_pid'), [str(Path(__file__).resolve()), 'run', kind]),
            'process_running': matches(data.get('process_pid'), [command(kind)[-1] if kind == 'worker' else command(kind)[0]])}


def supervise(kind):
    record, lock_path, log_path = paths(kind)
    lock = lock_path.open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    stopping = False
    child = None

    def stop(*_):
        nonlocal stopping
        stopping = True
        if child and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    environment = {**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
    node_dir = str(TOOLS / 'node' / 'bin')
    if not (TOOLS / 'node' / 'bin' / 'node').exists():
        node_dir = '/opt/homebridge/bin'
    environment['PATH'] = node_dir + ':' + environment.get('PATH', '/usr/bin:/bin')
    try:
        while not stopping:
            if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
                log_path.replace(log_path.with_suffix('.log.1'))
            with log_path.open('a') as log:
                child = subprocess.Popen(command(kind), cwd=ROOT, env=environment,
                                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                temporary = record.with_suffix('.tmp')
                temporary.write_text(json.dumps({'supervisor_pid': os.getpid(), 'process_pid': child.pid,
                                                 'started_at': time.time()}) + '\n')
                temporary.replace(record)
                while child.poll() is None:
                    time.sleep(1)
            if not stopping:
                for _ in range(10):
                    if stopping:
                        break
                    time.sleep(1)
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        record.unlink(missing_ok=True)
        lock.close()


def main():
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE, 0o700)
    action, kind = sys.argv[1:] if len(sys.argv) == 3 else ('', '')
    record, _, log_path = paths(kind)
    if action == 'run':
        supervise(kind)
    elif action == 'start':
        if not status(kind)['supervisor_running']:
            with log_path.open('a') as output:
                subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'run', kind],
                                 cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                 start_new_session=True)
            for _ in range(30):
                if status(kind)['process_running']:
                    break
                time.sleep(0.1)
        print(json.dumps(status(kind)))
    elif action == 'status':
        print(json.dumps(status(kind)))
    elif action == 'stop':
        data = status(kind)
        if data['supervisor_running']:
            os.kill(data['supervisor_pid'], signal.SIGTERM)
        print(json.dumps({'kind': kind, 'stop_requested': True}))
    else:
        raise SystemExit('Usage: pi-user-service.py start|stop|status|run worker|tailscale')


if __name__ == '__main__':
    main()
