"""Run command for slurmit CLI (server-side).

Executes a queued job by moving it to runs/ and submitting to SLURM.
"""

import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from slurmit.backend.slurm import SlurmBackend
from slurmit.core.config import load_config, load_secret_config
from slurmit.monitor.status import JobState, StatusMonitor

console = Console()

# Base directory for slurmit on server
MYJOB_BASE_DIR = Path.home() / "slurmit"


def ensure_base_directories() -> None:
    """Ensure slurmit base directories exist."""
    (MYJOB_BASE_DIR / "queue").mkdir(parents=True, exist_ok=True)
    (MYJOB_BASE_DIR / "runs").mkdir(parents=True, exist_ok=True)
    (MYJOB_BASE_DIR / "active").mkdir(parents=True, exist_ok=True)


def get_queue_dir(job_name: str) -> Path:
    """Get the queue directory for a job."""
    return MYJOB_BASE_DIR / "queue" / job_name


def get_run_dir(run_id: str) -> Path:
    """Get the run directory for a job run."""
    return MYJOB_BASE_DIR / "runs" / run_id


def get_active_link(job_name: str) -> Path:
    """Get the active symlink path for a job."""
    return MYJOB_BASE_DIR / "active" / job_name


def generate_run_id(job_name: str) -> str:
    """Generate a unique run ID with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{job_name}_{timestamp}"


def move_queue_to_runs(job_name: str) -> tuple[str, Path]:
    """Move job from queue to runs directory.

    Returns:
        Tuple of (run_id, run_dir_path)
    """
    queue_dir = get_queue_dir(job_name)
    run_id = generate_run_id(job_name)
    run_dir = get_run_dir(run_id)

    # Copy instead of move (to keep queue clean for potential resubmit)
    shutil.copytree(queue_dir, run_dir)

    # Update active symlink
    active_link = get_active_link(job_name)
    if active_link.exists() or active_link.is_symlink():
        active_link.unlink()
    active_link.symlink_to(run_dir)

    return run_id, run_dir


def wait_for_completion(
    slurm_job_id: str,
    poll_interval: int = 10,
    follow_logs: bool = False,
    log_file: Path | None = None,
) -> JobState:
    """Wait for a SLURM job to complete.

    Args:
        slurm_job_id: SLURM job ID to monitor
        poll_interval: Seconds between status checks
        follow_logs: If True, tail logs while waiting
        log_file: Path to log file for following

    Returns:
        Final job state
    """
    from slurmit.transport.ssh import SSHClient
    from slurmit.core.models import ConnectionConfig

    # For local execution, create a dummy SSH connection to localhost
    # In practice, we're running locally, so we use subprocess
    import subprocess

    last_state = None
    log_offset = 0

    with console.status("[bold green]Waiting for job to complete...") as status:
        while True:
            # Get job status using squeue/sacct
            try:
                # Try squeue first
                result = subprocess.run(
                    ["squeue", "-j", slurm_job_id, "-h", "-o", "%T"],
                    capture_output=True,
                    text=True,
                )

                if result.returncode == 0 and result.stdout.strip():
                    state_str = result.stdout.strip()
                    state = JobState.from_string(state_str)
                else:
                    # Job not in queue, check sacct
                    result = subprocess.run(
                        ["sacct", "-j", slurm_job_id, "-n", "-X", "-o", "State", "--parsable2"],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        state_str = result.stdout.strip().split("\n")[0]
                        state = JobState.from_string(state_str)
                    else:
                        state = JobState.UNKNOWN

            except Exception:
                state = JobState.UNKNOWN

            if state != last_state:
                last_state = state

            status.update(f"[bold green]Job {slurm_job_id}: {state.value}")

            # Check if job is in a terminal state
            if state in (
                JobState.COMPLETED,
                JobState.FAILED,
                JobState.CANCELLED,
                JobState.TIMEOUT,
                JobState.NODE_FAIL,
                JobState.OUT_OF_MEMORY,
            ):
                break

            # Follow logs if requested
            if follow_logs and log_file and log_file.exists():
                try:
                    with open(log_file) as f:
                        f.seek(log_offset)
                        new_content = f.read()
                        if new_content:
                            console.print(new_content, end="")
                            log_offset = f.tell()
                except Exception:
                    pass

            time.sleep(poll_interval)

    return state


def run(
    job_name: str = typer.Argument(
        ...,
        help="Name of the job to run (from queue)",
    ),
    wait: bool = typer.Option(
        False,
        "--wait",
        "-w",
        help="Wait for job completion",
    ),
    follow: bool = typer.Option(
        False,
        "--follow",
        "-f",
        help="Follow log output (implies --wait)",
    ),
    poll_interval: int = typer.Option(
        10,
        "--poll-interval",
        help="Status check interval in seconds (for --wait)",
    ),
) -> None:
    """Run a queued job (server-side command).

    This command:
    1. Checks that the job exists in ~/slurmit/queue/
    2. Moves it to ~/slurmit/runs/<job_name>_<timestamp>/
    3. Creates symlink in ~/slurmit/active/
    4. Generates and submits sbatch script
    """
    # Ensure base directories exist
    ensure_base_directories()

    # Check if job exists in queue
    queue_dir = get_queue_dir(job_name)
    if not queue_dir.exists():
        console.print(f"[red]Error:[/red] Job '{job_name}' not found in queue")
        console.print(f"  Queue directory: {queue_dir}")
        console.print("\nUse [cyan]slurmit list --queue[/cyan] to see available jobs.")
        raise typer.Exit(1)

    # Check for required files
    config_file = queue_dir / "slurmit.yaml"
    code_dir = queue_dir / "code"

    if not config_file.exists():
        console.print(f"[red]Error:[/red] Config file not found: {config_file}")
        raise typer.Exit(1)

    if not code_dir.exists():
        console.print(f"[red]Error:[/red] Code directory not found: {code_dir}")
        raise typer.Exit(1)

    console.print(f"Found job: [cyan]{job_name}[/cyan]")
    console.print(f"  Queue dir: {queue_dir}")

    # Load configuration
    try:
        config = load_config(str(config_file))
    except Exception as e:
        console.print(f"[red]Error loading config:[/red] {e}")
        raise typer.Exit(1)

    # Load secrets if available
    secret_file = queue_dir / "secret.yaml"
    secret_env = {}
    if secret_file.exists():
        try:
            secret_config = load_secret_config(str(secret_file))
            secret_env = secret_config.env_vars
        except Exception:
            console.print("[yellow]Warning:[/yellow] Failed to load secrets")

    # Move to runs directory
    console.print("Moving to runs directory...")
    run_id, run_dir = move_queue_to_runs(job_name)
    console.print(f"  Run ID: [cyan]{run_id}[/cyan]")
    console.print(f"  Run dir: {run_dir}")

    # Working directory is the code subdirectory
    working_dir = run_dir / "code"

    # Create log directory
    log_dir = run_dir / "logs"
    log_dir.mkdir(exist_ok=True)

    # Generate and write sbatch script
    console.print("Generating sbatch script...")

    # Create a minimal SSH-like interface for local execution
    class LocalExecutor:
        """Local command executor that mimics SSHClient interface."""

        def ensure_directory(self, path: str) -> None:
            Path(path).expanduser().mkdir(parents=True, exist_ok=True)

        def write_file(self, path: str, content: str) -> None:
            expanded = Path(path).expanduser()
            expanded.parent.mkdir(parents=True, exist_ok=True)
            expanded.write_text(content)

        def run(self, command: str, warn: bool = False, hide: bool = True):
            import subprocess
            from dataclasses import dataclass

            @dataclass
            class Result:
                stdout: str
                stderr: str
                return_code: int
                ok: bool

            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
            )
            return Result(
                stdout=result.stdout.strip(),
                stderr=result.stderr.strip(),
                return_code=result.returncode,
                ok=result.returncode == 0,
            )

    local = LocalExecutor()

    # Update config output paths for this run
    # Override log directory to our run's log dir
    original_log_dir = config.output.log_dir
    config.output.log_dir = "logs"  # Relative to working dir's parent (run_dir)

    # Generate sbatch script
    slurm_backend = SlurmBackend(local, config)  # type: ignore

    # Prepare workspace (create directories, write scripts)
    # Note: working_dir for script is run_dir (not code subdir) so logs go to run_dir/logs
    script_path = slurm_backend.prepare_workspace(str(run_dir), secret_env)
    console.print(f"  Script: {script_path}")

    # Fix the script to cd into code directory
    script_content = Path(script_path).read_text()
    script_content = script_content.replace(
        f"cd {run_dir}",
        f"cd {working_dir}"
    )
    Path(script_path).write_text(script_content)

    # Submit job
    console.print("Submitting to SLURM...")
    result = local.run(f"sbatch {script_path}")

    if not result.ok:
        console.print(f"[red]Error:[/red] sbatch failed: {result.stderr}")
        raise typer.Exit(1)

    # Parse job ID
    output = result.stdout
    if "Submitted batch job" not in output:
        console.print(f"[red]Error:[/red] Unexpected sbatch output: {output}")
        raise typer.Exit(1)

    slurm_job_id = output.split()[-1]

    console.print(
        f"\n[green]Job submitted successfully![/green]\n"
        f"  SLURM Job ID: [bold]{slurm_job_id}[/bold]\n"
        f"  Run ID: [cyan]{run_id}[/cyan]\n"
        f"  Working dir: {working_dir}"
    )

    # Handle --wait/--follow options
    if follow:
        wait = True

    if wait:
        console.print("\nWaiting for job completion...")
        stdout_file = log_dir / config.output.stdout.replace("%j", slurm_job_id)

        final_state = wait_for_completion(
            slurm_job_id,
            poll_interval=poll_interval,
            follow_logs=follow,
            log_file=stdout_file,
        )

        # Show final status
        state_color = "green" if final_state == JobState.COMPLETED else "red"
        console.print(f"\nJob finished: [{state_color}]{final_state.value}[/{state_color}]")

        if final_state == JobState.FAILED:
            # Show last few lines of stderr
            stderr_file = log_dir / config.output.stderr.replace("%j", slurm_job_id)
            if stderr_file.exists():
                console.print("\n[bold]Last lines of stderr:[/bold]")
                lines = stderr_file.read_text().splitlines()[-10:]
                for line in lines:
                    console.print(f"  {line}")
    else:
        console.print(f"\nTo check status: [cyan]squeue -j {slurm_job_id}[/cyan]")
        console.print(f"To view logs:    [cyan]tail -f {log_dir}/job_{slurm_job_id}.out[/cyan]")


def list_queue() -> None:
    """List jobs in the queue directory."""
    queue_base = MYJOB_BASE_DIR / "queue"
    if not queue_base.exists():
        console.print("No jobs in queue.")
        return

    jobs = [d.name for d in queue_base.iterdir() if d.is_dir()]
    if not jobs:
        console.print("No jobs in queue.")
        return

    console.print("[bold]Queued jobs:[/bold]")
    for job in sorted(jobs):
        job_dir = queue_base / job
        config_exists = (job_dir / "slurmit.yaml").exists()
        code_exists = (job_dir / "code").exists()
        status = "[green]ready[/green]" if (config_exists and code_exists) else "[yellow]incomplete[/yellow]"
        console.print(f"  {job} {status}")


def list_runs(limit: int = 20) -> None:
    """List job runs."""
    runs_base = MYJOB_BASE_DIR / "runs"
    if not runs_base.exists():
        console.print("No runs found.")
        return

    runs = sorted(
        [d for d in runs_base.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )[:limit]

    if not runs:
        console.print("No runs found.")
        return

    console.print("[bold]Recent runs:[/bold]")
    for run_dir in runs:
        # Try to get job name from run_id
        run_id = run_dir.name
        job_name = "_".join(run_id.split("_")[:-2])  # Remove timestamp suffix
        timestamp = "_".join(run_id.split("_")[-2:])  # Get timestamp
        console.print(f"  {run_id}")
