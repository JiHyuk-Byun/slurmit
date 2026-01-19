"""Status command for slurmit CLI."""

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from slurmit.core.models import ConnectionConfig
from slurmit.monitor.status import JobState, StatusMonitor
from slurmit.storage import job_store
from slurmit.transport.ssh import SSHClient

console = Console()

# Remote base directory
MYJOB_BASE_DIR = Path.home() / "slurmit"


def _get_state_style(state: JobState) -> str:
    """Get Rich style for a job state."""
    styles = {
        JobState.PENDING: "yellow",
        JobState.RUNNING: "green",
        JobState.COMPLETING: "green",
        JobState.COMPLETED: "blue",
        JobState.FAILED: "red",
        JobState.CANCELLED: "dim",
        JobState.TIMEOUT: "red",
        JobState.NODE_FAIL: "red",
        JobState.OUT_OF_MEMORY: "red",
        JobState.UNKNOWN: "dim",
    }
    return styles.get(state, "white")


def _get_status_style(status: str) -> str:
    """Get Rich style for a status string."""
    status_upper = status.upper()
    if status_upper in ("RUNNING", "SUBMITTED"):
        return "green"
    elif status_upper in ("PENDING", "QUEUED"):
        return "yellow"
    elif status_upper in ("COMPLETED",):
        return "blue"
    elif status_upper in ("FAILED", "CANCELLED", "TIMEOUT"):
        return "red"
    return "white"


def status(
    job_name: str = typer.Argument(
        ...,
        help="Job name or SLURM job ID",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed information",
    ),
) -> None:
    """Check the status of a submitted job."""
    # Try to find job by name first
    record = job_store.find_job_by_name(job_name)

    if record is None:
        # Try by name prefix
        try:
            record = job_store.find_job_by_prefix(job_name)
        except ValueError:
            pass

    if record is None:
        # Try by SLURM job ID
        record = job_store.find_job_by_slurm_id(job_name)

    if record is None:
        # Try by run ID
        record = job_store.find_job_by_run_id(job_name)

    if record is None:
        console.print(f"[red]Error:[/red] Job not found: {job_name}")
        console.print("Use [cyan]slurmit list[/cyan] to see recent jobs.")
        raise typer.Exit(1)

    console.print(f"Job: [cyan]{record.name}[/cyan]")
    console.print(f"Host: [cyan]{record.host}[/cyan]")
    console.print(f"Submitted: {record.submitted_at}")

    if record.run_id:
        console.print(f"Run ID: [cyan]{record.run_id}[/cyan]")

    if record.slurm_job_id:
        # Connect to remote to get current SLURM status
        console.print(f"\nQuerying SLURM status for job [cyan]{record.slurm_job_id}[/cyan]...")

        try:
            user = record.user or os.environ.get("USER", "")
            connection = ConnectionConfig(host=record.host, user=user)

            with SSHClient(connection) as ssh:
                monitor = StatusMonitor(ssh)
                slurm_status = monitor.get_status(record.slurm_job_id)

                if slurm_status:
                    state_style = _get_state_style(slurm_status.state)
                    console.print(
                        f"\nSLURM Job ID: [bold]{slurm_status.job_id}[/bold]"
                    )
                    console.print(
                        f"State: [{state_style}]{slurm_status.state.value}[/{state_style}]"
                    )
                    console.print(f"Partition: {slurm_status.partition}")
                    if slurm_status.node:
                        console.print(f"Node: {slurm_status.node}")
                    console.print(f"Elapsed: {slurm_status.elapsed}")
                    if slurm_status.start_time:
                        console.print(f"Start time: {slurm_status.start_time}")
                    if slurm_status.end_time:
                        console.print(f"End time: {slurm_status.end_time}")
                    if slurm_status.exit_code:
                        console.print(f"Exit code: {slurm_status.exit_code}")

                    # Update local record
                    job_store.update_job_status(
                        record.name,
                        slurm_status.state.value,
                    )
                else:
                    console.print("[yellow]Job not found in SLURM queue or history[/yellow]")

        except Exception as e:
            console.print(f"[yellow]Could not connect to remote:[/yellow] {e}")
            console.print(f"Last known status: {record.status}")
    else:
        status_style = _get_status_style(record.status)
        console.print(f"Status: [{status_style}]{record.status}[/{status_style}]")

    if verbose:
        console.print(f"\n[bold]Details:[/bold]")
        console.print(f"  Queue dir: {record.queue_dir}")
        if record.run_dir:
            console.print(f"  Run dir: {record.run_dir}")
        if record.log_dir:
            console.print(f"  Log dir: {record.log_dir}")
        console.print(f"  Command: {record.command}")
        if record.git_branch:
            console.print(f"  Git branch: {record.git_branch}")
        if record.git_commit:
            console.print(f"  Git commit: {record.git_commit[:8]}")
        if record.config_hash:
            console.print(f"  Config hash: {record.config_hash}")


