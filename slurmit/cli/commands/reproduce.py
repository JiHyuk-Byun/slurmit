"""Reproduce command for slurmit CLI.

Reproduces a past experiment from its metadata.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from slurmit.core.metadata import JobMetadata, load_metadata

console = Console()

# Base directory for slurmit on server
MYJOB_BASE_DIR = Path.home() / "slurmit"


def reproduce(
    run_id: str = typer.Argument(
        ...,
        help="Run ID to reproduce (e.g., my-exp_20240119_143022)",
    ),
    new_name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Name for the new job (default: <original>-repro)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show reproduction steps without executing",
    ),
    apply_patch: bool = typer.Option(
        True,
        "--apply-patch/--no-patch",
        help="Apply uncommitted.patch if available",
    ),
) -> None:
    """Reproduce a past experiment from its metadata.

    This command:
    1. Loads metadata from the specified run
    2. Checks out the same git commit
    3. Optionally applies any uncommitted changes
    4. Copies the run to a new queue entry
    """
    # Find the run directory
    runs_base = MYJOB_BASE_DIR / "runs"
    run_dir = runs_base / run_id

    if not run_dir.exists():
        # Try to find a partial match
        matches = list(runs_base.glob(f"*{run_id}*"))
        if len(matches) == 1:
            run_dir = matches[0]
            run_id = run_dir.name
        elif len(matches) > 1:
            console.print(f"[red]Error:[/red] Multiple runs match '{run_id}':")
            for m in matches[:5]:
                console.print(f"  - {m.name}")
            raise typer.Exit(1)
        else:
            console.print(f"[red]Error:[/red] Run not found: {run_id}")
            console.print("\nUse [cyan]slurmit list --runs[/cyan] to see available runs.")
            raise typer.Exit(1)

    console.print(f"Found run: [cyan]{run_id}[/cyan]")
    console.print(f"  Directory: {run_dir}")

    # Load metadata
    metadata_file = run_dir / "metadata.json"
    if not metadata_file.exists():
        console.print(f"[red]Error:[/red] No metadata.json found in {run_dir}")
        console.print("This run may have been created before metadata tracking was enabled.")
        raise typer.Exit(1)

    metadata = load_metadata(metadata_file)
    if metadata is None:
        console.print(f"[red]Error:[/red] Failed to parse metadata.json")
        raise typer.Exit(1)

    # Display metadata
    console.print(Panel.fit(
        f"[bold]Original Experiment[/bold]\n"
        f"Job name: {metadata.job_name}\n"
        f"Submitted: {metadata.submitted_at}\n"
        f"From: {metadata.submitted_from}\n"
        f"Git repo: {metadata.git.repo or '(none)'}\n"
        f"Git branch: {metadata.git.branch}\n"
        f"Git commit: {metadata.git.commit[:8] if metadata.git.commit else '(none)'}\n"
        f"Was dirty: {metadata.git.dirty}\n"
        f"Config hash: {metadata.config_hash}",
        title="Metadata",
    ))

    # Determine new job name
    original_name = metadata.job_name
    job_name = new_name or f"{original_name}-repro"

    console.print(f"\nNew job name: [cyan]{job_name}[/cyan]")

    # Check for uncommitted.patch
    patch_file = run_dir / "uncommitted.patch"
    has_patch = patch_file.exists() and patch_file.stat().st_size > 0

    if has_patch:
        if apply_patch:
            console.print("[yellow]Note:[/yellow] Will apply uncommitted.patch from original run")
        else:
            console.print("[yellow]Note:[/yellow] uncommitted.patch exists but will NOT be applied (--no-patch)")

    if dry_run:
        console.print("\n[yellow]Dry run mode - showing reproduction steps:[/yellow]")
        console.print(f"\n1. Create new queue entry: ~/slurmit/queue/{job_name}/")
        console.print(f"2. Copy code from: {run_dir}/code/")
        if metadata.git.commit:
            console.print(f"3. Checkout git commit: {metadata.git.commit[:8]}")
        if has_patch and apply_patch:
            console.print(f"4. Apply patch: {patch_file}")
        console.print(f"5. Copy config files")
        console.print(f"\nAfter reproduction, run: [cyan]slurmit run {job_name}[/cyan]")
        raise typer.Exit(0)

    # Create new queue directory
    queue_dir = MYJOB_BASE_DIR / "queue" / job_name
    if queue_dir.exists():
        console.print(f"[yellow]Warning:[/yellow] Queue directory already exists: {queue_dir}")
        if not typer.confirm("Overwrite existing queue entry?"):
            raise typer.Exit(1)
        shutil.rmtree(queue_dir)

    queue_dir.mkdir(parents=True)
    code_dir = queue_dir / "code"

    # Copy code from the run
    console.print("Copying code...")
    run_code_dir = run_dir / "code"
    if run_code_dir.exists():
        shutil.copytree(run_code_dir, code_dir)
    else:
        console.print(f"[yellow]Warning:[/yellow] No code directory in run, creating empty")
        code_dir.mkdir()

    # If git commit is specified and we have a repo, try to checkout
    if metadata.git.commit and metadata.git.repo:
        console.print(f"Checking out commit: [cyan]{metadata.git.commit[:8]}[/cyan]...")
        try:
            # Check if code_dir is a git repo
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=code_dir,
                capture_output=True,
            )
            if result.returncode == 0:
                # It's a git repo, try to checkout the commit
                subprocess.run(
                    ["git", "checkout", metadata.git.commit],
                    cwd=code_dir,
                    capture_output=True,
                )
                console.print("[green]Checked out original commit[/green]")
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Could not checkout commit: {e}")

    # Apply patch if requested
    if has_patch and apply_patch:
        console.print("Applying uncommitted.patch...")
        try:
            result = subprocess.run(
                ["git", "apply", str(patch_file)],
                cwd=code_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                console.print("[green]Patch applied successfully[/green]")
            else:
                console.print(f"[yellow]Warning:[/yellow] Failed to apply patch: {result.stderr}")
                # Copy the patch anyway for manual application
                shutil.copy(patch_file, queue_dir / "uncommitted.patch")
                console.print("Patch file copied to queue directory for manual application")
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Could not apply patch: {e}")

    # Copy config files
    console.print("Copying config files...")
    config_files = ["slurmit.yaml", "secret.yaml", "metadata.json"]
    for cf in config_files:
        src = run_dir / cf
        if src.exists():
            shutil.copy(src, queue_dir / cf)

    # Update metadata for new run
    new_metadata = {
        "job_name": job_name,
        "reproduced_from": run_id,
        "original_metadata": metadata.to_dict(),
    }
    (queue_dir / "metadata.json").write_text(json.dumps(new_metadata, indent=2))

    console.print(
        f"\n[green]Reproduction ready![/green]\n"
        f"  Queue dir: {queue_dir}\n"
        f"\nTo run the reproduced experiment:\n"
        f"  [cyan]slurmit run {job_name}[/cyan]"
    )
