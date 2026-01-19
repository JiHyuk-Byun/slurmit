"""Logs command for myjob CLI."""

import os
import sys
from typing import Optional

import typer
from rich.console import Console

from myjob.core.models import ConnectionConfig
from myjob.monitor.logs import LogMonitor
from myjob.storage import job_store
from myjob.transport.ssh import SSHClient

console = Console()


def logs(
    job_id: str = typer.Argument(
        ...,
        help="Job ID (local ID or SLURM job ID)",
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
    # Find job record
    record = job_store.find_job_by_prefix(job_id) if len(job_id) <= 6 else None

    if record is None:
        record = job_store.find_job_by_slurm_id(job_id)

    if record is None:
        console.print(f"[red]Error:[/red] Job not found: {job_id}")
        console.print("Use [cyan]myjob list[/cyan] to see recent jobs.")
        raise typer.Exit(1)

    console.print(f"Job: [cyan]{record.name}[/cyan] ({record.local_id})")
    console.print(f"Host: [cyan]{record.host}[/cyan]")

    try:
        connection = ConnectionConfig(host=record.host, user=os.environ.get("USER", ""))

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
