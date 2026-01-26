"""Jobs command for slurmit CLI.

Shows running SLURM jobs on the cluster.
"""

import os
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from slurmit.core.models import ConnectionConfig
from slurmit.monitor.status import JobState, LocalStatusMonitor, StatusMonitor
from slurmit.transport.ssh import SSHClient

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


def jobs(
    partition: Optional[str] = typer.Option(
        None,
        "--partition",
        "-p",
        help="Filter by partition",
    ),
    user: Optional[str] = typer.Option(
        None,
        "--user",
        "-u",
        help="Filter by user",
    ),
    node: Optional[str] = typer.Option(
        None,
        "--node",
        "-n",
        help="Filter by node",
    ),
    mine: bool = typer.Option(
        False,
        "--mine",
        "-m",
        help="Show only my jobs",
    ),
    host: Optional[str] = typer.Option(
        None,
        "--host",
        "-H",
        help="Remote host (for remote query)",
    ),
    ssh_user: Optional[str] = typer.Option(
        None,
        "--ssh-user",
        help="SSH username (for remote query)",
    ),
    local: bool = typer.Option(
        False,
        "--local",
        "-l",
        help="Query local SLURM (default if on cluster)",
    ),
) -> None:
    """Show running SLURM jobs on the cluster.

    By default, shows all jobs with your jobs highlighted.
    Use --mine to show only your jobs.
    """
    # Determine if we should use local or remote
    use_local = local or (not host)

    # Get current user for highlighting
    current_user = os.environ.get("USER", "")

    # Determine user filter
    if mine:
        filter_user = current_user  # Show only my jobs
    elif user:
        filter_user = user  # Use specified user
    else:
        filter_user = None  # Show all jobs (default)

    if use_local:
        # Use local SLURM commands
        monitor = LocalStatusMonitor()
        job_list = monitor.list_all_jobs(
            user=filter_user,
            partition=partition,
            node=node,
        )

        if not job_list:
            if filter_user:
                console.print(f"[yellow]No jobs found for user '{filter_user}'.[/yellow]")
            else:
                console.print("[yellow]No jobs found.[/yellow]")
            console.print("Make sure you're on a SLURM cluster or use --host for remote query.")
            raise typer.Exit(0)
    else:
        # Use SSH for remote query
        remote_user = ssh_user or current_user

        if not remote_user:
            console.print("[red]Error:[/red] SSH username required. Use --ssh-user or set USER env var.")
            raise typer.Exit(1)

        try:
            connection = ConnectionConfig(host=host, user=remote_user)
            with SSHClient(connection) as ssh:
                monitor = StatusMonitor(ssh)
                job_list = monitor.list_all_jobs(
                    user=filter_user,
                    partition=partition,
                    node=node,
                )
        except Exception as e:
            console.print(f"[red]Error connecting to {host}:[/red] {e}")
            raise typer.Exit(1)

        if not job_list:
            if filter_user:
                console.print(f"[yellow]No jobs found for user '{filter_user}'.[/yellow]")
            else:
                console.print("[yellow]No jobs found.[/yellow]")
            raise typer.Exit(0)

    # Display jobs table
    table = Table(title="RUNNING JOBS")
    table.add_column("JOB ID")
    table.add_column("NAME")
    table.add_column("STATE")
    table.add_column("PARTITION")
    table.add_column("NODE(S)")
    table.add_column("GPUS")
    table.add_column("TIME")
    table.add_column("LIMIT")

    my_jobs = 0
    for job in job_list:
        state_style = _get_state_style(job.state)
        is_mine = job.user == current_user

        if is_mine:
            my_jobs += 1

        # Format GPU string
        gpu_str = job.gpus if job.gpus and job.gpus != "-" else "-"

        # Highlight my jobs with cyan, others dimmed
        if is_mine:
            job_id_str = f"[cyan bold]{job.job_id}[/cyan bold]"
            name_str = f"[cyan]{job.name[:20] if len(job.name) > 20 else job.name}[/cyan]"
        else:
            job_id_str = f"[dim]{job.job_id}[/dim]"
            name_str = f"[dim]{job.name[:20] if len(job.name) > 20 else job.name}[/dim]"

        table.add_row(
            job_id_str,
            name_str,
            f"[{state_style}]{job.state.value}[/{state_style}]",
            job.partition if is_mine else f"[dim]{job.partition}[/dim]",
            job.nodes or "-" if is_mine else f"[dim]{job.nodes or '-'}[/dim]",
            gpu_str if is_mine else f"[dim]{gpu_str}[/dim]",
            job.elapsed if is_mine else f"[dim]{job.elapsed}[/dim]",
            job.time_limit if is_mine else f"[dim]{job.time_limit}[/dim]",
        )

    console.print(table)

    # Print summary
    console.print()
    running = sum(1 for j in job_list if j.state == JobState.RUNNING)
    pending = sum(1 for j in job_list if j.state == JobState.PENDING)
    console.print(f"Total: {len(job_list)} jobs ([green]{running} running[/green], [yellow]{pending} pending[/yellow])")
    if my_jobs > 0:
        console.print(f"My jobs: [cyan]{my_jobs}[/cyan]")
