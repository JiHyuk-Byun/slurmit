"""Main CLI entry point for slurmit."""

import typer
from rich.console import Console

from slurmit import __version__
from slurmit.cli.commands import init, jobs, logs, nodes, reproduce, run, status, submit

app = typer.Typer(
    name="slurmit",
    help="CLI tool for submitting and managing SLURM jobs on remote clusters.",
)
console = Console()

# Register subcommands
app.command(name="submit")(submit.submit)
app.command(name="run")(run.run)
app.command(name="status")(status.status)
app.command(name="logs")(logs.logs)
app.command(name="init")(init.init)
app.command(name="list")(status.list_jobs)
app.command(name="cancel")(status.cancel)
app.command(name="nodes")(nodes.nodes)
app.command(name="jobs")(jobs.jobs)
app.command(name="reproduce")(reproduce.reproduce)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
    ),
) -> None:
    """slurmit - Submit and manage SLURM jobs on remote clusters."""
    if version:
        console.print(f"slurmit version {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


if __name__ == "__main__":
    app()
