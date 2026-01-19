"""Nodes command for myjob CLI.

Shows cluster node and GPU status.
"""

import os
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from myjob.core.models import ConnectionConfig
from myjob.monitor.nodes import NodeMonitor, LocalNodeMonitor
from myjob.transport.ssh import SSHClient

console = Console()


def _get_state_style(state: str) -> str:
    """Get Rich style for a node state."""
    state_lower = state.lower()
    if state_lower in ("idle",):
        return "green"
    elif state_lower in ("mixed",):
        return "yellow"
    elif state_lower in ("allocated",):
        return "cyan"
    elif state_lower in ("down", "drain", "draining", "fail"):
        return "red"
    elif state_lower in ("completing",):
        return "blue"
    return "white"


def nodes(
    partition: Optional[str] = typer.Option(
        None,
        "--partition",
        "-p",
        help="Filter by partition",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed information",
    ),
    host: Optional[str] = typer.Option(
        None,
        "--host",
        "-H",
        help="Remote host (for remote query)",
    ),
    user: Optional[str] = typer.Option(
        None,
        "--user",
        "-u",
        help="SSH username (for remote query)",
    ),
    local: bool = typer.Option(
        False,
        "--local",
        "-l",
        help="Query local SLURM (default if on cluster)",
    ),
) -> None:
    """Show cluster node and GPU status.

    By default, queries the local SLURM cluster. Use --host to query a remote cluster.
    """
    # Determine if we should use local or remote
    use_local = local or (not host)

    if use_local:
        # Use local SLURM commands
        monitor = LocalNodeMonitor()
        node_list = monitor.get_nodes(partition=partition)

        if not node_list:
            console.print("[yellow]No nodes found.[/yellow]")
            console.print("Make sure you're on a SLURM cluster or use --host for remote query.")
            raise typer.Exit(1)

        summary = monitor.get_summary()
    else:
        # Use SSH for remote query
        if not user:
            user = os.environ.get("USER", "")

        if not user:
            console.print("[red]Error:[/red] SSH username required. Use --user or set USER env var.")
            raise typer.Exit(1)

        try:
            connection = ConnectionConfig(host=host, user=user)
            with SSHClient(connection) as ssh:
                monitor = NodeMonitor(ssh)
                node_list = monitor.get_nodes(partition=partition)
                summary = monitor.get_summary()
        except Exception as e:
            console.print(f"[red]Error connecting to {host}:[/red] {e}")
            raise typer.Exit(1)

    if not node_list:
        console.print("[yellow]No nodes found.[/yellow]")
        return

    # Display nodes table
    table = Table(title="CLUSTER STATUS")
    table.add_column("NODE", style="cyan")
    table.add_column("STATE")
    table.add_column("PARTITION")
    table.add_column("CPU (used/total)")
    table.add_column("MEMORY")
    table.add_column("GPU (free/total)")

    for node in node_list:
        state_style = _get_state_style(node.state)

        gpu_str = "-"
        if node.gpu:
            gpu_str = node.gpu.usage_str
            # Color GPU availability
            if node.gpu.free > 0:
                gpu_str = f"[green]{gpu_str}[/green]"
            else:
                gpu_str = f"[dim]{gpu_str}[/dim]"

        table.add_row(
            node.name,
            f"[{state_style}]{node.state}[/{state_style}]",
            node.partition,
            node.cpu_usage_str,
            node.memory_total,
            gpu_str,
        )

    console.print(table)

    # Display summary
    console.print()
    if verbose and summary.get("nodes_by_state"):
        console.print("[bold]Node States:[/bold]")
        for state, count in sorted(summary["nodes_by_state"].items()):
            state_style = _get_state_style(state)
            console.print(f"  [{state_style}]{state}[/{state_style}]: {count}")
        console.print()

    if summary.get("total_gpus", 0) > 0:
        console.print("[bold]GPU Summary:[/bold]")
        console.print(f"  Total GPUs: {summary['total_gpus']}")
        console.print(f"  Free GPUs:  [green]{summary['free_gpus']}[/green]")

        if summary.get("gpus_by_type"):
            console.print()
            for gpu_type, counts in sorted(summary["gpus_by_type"].items()):
                console.print(
                    f"  {gpu_type.upper()}: "
                    f"[green]{counts['free']}[/green]/{counts['total']} available"
                )
