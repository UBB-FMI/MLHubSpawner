from __future__ import annotations

import asyncio
import copy
import logging
import os
import shlex
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Deque, Dict, List, Optional, Sequence, Tuple

from .machine_registry import MachineInstance, MachineRegistry, normalize_endpoint


DEFAULT_MONITOR_USERNAME = "monitorbot"
DEFAULT_MONITOR_KEY_PATH = "~/.ssh/id_rsa"
DEFAULT_POLL_INTERVAL_SECONDS = 30
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_STALE_AFTER_SECONDS = 90
DEFAULT_HISTORY_LIMIT = 600


@dataclass
class GPUMetrics:
    index: int
    memory_used_bytes: int
    memory_total_bytes: int
    utilization_gpu_pct: float
    memory_headroom_ratio: Optional[float]
    idle_ratio: Optional[float]


@dataclass
class CollectedNodeMetrics:
    gpus: List[GPUMetrics]
    ram_total_bytes: int
    ram_available_bytes: int
    ram_used_bytes: int
    cpu_sample: Tuple[int, ...]


@dataclass
class NodeSnapshot:
    machine_instance_id: str
    endpoint: str
    hostname: str
    ssh_port: int
    assigned_user_count: int = 0
    last_success_at: Optional[float] = None
    last_attempt_at: Optional[float] = None
    last_error: Optional[str] = None
    healthy: bool = False
    stale: bool = True
    cpu_usage_pct: Optional[float] = None
    ram_total_bytes: Optional[int] = None
    ram_available_bytes: Optional[int] = None
    ram_used_bytes: Optional[int] = None
    gpus: List[GPUMetrics] = field(default_factory=list)
    fitness_score: Optional[float] = None
    previous_cpu_sample: Optional[Tuple[int, ...]] = None

    @classmethod
    def from_machine_instance(cls, machine_instance: MachineInstance) -> "NodeSnapshot":
        return cls(
            machine_instance_id=machine_instance.instance_id,
            endpoint=machine_instance.endpoint,
            hostname=machine_instance.hostname,
            ssh_port=machine_instance.ssh_port,
            assigned_user_count=machine_instance.allocation_count,
        )


class NodeFitnessScorer:
    GPU_MEMORY_HEADROOM_WEIGHT = 0.40
    RAM_HEADROOM_WEIGHT = 0.25
    GPU_IDLE_WEIGHT = 0.25
    CPU_IDLE_WEIGHT = 0.10
    ASSIGNED_USER_PENALTY_PER_USER = 0.02

    def score(
        self,
        *,
        gpus: Sequence[GPUMetrics],
        ram_total_bytes: Optional[int],
        ram_available_bytes: Optional[int],
        cpu_usage_pct: Optional[float],
        assigned_user_count: int = 0,
    ) -> Optional[float]:
        components: List[Tuple[float, float]] = []

        gpu_memory_headroom_values = [
            gpu.memory_headroom_ratio for gpu in gpus if gpu.memory_headroom_ratio is not None
        ]
        if gpu_memory_headroom_values:
            components.append(
                (
                    self.GPU_MEMORY_HEADROOM_WEIGHT,
                    sum(gpu_memory_headroom_values) / len(gpu_memory_headroom_values),
                )
            )

        if ram_total_bytes and ram_total_bytes > 0 and ram_available_bytes is not None:
            ram_headroom_ratio = _clamp_ratio(ram_available_bytes / ram_total_bytes)
            components.append((self.RAM_HEADROOM_WEIGHT, ram_headroom_ratio))

        gpu_idle_values = [gpu.idle_ratio for gpu in gpus if gpu.idle_ratio is not None]
        if gpu_idle_values:
            components.append(
                (
                    self.GPU_IDLE_WEIGHT,
                    sum(gpu_idle_values) / len(gpu_idle_values),
                )
            )

        if cpu_usage_pct is not None:
            cpu_idle_ratio = _clamp_ratio(1.0 - (cpu_usage_pct / 100.0))
            components.append((self.CPU_IDLE_WEIGHT, cpu_idle_ratio))

        if not components:
            return None

        weight_sum = sum(weight for weight, _ in components)
        weighted_score = sum(weight * value for weight, value in components) / weight_sum
        assigned_user_penalty = min(1.0, max(0.0, float(assigned_user_count)) * self.ASSIGNED_USER_PENALTY_PER_USER)
        adjusted_score = weighted_score * (1.0 - assigned_user_penalty)
        return round(adjusted_score * 100.0, 2)


