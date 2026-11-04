"""Isolate failed design tasks while preserving successful neighboring artifacts."""

from contextlib import contextmanager
from pathlib import Path
import time

from infrastructure.shared.agent.efficiency import enabled
from infrastructure.shared.agent.service_recovery import retryable_service_error
from infrastructure.utils.files import save_json


class StageIncomplete(RuntimeError):
    def __init__(self, stage, failures):
        self.failures = failures
        super().__init__(f'{stage}: {len(failures)} task(s) failed; all tasks were attempted. '
            'Continue with available artifacts.')


class TaskFailures:
    """Track failures in memory without writing per-task status files."""

    def __init__(self, arc_dir, stage, console):
        self.arc_dir, self.stage, self.console = Path(arc_dir), stage, console
        self.report = {'status': 'RUNNING', 'tasks': {}}

    def iterate(self, items, identity=lambda item: item):
        """Attempt all tasks, then one deferred pass over transient failures only."""
        items = list(items)
        yield from enumerate(items, 1)
        if not enabled('service_recovery'):
            return
        pending = [(index, item) for index, item in enumerate(items, 1)
            if self.report['tasks'].get(identity(item), {}).get('retryable')]
        if pending:
            self.console.show(self.stage + ' | Deferred service recovery',
                f'Retry {len(pending)} transiently failed task(s) once; preserve all accepted artifacts.')
            time.sleep(5)
            yield from pending

    @contextmanager
    def task(self, identity):
        previous = self.report['tasks'].get(identity, {})
        attempts = previous.get('attempts', 0) + 1
        try:
            yield
        except Exception as error:
            if isinstance(error, OSError):
                raise
            self.report['tasks'][identity] = {'status': 'FAILED', 'error': str(error),
                'error_type': type(error).__name__, 'retryable': retryable_service_error(error), 'attempts': attempts}
            self.console.show(self.stage + ' / ' + identity + ' | FAILED; continuing', str(error))
        else:
            self.report['tasks'][identity] = {'status': 'GREEN', 'attempts': attempts}
        finally:
            if enabled('service_recovery') and (attempts > 1 or any(
                    item.get('status') == 'FAILED' for item in self.report['tasks'].values())):
                save_json(self.arc_dir / 'task_recovery' / (self.stage + '.json'), self.report)

    def finish(self):
        failures = [{'task': identity, **entry} for identity, entry in self.report['tasks'].items()
            if entry['status'] == 'FAILED']
        self.report['status'] = 'COMPLETED_WITH_FAILURES' if failures else 'GREEN'
        if enabled('service_recovery') and any(item.get('attempts', 0) > 1 for item in self.report['tasks'].values()):
            save_json(self.arc_dir / 'task_recovery' / (self.stage + '.json'), self.report)
        if failures:
            raise StageIncomplete(self.stage, failures)
