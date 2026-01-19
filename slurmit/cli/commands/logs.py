"""Logs command for slurmit CLI."""

import os
import sys
from typing import Optional

import typer
from rich.console import Console

from slurmit.core.models import ConnectionConfig
from slurmit.monitor.logs import LogMonitor
from slurmit.storage import job_store
from slurmit.transport.ssh import SSHClient

console = Console()


def logs(
    job_name: str = typer.Argument(
        ...,
        help="Job name or SLURM job ID",
    ),
    follow: bool = typer.Option(
        False,
        "--follow",
        "-f",
        help="Follow log output (like tail -f)",
    ),
    lines: int = typer.Option(
        50,
        "--lines",
        "-n",
        help="Number of lines to show",
    ),
    stderr: bool = typer.Option(
        False,
        "--stderr",
        "-e",
        help="Show stderr instead of stdout",
    ),
    both: bool = typer.Option(
        False,
        "--both",
        "-b",
        help="Show both stdout and stderr",
    ),
) -> None:
    """View logs for a submitted job."""
    # Find job record by name first
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

    # Check if job has been run
    if not record.log_dir:
        console.print("[yellow]No log directory set.[/yellow]")
        console.print("The job may not have been run yet.")
        if record.status == "QUEUED":
            console.print(f"\nRun the job first: [cyan]slurmit run {record.name}[/cyan] (on server)")
        raise typer.Exit(1)

    try:
        user = record.user or os.environ.get("USER", "")
        connection = ConnectionConfig(host=record.host, user=user)

        with SSHClient(connection) as ssh:
            log_monitor = LogMonitor(ssh)

            if both:
                # Show both stdout and stderr
                log_content = log_monitor.get_logs(record, lines=lines)

                if log_content.stdout_path:
                    console.print(f"\n[bold cyan]STDOUT[/bold cyan] ({log_content.stdout_path}):")
                    console.print("-" * 60)
                    if log_content.stdout:
                        console.print(log_content.stdout)
                    else:
                        console.print("[dim](empty)[/dim]")

                if log_content.stderr_path:
                    console.print(f"\n[bold yellow]STDERR[/bold yellow] ({log_content.stderr_path}):")
                    console.print("-" * 60)
                    if log_content.stderr:
                        console.print(log_content.stderr)
                    else:
                        console.print("[dim](empty)[/dim]")

                if not log_content.stdout_path and not log_content.stderr_path:
                    console.print("\n[yellow]No log files found yet.[/yellow]")
                    console.print("The job may still be starting.")

            else:
                # Show single stream
                stream = "stderr" if stderr else "stdout"
                console.print(f"Showing: [cyan]{stream}[/cyan]")
                console.print("-" * 60)

                if follow:
                    console.print("[dim]Following log output (Ctrl+C to stop)...[/dim]\n")
                    try:
                        for chunk in log_monitor.tail_logs(record, follow=True, lines=lines, stream=stream):
                            # Print without Rich formatting for real-time output
                            sys.stdout.write(chunk)
                            sys.stdout.flush()
                    except KeyboardInterrupt:
                        console.print("\n[dim]Stopped following.[/dim]")
                else:
                    for chunk in log_monitor.tail_logs(record, follow=False, lines=lines, stream=stream):
                        console.print(chunk)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
