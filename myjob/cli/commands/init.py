"""Init command for myjob CLI - interactive configuration file generation."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from myjob.core.config import create_sample_config, create_sample_secret

console = Console()


def init(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing configuration files",
    ),
    minimal: bool = typer.Option(
        False,
        "--minimal",
        "-m",
        help="Create minimal configuration without interactive prompts",
    ),
) -> None:
    """Initialize configuration files for myjob.

    Creates myjob.yaml and optionally secret.yaml in the current directory.
    """
    config_path = Path.cwd() / "myjob.yaml"
    secret_path = Path.cwd() / "secret.yaml"

    # Check for existing files
    if config_path.exists() and not force:
        if not Confirm.ask(
            f"[yellow]myjob.yaml already exists. Overwrite?[/yellow]"
        ):
            console.print("Aborted.")
            raise typer.Exit(0)

    if minimal:
        # Just create sample files without prompts
        _write_sample_config(config_path)
        console.print(f"[green]Created:[/green] {config_path}")

        if Confirm.ask("Create secret.yaml for sensitive data?", default=True):
            _write_sample_secret(secret_path)
            console.print(f"[green]Created:[/green] {secret_path}")
            console.print(
                "[yellow]Remember to add secret.yaml to .gitignore![/yellow]"
            )

        console.print("\nEdit the configuration files to match your setup.")
        return

    # Interactive configuration
    console.print(Panel.fit(
        "[bold]myjob Configuration Setup[/bold]\n"
        "This wizard will help you create configuration files.",
        title="Welcome",
    ))

    # Gather basic information
    console.print("\n[bold]Connection Settings[/bold]")
    host = Prompt.ask("Remote host", default="cluster.example.com")
    user = Prompt.ask("SSH username", default=Path.home().name)

    console.print("\n[bold]SLURM Settings[/bold]")
    partition = Prompt.ask("Default partition", default="gpu")
    account = Prompt.ask("Account (optional, press Enter to skip)", default="")

    console.print("\n[bold]Resource Defaults[/bold]")
    gpus = Prompt.ask("Default GPUs", default="1")
    cpus = Prompt.ask("CPUs per task", default="4")
    memory = Prompt.ask("Memory", default="32G")
    time_limit = Prompt.ask("Time limit", default="4:00:00")

    console.print("\n[bold]Execution[/bold]")
    command = Prompt.ask("Default command", default="python train.py")

    console.print("\n[bold]Job Settings[/bold]")
    job_name = Prompt.ask("Default job name", default="myjob")
    workspace = Prompt.ask("Remote workspace directory", default="~/myjob-workspace")

    # Generate configuration
    config_content = _generate_config(
        host=host,
        user=user,
        partition=partition,
        account=account if account else None,
        gpus=int(gpus),
        cpus=int(cpus),
        memory=memory,
        time_limit=time_limit,
        command=command,
        job_name=job_name,
        workspace=workspace,
    )

    # Write configuration
    with open(config_path, "w") as f:
        f.write(config_content)
    console.print(f"\n[green]Created:[/green] {config_path}")

    # Ask about secrets
    if Confirm.ask("\nCreate secret.yaml for sensitive data (API keys, etc.)?", default=True):
        if secret_path.exists() and not force:
            if not Confirm.ask(
                f"[yellow]secret.yaml already exists. Overwrite?[/yellow]"
            ):
                console.print("Skipped secret.yaml")
            else:
                _write_sample_secret(secret_path)
                console.print(f"[green]Created:[/green] {secret_path}")
        else:
            _write_sample_secret(secret_path)
            console.print(f"[green]Created:[/green] {secret_path}")

        console.print("[yellow]Remember to add secret.yaml to .gitignore![/yellow]")

        # Check/create .gitignore
        gitignore_path = Path.cwd() / ".gitignore"
        if gitignore_path.exists():
            with open(gitignore_path) as f:
                gitignore_content = f.read()
            if "secret.yaml" not in gitignore_content:
                if Confirm.ask("Add secret.yaml to .gitignore?", default=True):
                    with open(gitignore_path, "a") as f:
                        f.write("\n# myjob secrets\nsecret.yaml\n")
                    console.print("[green]Added secret.yaml to .gitignore[/green]")
        else:
            if Confirm.ask("Create .gitignore with secret.yaml?", default=True):
                with open(gitignore_path, "w") as f:
                    f.write("# myjob secrets\nsecret.yaml\n")
                console.print(f"[green]Created:[/green] {gitignore_path}")

    console.print("\n[bold green]Setup complete![/bold green]")
    console.print("Next steps:")
    console.print("  1. Edit [cyan]myjob.yaml[/cyan] to configure your job")
    console.print("  2. Add API keys to [cyan]secret.yaml[/cyan] if needed")
    console.print("  3. Run [cyan]myjob submit[/cyan] to submit a job")


def _generate_config(
    host: str,
    user: str,
    partition: str,
    account: Optional[str],
    gpus: int,
    cpus: int,
    memory: str,
    time_limit: str,
    command: str,
    job_name: str,
    workspace: str,
) -> str:
    """Generate configuration file content."""
    lines = [
        "# myjob configuration file",
        f"name: {job_name}",
        "",
        "# Connection settings",
        "connection:",
        f"  host: {host}",
        f"  user: {user}",
        "  # key_file: ~/.ssh/id_rsa  # Uncomment if needed",
        "",
        "# SLURM settings",
        "slurm:",
        f"  partition: {partition}",
    ]

    if account:
        lines.append(f"  account: {account}")
    else:
        lines.append("  # account: my-account  # Uncomment if needed")

    lines.extend([
        "",
        "# Resource allocation",
        "resources:",
        "  nodes: 1",
        "  ntasks: 1",
        f"  cpus_per_task: {cpus}",
        f"  gpus: {gpus}",
        "  # gpu_type: a100  # Uncomment to specify GPU type",
        f"  memory: {memory}",
        f'  time: "{time_limit}"',
        "",
        "# Git configuration (auto-detects from local repo)",
        "git:",
        "  auto_detect: true",
        "  # repo_url: https://github.com/user/repo.git",
        "  # branch: main",
        "",
        "# Execution settings",
        "execution:",
        f"  command: {command}",
        "  modules:",
        "    # - cuda/11.8",
        "    # - python/3.10",
        "  setup_commands:",
        "    # - pip install -r requirements.txt",
        "  env_vars:",
        "    # WANDB_PROJECT: my-project",
        "",
        "# Output settings",
        "output:",
        '  stdout: "%x_%j.out"',
        '  stderr: "%x_%j.err"',
        "  log_dir: logs",
        "",
        f"workspace: {workspace}",
    ])

    return "\n".join(lines) + "\n"


def _write_sample_config(path: Path) -> None:
    """Write sample configuration file."""
    content = create_sample_config()
    with open(path, "w") as f:
        f.write(content)


def _write_sample_secret(path: Path) -> None:
    """Write sample secret configuration file."""
    content = create_sample_secret()
    with open(path, "w") as f:
        f.write(content)