class NodeHealthMonitor:
    def __init__(
        self,
        logger: Optional[logging.Logger],
        machine_registry: MachineRegistry,
        *,
        ssh_username: str = DEFAULT_MONITOR_USERNAME,
        ssh_key_path: str = DEFAULT_MONITOR_KEY_PATH,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
        connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        scorer: Optional[NodeFitnessScorer] = None,
        time_fn=time.time,
    ):
        self.log = logger or logging.getLogger(__name__)
        self.machine_registry = machine_registry
        self.ssh_username = ssh_username
        self.ssh_key_path = ssh_key_path
        self.poll_interval_seconds = poll_interval_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self.stale_after_seconds = stale_after_seconds
        self.history_limit = max(1, int(history_limit))
        self.scorer = scorer or NodeFitnessScorer()
        self.time_fn = time_fn

        self._task: Optional[asyncio.Task] = None
        self._cache: Dict[MachineInstance, NodeSnapshot] = {}
        self._history: Dict[MachineInstance, Deque[NodeSnapshot]] = {}

    def start(self) -> bool:
        if self._task is not None and not self._task.done():
            return False

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.log.debug("[NodeHealthMonitor] No running event loop yet; startup deferred.")
            return False

        self._task = loop.create_task(self._run_loop(), name="mlhub-node-health-monitor")
        self.log.info("[NodeHealthMonitor] Started shared node health monitor task.")
        return True

    async def stop(self):
        if self._task is None:
            return

        task = self._task
        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def refresh_all(self):
        machine_instances = tuple(self.machine_registry.machine_instances)
        active_instances = set(machine_instances)

        for machine_instance in machine_instances:
            self._cache.setdefault(machine_instance, NodeSnapshot.from_machine_instance(machine_instance))

        for cached_machine_instance in list(self._cache.keys()):
            if cached_machine_instance not in active_instances:
                del self._cache[cached_machine_instance]
                self._history.pop(cached_machine_instance, None)

        if not machine_instances:
            return

        await asyncio.gather(*(self._refresh_machine_instance(machine_instance) for machine_instance in machine_instances))

    def get_all_snapshots(self) -> Dict[MachineInstance, NodeSnapshot]:
        return {
            machine_instance: copy.deepcopy(snapshot)
            for machine_instance, snapshot in self._cache.items()
        }

    def get_snapshot(self, machine_instance: MachineInstance) -> Optional[NodeSnapshot]:
        if machine_instance is None:
            return None

        snapshot = self._cache.get(machine_instance)
        if snapshot is None:
            return None
        return copy.deepcopy(snapshot)

    def get_snapshot_history(self, machine_instance: MachineInstance) -> Tuple[NodeSnapshot, ...]:
        if machine_instance is None:
            return ()

        history = self._history.get(machine_instance)
        if history is None:
            return ()
        return tuple(copy.deepcopy(list(history)))

    def get_all_snapshot_payloads(self) -> Dict[str, Dict[str, object]]:
        return {
            machine_instance.instance_id: asdict(copy.deepcopy(snapshot))
            for machine_instance, snapshot in self._cache.items()
        }

    def get_all_snapshot_history_payloads(self) -> Dict[str, List[Dict[str, object]]]:
        return {
            machine_instance.instance_id: [
                _snapshot_history_payload(snapshot)
                for snapshot in copy.deepcopy(list(history))
            ]
            for machine_instance, history in self._history.items()
        }

    def get_snapshot_payload(self, machine_instance: MachineInstance) -> Optional[Dict[str, object]]:
        snapshot = self.get_snapshot(machine_instance)
        if snapshot is None:
            return None
        return asdict(snapshot)

    def _remember_snapshot(self, machine_instance: MachineInstance, snapshot: NodeSnapshot):
        history = self._history.setdefault(
            machine_instance,
            deque(maxlen=self.history_limit),
        )
        history.append(copy.deepcopy(snapshot))

    async def _run_loop(self):
        try:
            while True:
                try:
                    await self.refresh_all()
                except Exception:
                    self.log.exception("[NodeHealthMonitor] Monitoring cycle failed.")
                await asyncio.sleep(self.poll_interval_seconds)
        except asyncio.CancelledError:
            self.log.info("[NodeHealthMonitor] Shared node health monitor task stopped.")
            raise

    async def _refresh_machine_instance(self, machine_instance: MachineInstance):
        now = self.time_fn()
        previous_snapshot = self._cache.get(machine_instance, NodeSnapshot.from_machine_instance(machine_instance))

        try:
            collected_metrics = await self._collect_machine_metrics(machine_instance)
            cpu_usage_pct = compute_cpu_usage_pct(previous_snapshot.previous_cpu_sample, collected_metrics.cpu_sample)
            fitness_score = self.scorer.score(
                gpus=collected_metrics.gpus,
                ram_total_bytes=collected_metrics.ram_total_bytes,
                ram_available_bytes=collected_metrics.ram_available_bytes,
                cpu_usage_pct=cpu_usage_pct,
                assigned_user_count=machine_instance.allocation_count,
            )

            self._cache[machine_instance] = NodeSnapshot(
                machine_instance_id=machine_instance.instance_id,
                endpoint=machine_instance.endpoint,
                hostname=machine_instance.hostname,
                ssh_port=machine_instance.ssh_port,
                assigned_user_count=machine_instance.allocation_count,
                last_success_at=now,
                last_attempt_at=now,
                last_error=None,
                healthy=True,
                stale=False,
                cpu_usage_pct=cpu_usage_pct,
                ram_total_bytes=collected_metrics.ram_total_bytes,
                ram_available_bytes=collected_metrics.ram_available_bytes,
                ram_used_bytes=collected_metrics.ram_used_bytes,
                gpus=collected_metrics.gpus,
                fitness_score=fitness_score,
                previous_cpu_sample=collected_metrics.cpu_sample,
            )
            self._remember_snapshot(machine_instance, self._cache[machine_instance])
            self.log.debug(
                "[NodeHealthMonitor] Refreshed metrics for %s with fitness %s.",
                machine_instance.instance_id,
                fitness_score,
            )
        except Exception as error:
            stale = is_snapshot_stale(previous_snapshot.last_success_at, now, self.stale_after_seconds)
            failure_snapshot = copy.deepcopy(previous_snapshot)
            failure_snapshot.last_attempt_at = now
            failure_snapshot.last_error = str(error)
            failure_snapshot.healthy = False
            failure_snapshot.stale = stale
            failure_snapshot.assigned_user_count = machine_instance.allocation_count
            self._cache[machine_instance] = failure_snapshot
            self._remember_snapshot(machine_instance, failure_snapshot)
            self.log.info(
                "[NodeHealthMonitor] Failed to refresh %s: %s",
                machine_instance.instance_id,
                error,
            )

    async def _collect_machine_metrics(self, machine_instance: MachineInstance) -> CollectedNodeMetrics:
        asyncssh = _load_asyncssh()
        ssh_key_path = os.path.expanduser(self.ssh_key_path)
        async with asyncssh.connect(
            machine_instance.hostname,
            port=machine_instance.ssh_port,
            username=self.ssh_username,
            client_keys=[ssh_key_path],
            known_hosts=None,
            connect_timeout=self.connect_timeout_seconds,
        ) as conn:
            result = await conn.run(build_remote_metrics_command(), check=True)

        return parse_remote_metrics_output(result.stdout)


