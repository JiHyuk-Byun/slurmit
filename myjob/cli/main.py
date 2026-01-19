"""Main CLI entry point for myjob."""

import typer
from rich.console import Console

from myjob import __version__
from myjob.cli.commands import init, logs, status, submit

app = typer.Typer(
    name="myjob",
    help="CLI tool for submitting and managing SLURM jobs on remote clusters.",
)
console = Console()

# Register subcommands
app.command(name="submit")(submit.submit)
app.command(name="status")(status.status)
app.command(name="logs")(logs.logs)
app.command(name="init")(init.init)
app.command(name="list")(status.list_jobs)
app.command(name="cancel")(status.cancel)


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
    """myjob - Submit and manage SLURM jobs on remote clusters."""
    if version:
        console.print(f"myjob version {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


if __name__ == "__main__":
    app()
