"""Submit command for myjob CLI."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from myjob.backend.slurm import SlurmBackend
from myjob.core.config import find_config_file, load_config, load_secret_config
from myjob.core.job_id import generate_job_id
from myjob.core.models import ConnectionConfig
from myjob.storage.job_store import create_job_record
from myjob.transport.git_sync import GitSync, get_local_git_info, resolve_git_config
from myjob.transport.ssh import SSHClient

console = Console()


def submit(
    config_file: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file (default: myjob.yaml)",
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
    partition: Optional[str] = typer.Option(
        None,
        "--partition",
        "-p",
        help="SLURM partition (overrides config)",
    ),
    gpus: Optional[int] = typer.Option(
        None,
        "--gpus",
        "-g",
        help="Number of GPUs (overrides config)",
    ),
    time_limit: Optional[str] = typer.Option(
        None,
        "--time",
        "-t",
        help="Time limit in HH:MM:SS (overrides config)",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Job name (overrides config)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without submitting",
    ),
) -> None:
    """Submit a job to a remote SLURM cluster."""
    # Build CLI overrides
    cli_overrides: dict = {}
    if host:
        cli_overrides.setdefault("connection", {})["host"] = host
    if user:
        cli_overrides.setdefault("connection", {})["user"] = user
    if partition:
        cli_overrides.setdefault("slurm", {})["partition"] = partition
    if gpus is not None:
        cli_overrides.setdefault("resources", {})["gpus"] = gpus
    if time_limit:
        cli_overrides.setdefault("resources", {})["time"] = time_limit
    if name:
        cli_overrides["name"] = name

    # Find and validate config file
    config_path = find_config_file(config_file)
    if config_path is None:
        console.print(
            "[red]Error:[/red] No configuration file found. "
            "Create myjob.yaml or use --config to specify one."
        )
        console.print("Run [cyan]myjob init[/cyan] to create a sample configuration.")
        raise typer.Exit(1)

    console.print(f"Using config: [cyan]{config_path}[/cyan]")

    # Load configuration
    try:
        config = load_config(str(config_path), cli_overrides)
    except Exception as e:
        console.print(f"[red]Error loading config:[/red] {e}")
        raise typer.Exit(1)

    # Load secrets
    secret_config = load_secret_config()

    # Merge secret env vars
    secret_env = secret_config.env_vars

    # Get local git info if auto_detect is enabled
    local_git_info = None
    if config.git.auto_detect:
        local_git_info = get_local_git_info()
        if local_git_info:
            console.print(f"Detected git repo: [cyan]{local_git_info.repo_root}[/cyan]")
            console.print(f"  Branch: [cyan]{local_git_info.branch}[/cyan]")
            console.print(f"  Commit: [cyan]{local_git_info.commit[:8]}[/cyan]")

            if local_git_info.has_uncommitted:
                console.print(
                    f"[yellow]Warning:[/yellow] {len(local_git_info.uncommitted_files)} "
                    "uncommitted files detected"
                )

    # Resolve git config with local info
    resolved_git = resolve_git_config(config.git, local_git_info)

    # Generate local job ID
    local_id = generate_job_id()
    console.print(f"Local job ID: [green]{local_id}[/green]")

    # Determine remote working directory
    workspace = Path(config.workspace).expanduser()
    job_dir = f"{workspace}/{config.name}-{local_id}"

    if dry_run:
        console.print("\n[yellow]Dry run mode - no changes will be made[/yellow]")
        console.print(Panel.fit(
            f"[bold]Job Configuration[/bold]\n"
            f"Name: {config.name}\n"
            f"Host: {config.connection.host}\n"
            f"User: {config.connection.user}\n"
            f"Partition: {config.slurm.partition}\n"
            f"Resources: {config.resources.nodes} nodes, "
            f"{config.resources.cpus_per_task} CPUs, "
            f"{config.resources.gpus} GPUs\n"
            f"Time: {config.resources.time}\n"
            f"Command: {config.execution.command}\n"
            f"Remote dir: {job_dir}",
            title="Dry Run",
        ))
        raise typer.Exit(0)

    # Connect to remote
    console.print(f"\nConnecting to [cyan]{config.connection.host}[/cyan]...")

    try:
        with SSHClient(config.connection) as ssh:
            # Verify SLURM is available
            try:
                slurm_version = ssh.check_slurm_version()
                console.print(f"SLURM: [green]{slurm_version}[/green]")
            except RuntimeError as e:
                console.print(f"[red]Error:[/red] {e}")
                raise typer.Exit(1)

            # Sync git repository if configured
            if resolved_git.repo_url:
                console.print(f"Syncing repository to [cyan]{job_dir}[/cyan]...")
                git_sync = GitSync(ssh, resolved_git)
                try:
                    git_sync.clone_or_update(job_dir)
                    console.print("[green]Repository synced[/green]")
                except RuntimeError as e:
                    console.print(f"[red]Error syncing repository:[/red] {e}")
                    raise typer.Exit(1)
            else:
                # Just create the directory
                ssh.ensure_directory(job_dir)

            # Prepare workspace and submit
            console.print("Preparing job submission...")
            slurm_backend = SlurmBackend(ssh, config)

            script_path = slurm_backend.prepare_workspace(job_dir, secret_env)
            console.print(f"Script: [cyan]{script_path}[/cyan]")

            console.print("Submitting job...")
            submit_result = slurm_backend.submit(script_path)

            console.print(
                f"\n[green]Job submitted successfully![/green]\n"
                f"  SLURM Job ID: [bold]{submit_result.slurm_job_id}[/bold]\n"
                f"  Local ID: [bold]{local_id}[/bold]"
            )

            # Save job record
            create_job_record(
                local_id=local_id,
                name=config.name,
                host=config.connection.host,
                remote_dir=job_dir,
                log_dir=submit_result.log_dir,
                command=config.execution.command,
                config_file=str(config_path) if config_path else None,
                slurm_job_id=submit_result.slurm_job_id,
                git_commit=resolved_git.commit,
                git_branch=resolved_git.branch,
            )

            console.print(f"\nTo check status: [cyan]myjob status {local_id}[/cyan]")
            console.print(f"To view logs: [cyan]myjob logs {local_id}[/cyan]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
