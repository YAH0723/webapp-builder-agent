"""Check the built production server with isolated data and local HTTP only."""
import json
from pathlib import Path
import shutil
import socket
from tempfile import TemporaryDirectory, TemporaryFile
from time import monotonic, sleep
from urllib.request import build_opener, ProxyHandler

from infrastructure.utils.processes import start_process, stop_process


def check_production(output, timeout=20):
    output = Path(output)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    opener = build_opener(ProxyHandler({}))
    with TemporaryDirectory(prefix='arc-compact-startup-') as directory, TemporaryFile() as log:
        process = start_process([shutil.which('node') or 'node', 'backend/dist/server.js'], cwd=output,
            env={'PORT': str(port), 'DATABASE_URL': str(Path(directory) / 'app.db')}, stdout=log, stderr=log)
        try:
            deadline = monotonic() + timeout
            while monotonic() < deadline and process.poll() is None:
                try:
                    with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
                        health = json.load(response)
                    with opener.open(f'http://127.0.0.1:{port}/', timeout=1) as response:
                        page = response.read().decode('utf8')
                    if health.get('status') == 'ok' and 'id="root"' in page:
                        return {'status': 'GREEN', 'production_health': True, 'frontend_html': True,
                                'isolated_database': True, 'business_acceptance_passed': False}
                except (OSError, ValueError): pass
                sleep(.1)
            log.seek(0)
            raise ValueError('Built application did not start: ' + log.read().decode('utf8', errors='replace')[-6000:])
        finally:
            stop_process(process)
