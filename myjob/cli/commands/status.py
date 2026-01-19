"""Status command for myjob CLI."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from myjob.core.models import ConnectionConfig
from myjob.monitor.status import JobState, StatusMonitor
from myjob.storage import job_store
from myjob.transport.ssh import SSHClient

console = Console()


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


def status(
    job_id: str = typer.Argument(
        ...,
        help="Job ID (local ID or SLURM job ID)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed information",
    ),
) -> None:
    """Check the status of a submitted job."""
    # Try to find job by local ID first
    record = job_store.find_job_by_prefix(job_id) if len(job_id) <= 6 else None

    if record is None:
        # Try by SLURM job ID
        record = job_store.find_job_by_slurm_id(job_id)

    if record is None:
        console.print(f"[red]Error:[/red] Job not found: {job_id}")
        console.print("Use [cyan]myjob list[/cyan] to see recent jobs.")
        raise typer.Exit(1)

    console.print(f"Job: [cyan]{record.name}[/cyan] ({record.local_id})")
    console.print(f"Host: [cyan]{record.host}[/cyan]")
    console.print(f"Submitted: {record.submitted_at}")

    if record.slurm_job_id:
        # Connect to remote to get current status
        console.print(f"\nQuerying SLURM status for job [cyan]{record.slurm_job_id}[/cyan]...")

        try:
            # Create minimal connection config
            connection = ConnectionConfig(host=record.host, user="")
            # Try to get user from config or use current user
            import os
            connection = ConnectionConfig(host=record.host, user=os.environ.get("USER", ""))

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
                        record.local_id,
                        slurm_status.state.value,
                    )
                else:
                    console.print("[yellow]Job not found in SLURM queue or history[/yellow]")

        except Exception as e:
            console.print(f"[yellow]Could not connect to remote:[/yellow] {e}")
            console.print(f"Last known status: {record.status}")
    else:
        console.print(f"Status: {record.status}")

    if verbose:
        console.print(f"\n[bold]Details:[/bold]")
        console.print(f"  Remote dir: {record.remote_dir}")
        console.print(f"  Log dir: {record.log_dir}")
        console.print(f"  Command: {record.command}")
        if record.git_branch:
            console.print(f"  Git branch: {record.git_branch}")
        if record.git_commit:
            console.print(f"  Git commit: {record.git_commit[:8]}")


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
) -> None:
    """List recent submitted jobs."""
    max_limit = 100 if all_jobs else limit
    records = job_store.list_jobs(limit=max_limit)

    if not records:
        console.print("No jobs found.")
        console.print("Submit a job with [cyan]myjob submit[/cyan]")
        return

    table = Table(title="Recent Jobs")
    table.add_column("Local ID", style="cyan")
    table.add_column("SLURM ID")
    table.add_column("Name")
    table.add_column("Host")
    table.add_column("Status")
    table.add_column("Submitted")

    for record in records:
        status_style = "green" if record.status == "RUNNING" else (
            "yellow" if record.status == "PENDING" else (
                "red" if record.status in ("FAILED", "CANCELLED") else "blue"
            )
        )
        table.add_row(
            record.local_id,
            record.slurm_job_id or "-",
            record.name,
            record.host,
            f"[{status_style}]{record.status}[/{status_style}]",
            record.submitted_at[:19],  # Trim milliseconds
        )

    console.print(table)


def cancel(
    job_id: str = typer.Argument(
        ...,
        help="Job ID to cancel (local ID or SLURM job ID)",
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
    record = job_store.find_job_by_prefix(job_id) if len(job_id) <= 6 else None

    if record is None:
        record = job_store.find_job_by_slurm_id(job_id)

    if record is None:
        console.print(f"[red]Error:[/red] Job not found: {job_id}")
        raise typer.Exit(1)

    if not record.slurm_job_id:
        console.print("[red]Error:[/red] No SLURM job ID associated with this job")
        raise typer.Exit(1)

    if not force:
        confirm = typer.confirm(
            f"Cancel job {record.name} (SLURM ID: {record.slurm_job_id})?"
        )
        if not confirm:
            console.print("Cancelled.")
            raise typer.Exit(0)

    try:
        import os
        connection = ConnectionConfig(host=record.host, user=os.environ.get("USER", ""))

        with SSHClient(connection) as ssh:
            from myjob.backend.slurm import SlurmBackend
            from myjob.core.models import JobConfig, ExecutionConfig

            # Minimal config for cancel operation
            result = ssh.run(f"scancel {record.slurm_job_id}", warn=True)

            if result.ok:
                console.print(f"[green]Job {record.slurm_job_id} cancelled[/green]")
                job_store.update_job_status(record.local_id, "CANCELLED")
            else:
                console.print(f"[red]Failed to cancel job:[/red] {result.stderr}")
                raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
