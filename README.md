# slurmit

CLI tool for submitting and managing SLURM jobs on remote clusters.

## Architecture

```
LOCAL (User's PC)              SERVER (SLURM Cluster)
─────────────────              ─────────────────────
slurmit submit ─── rsync ────→ ~/slurmit/queue/
                               slurmit run ──→ sbatch
```

**Key Design:**
- `slurmit submit` runs locally: transfers code via rsync
- `slurmit run` runs on server: submits job to SLURM
- No git push required - direct file transfer
- Experiment versioning with git state capture

## Installation

```bash
# Install on both local machine and server
pip install -e .
```

## Quick Start

```bash
# 1. Create configuration
slurmit init

# 2. Edit slurmit.yaml with your settings

# 3. Submit from local (transfers code to server)
slurmit submit -n my-experiment

# 4. SSH to server and run
ssh user@cluster
slurmit run my-experiment

# 5. Check status (from local or server)
slurmit status my-experiment
slurmit logs my-experiment -f
```

## Commands

### Local Commands

```bash
slurmit submit -n <name>        # Transfer code+config to server
slurmit submit -n <name> --dry-run
slurmit status <name>           # Check job status
slurmit logs <name> -f          # View logs (follow mode)
slurmit list                    # List submitted jobs
slurmit cancel <name>           # Cancel a running job
```

### Server Commands

```bash
slurmit run <name>              # Run a queued job
slurmit run <name> -w           # Run and wait for completion
slurmit run <name> -f           # Run and follow logs
slurmit list --queue            # List queued jobs
slurmit list --runs             # List run history
slurmit nodes                   # Show cluster node/GPU status
slurmit nodes -p gpu            # Filter by partition
slurmit reproduce <run_id>      # Reproduce a past experiment
```

## Server Directory Structure

```
~/slurmit/
├── queue/                        # Pending jobs (after submit)
│   └── my-exp/
│       ├── code/                 # Synced source code
│       ├── slurmit.yaml          # Experiment config
│       └── metadata.json         # Version info (auto-generated)
│
├── runs/                         # Execution history
│   ├── my-exp_20240119_143022/   # With timestamp
│   │   ├── code/
│   │   ├── slurmit.yaml
│   │   ├── metadata.json
│   │   └── logs/
│   └── my-exp_20240119_150512/
│
└── active/                       # Currently running (symlinks)
    └── my-exp -> ../runs/my-exp_20240119_150512/
```

## Configuration

### slurmit.yaml

```yaml
name: my-experiment

connection:
  host: cluster.example.com
  user: myuser

slurm:
  partition: gpu
  account: my-account

resources:
  gpus: 1
  memory: 32G
  time: "4:00:00"

execution:
  command: python train.py
  modules:
    - cuda/11.8
    - anaconda3
  setup_commands:
    - conda activate myenv
```

### secret.yaml

Sensitive data stored separately:

```yaml
env_vars:
  WANDB_API_KEY: your-api-key
  HF_TOKEN: your-token
```

## Version Control

Each experiment automatically captures:
- Git commit hash
- Branch name
- Uncommitted changes (saved as patch)
- Config file hash

```bash
# View metadata
cat ~/slurmit/runs/my-exp_20240119_143022/metadata.json

# Reproduce a past experiment
slurmit reproduce my-exp_20240119_143022
```

### metadata.json Example

```json
{
  "job_name": "my-exp",
  "submitted_at": "2024-01-19T14:30:22",
  "submitted_from": "user@local-machine",
  "git": {
    "repo": "https://github.com/user/project",
    "branch": "main",
    "commit": "a1b2c3d4e5f6",
    "dirty": true,
    "diff_file": "uncommitted.patch"
  },
  "config_hash": "sha256:e4f5g6h7..."
}
```

## Node/GPU Monitoring

```bash
# Show cluster status
slurmit nodes

# Example output:
CLUSTER STATUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NODE          STATE      PARTITION   CPU (used/total)   GPU (free/total)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
gpu-node-01   mixed      gpu         24/64              2/4 (a100)
gpu-node-02   allocated  gpu         64/64              0/4 (a100)
gpu-node-03   idle       gpu         0/64               4/4 (a100)

GPU Summary:
  Total GPUs: 12
  Free GPUs:  6
  A100: 6/12 available
```

## Workflow Example

```bash
# Local: develop and test code

# Local: submit experiment
slurmit submit -n train-v1 --exclude "data/*"

# Server: check queue and run
ssh cluster
slurmit list --queue
slurmit run train-v1 -w

# Local: monitor progress
slurmit status train-v1
slurmit logs train-v1 -f

# Later: reproduce the experiment
slurmit reproduce train-v1_20240119_143022
```

## License

MIT