def parse_hostname_port(hostname_or_hostport: str) -> Tuple[str, int]:
    return normalize_endpoint(hostname_or_hostport)


def build_remote_metrics_command() -> str:
    script = """\
set -euo pipefail
echo __GPU__
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits
echo __MEM__
grep -E '^(MemTotal|MemAvailable):' /proc/meminfo
echo __CPU__
grep '^cpu ' /proc/stat
"""
    return "bash -lc " + shlex.quote(script)


def parse_remote_metrics_output(output: str) -> CollectedNodeMetrics:
    gpu_lines, mem_lines, cpu_lines = split_metrics_output(output)
    gpus = parse_gpu_metrics(gpu_lines)
    ram_total_bytes, ram_available_bytes, ram_used_bytes = parse_meminfo(mem_lines)
    cpu_sample = parse_cpu_stat(cpu_lines)

    return CollectedNodeMetrics(
        gpus=gpus,
        ram_total_bytes=ram_total_bytes,
        ram_available_bytes=ram_available_bytes,
        ram_used_bytes=ram_used_bytes,
        cpu_sample=cpu_sample,
    )


def split_metrics_output(output: str) -> Tuple[List[str], List[str], List[str]]:
    sections = {"gpu": [], "mem": [], "cpu": []}
    current_section = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "__GPU__":
            current_section = "gpu"
            continue
        if line == "__MEM__":
            current_section = "mem"
            continue
        if line == "__CPU__":
            current_section = "cpu"
            continue
        if current_section is None:
            continue
        sections[current_section].append(line)

    if not sections["gpu"]:
        raise ValueError("No GPU metrics found in remote command output.")
    if not sections["mem"]:
        raise ValueError("No memory metrics found in remote command output.")
    if not sections["cpu"]:
        raise ValueError("No CPU metrics found in remote command output.")

    return sections["gpu"], sections["mem"], sections["cpu"]


