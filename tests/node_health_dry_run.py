#!/usr/bin/env python3

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mlhubspawner.node_health_monitor import (
    NodeFitnessScorer,
    build_remote_metrics_command,
    parse_remote_metrics_output,
)


TARGET_HOSTS = [f"172.30.240.{last_octet}" for last_octet in range(64, 70)]
SSH_OPTIONS = [
    "-F",
    "/dev/null",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
]


async def collect_node_metrics(hostname: str, scorer: NodeFitnessScorer):
    process = await asyncio.create_subprocess_exec(
        "ssh",
        *SSH_OPTIONS,
        f"root@{hostname}",
        build_remote_metrics_command(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    stderr_text = stderr.decode().strip()

    if process.returncode != 0:
        return {
            "hostname": hostname,
            "healthy": False,
            "error": stderr_text or f"ssh exited with status {process.returncode}",
        }

    metrics = parse_remote_metrics_output(stdout.decode())
    fitness_score = scorer.score(
        gpus=metrics.gpus,
        ram_total_bytes=metrics.ram_total_bytes,
        ram_available_bytes=metrics.ram_available_bytes,
        cpu_usage_pct=None,
    )

    return {
        "hostname": hostname,
        "healthy": True,
        "error": None,
        "cpu_usage_pct": None,
        "ram_total_bytes": metrics.ram_total_bytes,
        "ram_available_bytes": metrics.ram_available_bytes,
        "ram_used_bytes": metrics.ram_used_bytes,
        "fitness_score": fitness_score,
        "gpus": [
            {
                "index": gpu.index,
                "memory_used_bytes": gpu.memory_used_bytes,
                "memory_total_bytes": gpu.memory_total_bytes,
                "utilization_gpu_pct": gpu.utilization_gpu_pct,
                "memory_headroom_ratio": gpu.memory_headroom_ratio,
                "idle_ratio": gpu.idle_ratio,
            }
            for gpu in metrics.gpus
        ],
    }


async def main():
    scorer = NodeFitnessScorer()
    results = await asyncio.gather(
        *(collect_node_metrics(hostname, scorer) for hostname in TARGET_HOSTS)
    )

    for result in results:
        print(json.dumps(result, sort_keys=True))

    if any(not result["healthy"] for result in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
