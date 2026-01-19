"""Submit command for slurmit CLI.

Transfers code and config to remote server using rsync.
"""

import tempfile
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from slurmit.core.config import find_config_file, load_config, load_secret_config
from slurmit.core.metadata import create_metadata, save_metadata, save_uncommitted_patch
from slurmit.storage.job_store import create_job_record, get_job
from slurmit.transport.rsync import (
    check_rsync_available,
    rsync_to_server,
    rsync_file_to_server,
)

console = Console()

# Remote base directory for slurmit
MYJOB_BASE_DIR = "~/slurmit"


def submit(
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Job name (unique identifier for this experiment)",
    ),
    config_file: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file (default: slurmit.yaml)",
    ),
    host: Optional[str] = typer.Option(
        None,
        "--host",
        "-H",
        help="Remote host (overrides config)",
    ),
    user: Optional[str] = typer.Option(
        None,
        "--user",
        "-u",
        help="SSH username (overrides config)",
    ),
    exclude: Optional[list[str]] = typer.Option(
        None,
        "--exclude",
        "-e",
        help="Additional patterns to exclude from rsync",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without making changes",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show verbose rsync output",
    ),
) -> None:
    """Submit a job to remote server (rsync transfer).

    This command:
    1. Creates metadata (git state, config hash)
    2. Saves uncommitted changes as a patch
    3. Transfers code to server via rsync
    4. Copies config and metadata files

    After submit, run 'slurmit run <name>' on the server to execute.
    """
    # Check rsync availability
    if not check_rsync_available():
        console.print("[red]Error:[/red] rsync is not available. Please install rsync.")
        raise typer.Exit(1)

    # Find and validate config file
    config_path = find_config_file(config_file)
    if config_path is None:
        console.print(
            "[red]Error:[/red] No configuration file found. "
            "Create slurmit.yaml or use --config to specify one."
        )
        console.print("Run [cyan]slurmit init[/cyan] to create a sample configuration.")
        raise typer.Exit(1)

    console.print(f"Using config: [cyan]{config_path}[/cyan]")

    # Build CLI overrides
    cli_overrides: dict = {}
    if host:
        cli_overrides.setdefault("connection", {})["host"] = host
    if user:
        cli_overrides.setdefault("connection", {})["user"] = user

    # Load configuration
    try:
        config = load_config(str(config_path), cli_overrides)
    except Exception as e:
        console.print(f"[red]Error loading config:[/red] {e}")
        raise typer.Exit(1)

    # Load secrets
    secret_config = load_secret_config()

    # Get connection details
    remote_host = config.connection.host
    remote_user = config.connection.user
    ssh_key = config.connection.key_file
    ssh_port = config.connection.port

    # Remote paths
    queue_dir = f"{MYJOB_BASE_DIR}/queue/{name}"
    code_dir = f"{queue_dir}/code"

    # Get local project root (directory containing config file)
    local_project_root = config_path.parent

    # Create metadata
    console.print("Creating metadata...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create metadata with git info
        metadata = create_metadata(name, config_path, tmpdir_path)

        # Show git info
        if metadata.git.commit:
            console.print(f"  Git commit: [cyan]{metadata.git.commit[:8]}[/cyan]")
            console.print(f"  Git branch: [cyan]{metadata.git.branch}[/cyan]")
            if metadata.git.dirty:
                console.print("  [yellow]Uncommitted changes detected[/yellow]")
                # Save uncommitted changes to the temp dir
                patch_file = save_uncommitted_patch(tmpdir_path)
                if patch_file:
                    console.print(f"  Saved patch: [cyan]{patch_file}[/cyan]")

        console.print(f"  Config hash: [cyan]{metadata.config_hash}[/cyan]")

        # Save metadata to temp dir
        save_metadata(metadata, tmpdir_path)

        if dry_run:
            console.print("\n[yellow]Dry run mode - no changes will be made[/yellow]")
            console.print(Panel.fit(
                f"[bold]Job Submission Preview[/bold]\n"
                f"Name: {name}\n"
                f"Host: {remote_host}\n"
                f"User: {remote_user}\n"
                f"Source: {local_project_root}\n"
                f"Destination: {remote_user}@{remote_host}:{queue_dir}\n"
                f"Command: {config.execution.command}",
                title="Dry Run",
            ))

            # Show rsync dry-run
            console.print("\n[bold]Rsync dry-run:[/bold]")
            result = rsync_to_server(
                local_path=local_project_root,
                remote_host=remote_host,
                remote_path=code_dir,
                user=remote_user,
                exclude=exclude,
                dry_run=True,
                verbose=True,
                ssh_key=ssh_key,
                port=ssh_port,
            )
            if result.stdout:
                console.print(result.stdout)
            raise typer.Exit(0)

        # Transfer code via rsync
        console.print(f"\nSyncing code to [cyan]{remote_host}:{code_dir}[/cyan]...")
        result = rsync_to_server(
            local_path=local_project_root,
            remote_host=remote_host,
            remote_path=code_dir,
            user=remote_user,
            exclude=exclude,
            delete=True,
            verbose=verbose,
            ssh_key=ssh_key,
            port=ssh_port,
        )

        if not result.success:
            console.print(f"[red]Error:[/red] rsync failed: {result.stderr}")
            raise typer.Exit(1)

        if verbose and result.stdout:
            console.print(result.stdout)
        console.print("[green]Code synced successfully[/green]")

        # Transfer config file
        console.print("Transferring config file...")
        result = rsync_file_to_server(
            local_file=config_path,
            remote_host=remote_host,
            remote_path=f"{queue_dir}/slurmit.yaml",
            user=remote_user,
            ssh_key=ssh_key,
            port=ssh_port,
        )
        if not result.success:
            console.print(f"[red]Error:[/red] Failed to transfer config: {result.stderr}")
            raise typer.Exit(1)

        # Transfer metadata.json
        console.print("Transferring metadata...")
        metadata_file = tmpdir_path / "metadata.json"
        result = rsync_file_to_server(
            local_file=metadata_file,
            remote_host=remote_host,
            remote_path=f"{queue_dir}/metadata.json",
            user=remote_user,
            ssh_key=ssh_key,
            port=ssh_port,
        )
        if not result.success:
            console.print(f"[red]Error:[/red] Failed to transfer metadata: {result.stderr}")
            raise typer.Exit(1)

        # Transfer uncommitted.patch if exists
        patch_file = tmpdir_path / "uncommitted.patch"
        if patch_file.exists():
            result = rsync_file_to_server(
                local_file=patch_file,
                remote_host=remote_host,
                remote_path=f"{queue_dir}/uncommitted.patch",
                user=remote_user,
                ssh_key=ssh_key,
                port=ssh_port,
            )
            if not result.success:
                console.print(f"[yellow]Warning:[/yellow] Failed to transfer patch: {result.stderr}")

        # Transfer secret.yaml if exists
        secret_path = config_path.parent / "secret.yaml"
        if secret_path.exists():
            console.print("Transferring secrets...")
            result = rsync_file_to_server(
                local_file=secret_path,
                remote_host=remote_host,
                remote_path=f"{queue_dir}/secret.yaml",
                user=remote_user,
                ssh_key=ssh_key,
                port=ssh_port,
            )
            if not result.success:
                console.print(f"[yellow]Warning:[/yellow] Failed to transfer secrets: {result.stderr}")

    # Save job record locally
    create_job_record(
        name=name,
        host=remote_host,
        user=remote_user,
        queue_dir=queue_dir,
        command=config.execution.command,
        config_file=str(config_path),
        git_commit=metadata.git.commit if metadata.git.commit else None,
        git_branch=metadata.git.branch if metadata.git.branch else None,
        config_hash=metadata.config_hash,
    )

    console.print(
        f"\n[green]Job submitted successfully![/green]\n"
        f"  Name: [bold]{name}[/bold]\n"
        f"  Remote: [cyan]{remote_host}:{queue_dir}[/cyan]"
    )

    console.print(f"\n[bold]Next steps:[/bold]")
    console.print(f"  1. SSH to server: [cyan]ssh {remote_user}@{remote_host}[/cyan]")
    console.print(f"  2. Run the job:   [cyan]slurmit run {name}[/cyan]")
    console.print(f"\nOr check status:    [cyan]slurmit status {name}[/cyan]")
