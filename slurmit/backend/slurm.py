"""SLURM script generation and job submission."""

from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

from slurmit.core.models import JobConfig
from slurmit.transport.ssh import SSHClient


@dataclass
class SubmitResult:
    """Result of job submission."""

    slurm_job_id: str
    script_path: str
    log_dir: str


class SlurmBackend:
    """SLURM backend for job submission."""

    def __init__(self, ssh_client: SSHClient, config: JobConfig):
        """Initialize SLURM backend."""
        self.ssh = ssh_client
        self.config = config

    def generate_sbatch_script(self, working_dir: str) -> str:
        """Generate sbatch script content."""
        lines = ["#!/bin/bash"]

        # Job name
        lines.append(f"#SBATCH --job-name={self.config.name}")

        # Output files
        log_dir = f"{working_dir}/{self.config.output.log_dir}"
        lines.append(f"#SBATCH --output={log_dir}/{self.config.output.stdout}")
        lines.append(f"#SBATCH --error={log_dir}/{self.config.output.stderr}")

        # Partition and account
        lines.append(f"#SBATCH --partition={self.config.slurm.partition}")
        if self.config.slurm.account:
            lines.append(f"#SBATCH --account={self.config.slurm.account}")
        if self.config.slurm.qos:
            lines.append(f"#SBATCH --qos={self.config.slurm.qos}")

        # Resources
        resources = self.config.resources
        lines.append(f"#SBATCH --nodes={resources.nodes}")
        lines.append(f"#SBATCH --ntasks={resources.ntasks}")
        lines.append(f"#SBATCH --cpus-per-task={resources.cpus_per_task}")
        lines.append(f"#SBATCH --mem={resources.memory}")
        lines.append(f"#SBATCH --time={resources.time}")

        # GPU resources
        if resources.gpus > 0:
            if resources.gpu_type:
                lines.append(f"#SBATCH --gres=gpu:{resources.gpu_type}:{resources.gpus}")
            else:
                lines.append(f"#SBATCH --gres=gpu:{resources.gpus}")

        # Extra SLURM options
        for key, value in self.config.slurm.extra_options.items():
            lines.append(f"#SBATCH --{key}={value}")

        lines.append("")

        # Print job info
        lines.append("# Print job information")
        lines.append('echo "Job ID: $SLURM_JOB_ID"')
        lines.append('echo "Node: $SLURM_NODELIST"')
        lines.append('echo "Start time: $(date)"')
        lines.append("")

        # Change to working directory
        lines.append("# Change to working directory")
        lines.append(f"cd {working_dir}")
        lines.append("")

        # Source environment file if exists
        lines.append("# Source environment")
        lines.append(f'if [ -f "{working_dir}/env.sh" ]; then')
        lines.append(f'    source "{working_dir}/env.sh"')
        lines.append("fi")
        lines.append("")

        # Load modules
        if self.config.execution.modules:
            lines.append("# Load modules")
            for module in self.config.execution.modules:
                lines.append(f"module load {module}")
            lines.append("")

        # Setup commands
        if self.config.execution.setup_commands:
            lines.append("# Setup commands")
            for cmd in self.config.execution.setup_commands:
                lines.append(cmd)
            lines.append("")

        # Main command
        lines.append("# Execute main command")
        lines.append(self.config.execution.command)
        lines.append("")

        # Print end time
        lines.append('echo "End time: $(date)"')

        return "\n".join(lines)

    def generate_env_script(self, extra_env: dict[str, str] | None = None) -> str:
        """Generate environment setup script."""
        lines = ["#!/bin/bash", "# Environment variables for slurmit", ""]

        # From config
        for key, value in self.config.execution.env_vars.items():
            lines.append(f'export {key}="{value}"')

        # Extra env vars (e.g., from secret.yaml)
        if extra_env:
            lines.append("")
            lines.append("# Secret environment variables")
            for key, value in extra_env.items():
                lines.append(f'export {key}="{value}"')

        return "\n".join(lines)

    def prepare_workspace(self, job_dir: str, extra_env: dict[str, str] | None = None) -> str:
        """Prepare the workspace directory for job submission.

        Returns the path to the sbatch script.
        """
        # Ensure directories exist
        self.ssh.ensure_directory(job_dir)
        log_dir = f"{job_dir}/{self.config.output.log_dir}"
        self.ssh.ensure_directory(log_dir)

        # Generate and write sbatch script
        script_content = self.generate_sbatch_script(job_dir)
        script_path = f"{job_dir}/job.sbatch"
        self.ssh.write_file(script_path, script_content)

        # Generate and write env script
        env_content = self.generate_env_script(extra_env)
        env_path = f"{job_dir}/env.sh"
        self.ssh.write_file(env_path, env_content)

        return script_path

    def submit(self, script_path: str) -> SubmitResult:
        """Submit the job using sbatch.

        Returns the SLURM job ID.
        """
        result = self.ssh.run(f"sbatch {script_path}", warn=True)

        if not result.ok:
            raise RuntimeError(f"Failed to submit job: {result.stderr}")

        # Parse job ID from output: "Submitted batch job 12345"
        output = result.stdout.strip()
        if "Submitted batch job" not in output:
            raise RuntimeError(f"Unexpected sbatch output: {output}")

        slurm_job_id = output.split()[-1]

        # Derive log directory from script path
        job_dir = str(Path(script_path).parent)
        log_dir = f"{job_dir}/{self.config.output.log_dir}"

        return SubmitResult(
            slurm_job_id=slurm_job_id,
            script_path=script_path,
            log_dir=log_dir,
        )

    def cancel(self, slurm_job_id: str) -> bool:
        """Cancel a running job."""
        result = self.ssh.run(f"scancel {slurm_job_id}", warn=True)
        return result.ok
