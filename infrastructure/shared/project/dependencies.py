"""Install the generated workspace's npm dependencies before each TDD run."""

from pathlib import Path
import subprocess
from threading import Thread

from infrastructure.utils.processes import npm_command, start_process, stop_process


def _install_once(output_dir: Path, refresh=False) -> None:
    """Run npm install in the generated workspace, stream its output, and fail on timeout or nonzero exit."""
    if not (output_dir / "package.json").is_file():
        raise ValueError("Run 00_project_initialization.py before installing project dependencies")
    command = npm_command()
    print(f"Installing dependencies in {output_dir}: npm install --include=dev --no-audit --no-fund", flush=True)
    with start_process(
        [*command, "install", "--include=dev", "--include=optional", "--no-audit", "--no-fund", *(['--prefer-online'] if refresh else [])],
        cwd=output_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    ) as process:
        # Forward child output through Python so the console log also receives it.
        def forward_output():
            """Forward npm output through Python so both the terminal and compiler.log receive it."""
            for line in process.stdout:
                print(line, end="", flush=True)

        reader = Thread(target=forward_output, daemon=True)
        reader.start()
        try:
            from infrastructure.shared.project.environment import active
            process.wait(timeout=180 if active() else 600)
        except subprocess.TimeoutExpired as error:
            stop_process(process)
            raise RuntimeError("npm install exceeded its bounded timeout") from error
        except BaseException:
            stop_process(process)
            raise
        finally:
            reader.join()
        if process.returncode:
            raise RuntimeError(f"npm install failed with exit code {process.returncode}; see the npm output above")


def install_dependencies(output_dir: Path) -> None:
    from infrastructure.shared.project.environment import active, workspace_contract, require_environment, block, EnvironmentBlocked
    if not active():
        return _install_once(output_dir)
    workspace_contract(output_dir)
    failures = []
    for attempt in range(2):
        try:
            _install_once(output_dir, refresh=bool(attempt))
            require_environment(output_dir)
            return
        except (RuntimeError, OSError, EnvironmentBlocked) as error:
            failures.append(str(error))
    block(output_dir, 'Dependency installation failed after two compiler-owned attempts', attempts=failures)
