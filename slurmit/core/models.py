"""Pydantic models for slurmit configuration."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ConnectionConfig(BaseModel):
    """SSH connection configuration."""

    host: str = Field(..., description="Remote host address")
    user: str = Field(..., description="SSH username")
    port: int = Field(default=22, description="SSH port")
    key_file: str | None = Field(default=None, description="Path to SSH private key")


class SlurmConfig(BaseModel):
    """SLURM-specific configuration."""

    partition: str = Field(default="default", description="SLURM partition to use")
    account: str | None = Field(default=None, description="SLURM account")
    qos: str | None = Field(default=None, description="Quality of Service")
    extra_options: dict[str, str] = Field(
        default_factory=dict, description="Additional SLURM options"
    )


class ResourceConfig(BaseModel):
    """Resource allocation configuration."""

    nodes: int = Field(default=1, description="Number of nodes")
    ntasks: int = Field(default=1, description="Number of tasks")
    cpus_per_task: int = Field(default=1, description="CPUs per task")
    gpus: int = Field(default=0, description="Number of GPUs")
    gpu_type: str | None = Field(default=None, description="GPU type (e.g., a100, v100)")
    memory: str = Field(default="4G", description="Memory per node")
    time: str = Field(default="1:00:00", description="Time limit (HH:MM:SS)")


class GitConfig(BaseModel):
    """Git repository configuration."""

    repo_url: str | None = Field(default=None, description="Git repository URL")
    branch: str = Field(default="main", description="Git branch to use")
    commit: str | None = Field(default=None, description="Specific commit hash")
    auto_detect: bool = Field(default=True, description="Auto-detect from local repo")


class ExecutionConfig(BaseModel):
    """Job execution configuration."""

    command: str = Field(..., description="Command to execute")
    working_dir: str | None = Field(default=None, description="Working directory on remote")
    env_vars: dict[str, str] = Field(default_factory=dict, description="Environment variables")
    modules: list[str] = Field(default_factory=list, description="Modules to load")
    setup_commands: list[str] = Field(
        default_factory=list, description="Commands to run before main command"
    )


class OutputConfig(BaseModel):
    """Output and logging configuration."""

    stdout: str = Field(default="job_%j.out", description="Stdout file pattern")
    stderr: str = Field(default="job_%j.err", description="Stderr file pattern")
    log_dir: str = Field(default="logs", description="Log directory on remote")


class JobConfig(BaseModel):
    """Complete job configuration combining all sub-configs."""

    name: str = Field(default="slurmit", description="Job name")
    connection: ConnectionConfig
    slurm: SlurmConfig = Field(default_factory=SlurmConfig)
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    execution: ExecutionConfig
    output: OutputConfig = Field(default_factory=OutputConfig)
    workspace: str = Field(default="~/slurmit-workspace", description="Remote workspace directory")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobConfig":
        """Create JobConfig from a dictionary, handling nested configs."""
        return cls(**data)


class SecretConfig(BaseModel):
    """Secret configuration (stored separately from main config)."""

    connection: ConnectionConfig | None = Field(
        default=None, description="Connection details from secret.yaml"
    )
    env_vars: dict[str, str] = Field(
        default_factory=dict, description="Secret environment variables"
    )


class JobRecord(BaseModel):
    """Record of a submitted job."""

    name: str = Field(..., description="Job name (primary identifier)")
    slurm_job_id: str | None = Field(default=None, description="SLURM job ID")
    run_id: str | None = Field(default=None, description="Run ID (name_timestamp)")
    config_file: str | None = Field(default=None, description="Config file used")
    host: str = Field(..., description="Remote host")
    user: str = Field(..., description="SSH username")
    queue_dir: str = Field(..., description="Remote queue directory")
    run_dir: str | None = Field(default=None, description="Remote run directory (after execution)")
    log_dir: str | None = Field(default=None, description="Remote log directory")
    status: str = Field(default="QUEUED", description="Job status")
    submitted_at: str = Field(..., description="Submission timestamp")
    started_at: str | None = Field(default=None, description="Execution start timestamp")
    completed_at: str | None = Field(default=None, description="Completion timestamp")
    git_commit: str | None = Field(default=None, description="Git commit hash")
    git_branch: str | None = Field(default=None, description="Git branch")
    config_hash: str | None = Field(default=None, description="Config file hash")
    command: str = Field(..., description="Executed command")

    # Backward compatibility: alias for old local_id field
    @property
    def local_id(self) -> str:
        """Backward compatibility: return name as local_id."""
        return self.name