def list_jobs(
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        help="Number of jobs to show",
    ),
    all_jobs: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Show all stored jobs",
    ),
    queue: bool = typer.Option(
        False,
        "--queue",
        help="Show jobs in server queue (server-side)",
    ),
    runs: bool = typer.Option(
        False,
        "--runs",
        help="Show run history (server-side)",
    ),
) -> None:
    """List recent submitted jobs."""
    if queue:
        _list_queue()
        return

    if runs:
        _list_runs(limit=limit if not all_jobs else 100)
        return

    # Default: list local job records
    max_limit = 100 if all_jobs else limit
    records = job_store.list_jobs(limit=max_limit)

    if not records:
        console.print("No jobs found.")
        console.print("Submit a job with [cyan]slurmit submit -n <name>[/cyan]")
        return

    table = Table(title="Recent Jobs")
    table.add_column("Name", style="cyan")
    table.add_column("SLURM ID")
    table.add_column("Host")
    table.add_column("Status")
    table.add_column("Submitted")

    for record in records:
        status_style = _get_status_style(record.status)
        table.add_row(
            record.name,
            record.slurm_job_id or "-",
            record.host,
            f"[{status_style}]{record.status}[/{status_style}]",
            record.submitted_at[:19],  # Trim milliseconds
        )

    console.print(table)


def _list_queue() -> None:
    """List jobs in the server queue directory."""
    queue_base = MYJOB_BASE_DIR / "queue"
    if not queue_base.exists():
        console.print("No jobs in queue.")
        console.print("This command should be run on the server.")
        return

    jobs = [d.name for d in queue_base.iterdir() if d.is_dir()]
    if not jobs:
        console.print("No jobs in queue.")
        return

    table = Table(title="Queued Jobs")
    table.add_column("Name", style="cyan")
    table.add_column("Status")
    table.add_column("Config")
    table.add_column("Code")

    for job in sorted(jobs):
        job_dir = queue_base / job
        config_exists = (job_dir / "slurmit.yaml").exists()
        code_exists = (job_dir / "code").exists()

        status = "[green]ready[/green]" if (config_exists and code_exists) else "[yellow]incomplete[/yellow]"
        config_str = "[green]yes[/green]" if config_exists else "[red]no[/red]"
        code_str = "[green]yes[/green]" if code_exists else "[red]no[/red]"

        table.add_row(job, status, config_str, code_str)

    console.print(table)
    console.print(f"\nTo run a job: [cyan]slurmit run <name>[/cyan]")


def _list_runs(limit: int = 20) -> None:
    """List job runs history."""
    runs_base = MYJOB_BASE_DIR / "runs"
    if not runs_base.exists():
        console.print("No runs found.")
        console.print("This command should be run on the server.")
        return

    runs = sorted(
        [d for d in runs_base.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )[:limit]

    if not runs:
        console.print("No runs found.")
        return

    table = Table(title="Run History")
    table.add_column("Run ID", style="cyan")
    table.add_column("Job Name")
    table.add_column("Modified")

    for run_dir in runs:
        run_id = run_dir.name
        # Parse job name from run_id (format: name_YYYYMMDD_HHMMSS)
        parts = run_id.rsplit("_", 2)
        job_name = parts[0] if len(parts) >= 3 else run_id

        # Get modification time
        import datetime
        mtime = datetime.datetime.fromtimestamp(run_dir.stat().st_mtime)
        mtime_str = mtime.strftime("%Y-%m-%d %H:%M")

        table.add_row(run_id, job_name, mtime_str)

    console.print(table)


def cancel(
    job_name: str = typer.Argument(
        ...,
        help="Job name or SLURM job ID to cancel",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Cancel without confirmation",
    ),
) -> None:
    """Cancel a running job."""
    # Find job record
    record = job_store.find_job_by_name(job_name)

    if record is None:
        try:
            record = job_store.find_job_by_prefix(job_name)
        except ValueError:
            pass

    if record is None:
        record = job_store.find_job_by_slurm_id(job_name)

    if record is None:
        console.print(f"[red]Error:[/red] Job not found: {job_name}")
        raise typer.Exit(1)

    if not record.slurm_job_id:
        console.print("[red]Error:[/red] No SLURM job ID associated with this job")
        console.print("The job may not have been submitted to SLURM yet.")
        raise typer.Exit(1)

    if not force:
        confirm = typer.confirm(
            f"Cancel job {record.name} (SLURM ID: {record.slurm_job_id})?"
        )
        if not confirm:
            console.print("Cancelled.")
            raise typer.Exit(0)

    try:
        user = record.user or os.environ.get("USER", "")
        connection = ConnectionConfig(host=record.host, user=user)

        with SSHClient(connection) as ssh:
            result = ssh.run(f"scancel {record.slurm_job_id}", warn=True)

            if result.ok:
                console.print(f"[green]Job {record.slurm_job_id} cancelled[/green]")
                job_store.update_job_status(record.name, "CANCELLED")
            else:
                console.print(f"[red]Failed to cancel job:[/red] {result.stderr}")
                raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
