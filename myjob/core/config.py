"""Configuration loading and merging for myjob."""

from pathlib import Path
from typing import Any

import yaml

from myjob.core.models import JobConfig, SecretConfig


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dict."""
    if not path.exists():
        return {}
    with open(path) as f:
        content = yaml.safe_load(f)
        return content if content else {}


def find_config_file(config_path: str | None = None) -> Path | None:
    """Find the configuration file.

    Search order:
    1. Explicit path if provided
    2. myjob.yaml in current directory
    3. myjob.yml in current directory
    """
    if config_path:
        path = Path(config_path)
        if path.exists():
            return path
        raise FileNotFoundError(f"Config file not found: {config_path}")

    for name in ["myjob.yaml", "myjob.yml"]:
        path = Path.cwd() / name
        if path.exists():
            return path

    return None


def find_secret_file() -> Path | None:
    """Find the secret configuration file.

    Search order:
    1. secret.yaml in current directory
    2. ~/.myjob/secret.yaml (global)
    """
    local_secret = Path.cwd() / "secret.yaml"
    if local_secret.exists():
        return local_secret

    global_secret = Path.home() / ".myjob" / "secret.yaml"
    if global_secret.exists():
        return global_secret

    return None


def load_secret_config() -> SecretConfig:
    """Load secret configuration from secret.yaml."""
    secret_path = find_secret_file()
    if secret_path:
        data = load_yaml_file(secret_path)
        return SecretConfig(**data)
    return SecretConfig()


def load_config(
    config_path: str | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> JobConfig:
    """Load and merge configuration from multiple sources.

    Priority (highest to lowest):
    1. CLI arguments
    2. myjob.yaml
    3. secret.yaml
    4. Defaults
    """
    # Start with empty config
    merged_config: dict[str, Any] = {}

    # Load secret.yaml (lowest priority for non-secret values)
    secret_path = find_secret_file()
    if secret_path:
        secret_data = load_yaml_file(secret_path)
        merged_config = deep_merge(merged_config, secret_data)

    # Load myjob.yaml
    config_file = find_config_file(config_path)
    if config_file:
        config_data = load_yaml_file(config_file)
        merged_config = deep_merge(merged_config, config_data)

    # Apply CLI overrides
    if cli_overrides:
        merged_config = deep_merge(merged_config, cli_overrides)

    # Validate and create JobConfig
    return JobConfig.from_dict(merged_config)


def get_defaults() -> dict[str, Any]:
    """Return default configuration values."""
    return {
        "name": "myjob",
        "slurm": {
            "partition": "default",
        },
        "resources": {
            "nodes": 1,
            "ntasks": 1,
            "cpus_per_task": 1,
            "gpus": 0,
            "memory": "4G",
            "time": "1:00:00",
        },
        "git": {
            "branch": "main",
            "auto_detect": True,
        },
        "output": {
            "stdout": "job_%j.out",
            "stderr": "job_%j.err",
            "log_dir": "logs",
        },
        "workspace": "~/myjob-workspace",
    }


def create_sample_config() -> str:
    """Generate a sample myjob.yaml configuration."""
    return """# myjob configuration file
name: my-experiment

# Connection settings (can also be in secret.yaml)
connection:
  host: cluster.example.com
  user: myuser
  # key_file: ~/.ssh/id_rsa  # Optional

# SLURM settings
slurm:
  partition: gpu
  account: my-account
  # qos: high
  # extra_options:
  #   constraint: "a100"

# Resource allocation
resources:
  nodes: 1
  ntasks: 1
  cpus_per_task: 4
  gpus: 1
  gpu_type: a100
  memory: 32G
  time: "4:00:00"

# Git configuration
git:
  # repo_url: https://github.com/user/repo.git
  branch: main
  auto_detect: true  # Detect from local git repo

# Execution settings
execution:
  command: python train.py
  # working_dir: /path/on/remote  # Optional
  modules:
    - cuda/11.8
    - python/3.10
  setup_commands:
    - pip install -r requirements.txt
  env_vars:
    WANDB_PROJECT: my-project

# Output settings
output:
  stdout: "%x_%j.out"
  stderr: "%x_%j.err"
  log_dir: logs

# Workspace directory on remote
workspace: ~/myjob-workspace
"""


def create_sample_secret() -> str:
    """Generate a sample secret.yaml configuration."""
    return """# Secret configuration file - DO NOT COMMIT TO GIT
# Add this file to .gitignore

connection:
  host: cluster.example.com
  user: myuser
  key_file: ~/.ssh/id_rsa

# Secret environment variables
env_vars:
  WANDB_API_KEY: your-api-key-here
  HF_TOKEN: your-huggingface-token
"""
