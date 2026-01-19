# myjob

CLI tool for submitting and managing SLURM jobs on remote clusters.

## Installation

```bash
pip install -e .
```

## Quick Start

1. Initialize configuration:
```bash
myjob init
```

2. Edit `myjob.yaml` with your cluster settings

3. Submit a job:
```bash
myjob submit
```

4. Check status:
```bash
myjob status <job_id>
```

5. View logs:
```bash
myjob logs <job_id>
```

## Commands

- `myjob init` - Create configuration files interactively
- `myjob submit` - Submit a job to the cluster
- `myjob status <job_id>` - Check job status
- `myjob logs <job_id>` - View job logs
- `myjob list` - List recent jobs
- `myjob cancel <job_id>` - Cancel a running job

## Configuration

Create `myjob.yaml` in your project directory:

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
```

For sensitive data (API keys), use `secret.yaml`:

```yaml
env_vars:
  WANDB_API_KEY: your-api-key
```

## License

MIT