def parse_gpu_metrics(gpu_lines: Sequence[str]) -> List[GPUMetrics]:
    gpus = []
    for line in gpu_lines:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 4:
            raise ValueError(f"Unexpected nvidia-smi output line: {line}")

        index = int(parts[0])
        memory_used_mib = int(parts[1])
        memory_total_mib = int(parts[2])
        utilization_gpu_pct = float(parts[3])

        memory_used_bytes = mib_to_bytes(memory_used_mib)
        memory_total_bytes = mib_to_bytes(memory_total_mib)
        memory_headroom_ratio = None
        if memory_total_bytes > 0:
            memory_headroom_ratio = _clamp_ratio(1.0 - (memory_used_bytes / memory_total_bytes))
        idle_ratio = _clamp_ratio(1.0 - (utilization_gpu_pct / 100.0))

        gpus.append(
            GPUMetrics(
                index=index,
                memory_used_bytes=memory_used_bytes,
                memory_total_bytes=memory_total_bytes,
                utilization_gpu_pct=utilization_gpu_pct,
                memory_headroom_ratio=memory_headroom_ratio,
                idle_ratio=idle_ratio,
            )
        )

    return gpus


def parse_meminfo(mem_lines: Sequence[str]) -> Tuple[int, int, int]:
    mem_values = {}
    for line in mem_lines:
        key, value = line.split(":", 1)
        numeric_part = value.strip().split()[0]
        mem_values[key] = int(numeric_part) * 1024

    if "MemTotal" not in mem_values or "MemAvailable" not in mem_values:
        raise ValueError("Missing MemTotal or MemAvailable in /proc/meminfo output.")

    ram_total_bytes = mem_values["MemTotal"]
    ram_available_bytes = mem_values["MemAvailable"]
    ram_used_bytes = max(ram_total_bytes - ram_available_bytes, 0)

    return ram_total_bytes, ram_available_bytes, ram_used_bytes


def parse_cpu_stat(cpu_lines: Sequence[str]) -> Tuple[int, ...]:
    for line in cpu_lines:
        if line.startswith("cpu "):
            fields = line.split()[1:]
            return tuple(int(field) for field in fields)
    raise ValueError("Missing aggregate cpu line in /proc/stat output.")


def compute_cpu_usage_pct(
    previous_cpu_sample: Optional[Tuple[int, ...]],
    current_cpu_sample: Tuple[int, ...],
) -> Optional[float]:
    if previous_cpu_sample is None:
        return None

    previous_values = _normalize_cpu_fields(previous_cpu_sample)
    current_values = _normalize_cpu_fields(current_cpu_sample)

    previous_idle = previous_values[3] + previous_values[4]
    current_idle = current_values[3] + current_values[4]

    previous_non_idle = (
        previous_values[0]
        + previous_values[1]
        + previous_values[2]
        + previous_values[5]
        + previous_values[6]
        + previous_values[7]
    )
    current_non_idle = (
        current_values[0]
        + current_values[1]
        + current_values[2]
        + current_values[5]
        + current_values[6]
        + current_values[7]
    )

    previous_total = previous_idle + previous_non_idle
    current_total = current_idle + current_non_idle

    total_delta = current_total - previous_total
    idle_delta = current_idle - previous_idle
    if total_delta <= 0:
        return None

    cpu_usage_ratio = (total_delta - idle_delta) / total_delta
    return round(_clamp_ratio(cpu_usage_ratio) * 100.0, 2)


def is_snapshot_stale(last_success_at: Optional[float], now: float, stale_after_seconds: int) -> bool:
    if last_success_at is None:
        return True
    return (now - last_success_at) >= stale_after_seconds


def mib_to_bytes(value_mib: int) -> int:
    return value_mib * 1024 * 1024


def _normalize_cpu_fields(cpu_sample: Tuple[int, ...]) -> Tuple[int, ...]:
    cpu_values = list(cpu_sample[:8])
    while len(cpu_values) < 8:
        cpu_values.append(0)
    return tuple(cpu_values)


def _clamp_ratio(value: float) -> float:
    return max(0.0, min(1.0, value))


def _snapshot_history_payload(snapshot: NodeSnapshot) -> Dict[str, object]:
    gpu_memory_used_bytes = None
    gpu_memory_total_bytes = None
    if snapshot.healthy and not snapshot.stale and snapshot.gpus:
        gpu_memory_used_bytes = sum(gpu.memory_used_bytes for gpu in snapshot.gpus)
        gpu_memory_total_bytes = sum(gpu.memory_total_bytes for gpu in snapshot.gpus)

    return {
        "recorded_at": int(round(snapshot.last_attempt_at)) if snapshot.last_attempt_at is not None else None,
        "fitness_score": snapshot.fitness_score if snapshot.healthy and not snapshot.stale else None,
        "cpu_usage_pct": snapshot.cpu_usage_pct if snapshot.healthy and not snapshot.stale else None,
        "gpu_memory_used_bytes": gpu_memory_used_bytes,
        "gpu_memory_total_bytes": gpu_memory_total_bytes,
        "assigned_user_count": snapshot.assigned_user_count,
        "healthy": snapshot.healthy,
        "stale": snapshot.stale,
    }


def _load_asyncssh():
    try:
        import asyncssh  # type: ignore
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "asyncssh is required for runtime node monitoring but is not installed in this Python environment."
        ) from error
    return asyncssh
