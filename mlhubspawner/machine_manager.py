import socket
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .machine_registry import MachineInstance, MachineRegistry, MachineType


@dataclass
class MachineAllocation:
    machine_type: MachineType
    machine_instance: MachineInstance
    shared_access_enabled: bool
    assigned_at: float


class MachineManager:
    def __init__(self, upstream_logger, machine_registry: MachineRegistry, time_fn=time.time):
        self.upstream_logger = upstream_logger
        self.machine_registry = machine_registry
        self.allocations: Dict[str, MachineAllocation] = {}
        self.time_fn = time_fn

    def is_machine_online(self, machine_instance: MachineInstance) -> bool:
        try:
            with socket.create_connection((machine_instance.hostname, machine_instance.ssh_port), timeout=2):
                return True
        except Exception:
            return False

    def take_machine(self, chosen_machine_type: MachineType, machine_instance: MachineInstance, unique_identifier: str, requested_shared_mode: bool) -> bool:
        self.upstream_logger.info(
            "[MachineManager] Attempting to take machine type %s on instance %s with UID %s (shared: %s)",
            chosen_machine_type.codename,
            machine_instance.endpoint,
            unique_identifier,
            requested_shared_mode,
        )

        if unique_identifier in self.allocations:
            self.upstream_logger.info(
                "[MachineManager] UID %s already has an allocation.",
                unique_identifier,
            )
            return False

        if machine_instance.machine_type != chosen_machine_type:
            self.upstream_logger.info(
                "[MachineManager] Machine instance %s does not belong to machine type %s.",
                machine_instance.endpoint,
                chosen_machine_type.codename,
            )
            return False

        if not self.is_machine_online(machine_instance):
            self.upstream_logger.info(
                "[MachineManager] Machine instance %s is offline. Cannot allocate.",
                machine_instance.endpoint,
            )
            return False

        if requested_shared_mode and not chosen_machine_type.shared_access_enabled:
            self.upstream_logger.info(
                "[MachineManager] Machine type with codename %s does not support shared access for machine %s",
                chosen_machine_type.codename,
                machine_instance.endpoint,
            )
            return False

        if not requested_shared_mode and machine_instance.has_allocations:
            self.upstream_logger.info(
                "[MachineManager] Machine instance %s (codename: %s) already has allocations. Cannot take machine exclusively.",
                machine_instance.endpoint,
                chosen_machine_type.codename,
            )
            return False

        if requested_shared_mode and machine_instance.has_exclusive_allocation:
            self.upstream_logger.info(
                "[MachineManager] Machine instance %s (codename: %s) already has an exclusive allocation. Cannot share.",
                machine_instance.endpoint,
                chosen_machine_type.codename,
            )
            return False

        assigned_at = float(self.time_fn())
        machine_instance.assign_user(unique_identifier, requested_shared_mode, assigned_at=assigned_at)
        self.allocations[unique_identifier] = MachineAllocation(
            machine_type=chosen_machine_type,
            machine_instance=machine_instance,
            shared_access_enabled=requested_shared_mode,
            assigned_at=assigned_at,
        )

        self.upstream_logger.info(
            "[MachineManager] Successfully allocated machine instance %s (codename: %s) to UID %s. Current allocations: %s",
            machine_instance.endpoint,
            chosen_machine_type.codename,
            unique_identifier,
            sorted(machine_instance.assigned_users.keys()),
        )
        return True

    def restore_allocation(
        self,
        machine_instance: MachineInstance,
        unique_identifier: str,
        shared_access_enabled: bool,
        assigned_at: Optional[float] = None,
    ) -> bool:
        existing_allocation = self.allocations.get(unique_identifier)
        if existing_allocation is not None:
            return existing_allocation.machine_instance is machine_instance

        if assigned_at is None:
            assigned_at = float(self.time_fn())

        machine_instance.assign_user(unique_identifier, shared_access_enabled, assigned_at=assigned_at)
        self.allocations[unique_identifier] = MachineAllocation(
            machine_type=machine_instance.machine_type,
            machine_instance=machine_instance,
            shared_access_enabled=shared_access_enabled,
            assigned_at=float(assigned_at),
        )
        self.upstream_logger.info(
            "[MachineManager] Restored allocation for UID %s on machine instance %s.",
            unique_identifier,
            machine_instance.endpoint,
        )
        return True

    def release_machine(self, unique_identifier: str):
        allocation = self.allocations.pop(unique_identifier, None)
        if allocation is None:
            self.upstream_logger.info(
                "[MachineManager] Attempted to release non-existing allocation with UID %s",
                unique_identifier,
            )
            return

        machine_instance = allocation.machine_instance
        self.upstream_logger.info(
            "[MachineManager] Releasing machine instance %s (codename: %s) allocated to UID %s",
            machine_instance.endpoint,
            allocation.machine_type.codename,
            unique_identifier,
        )
        machine_instance.release_user(unique_identifier)
        self.upstream_logger.info(
            "[MachineManager] Remaining allocations on %s: %s",
            machine_instance.endpoint,
            sorted(machine_instance.assigned_users.keys()),
        )

    def get_available_types(self, user_privilege_level: int) -> List[MachineType]:
        available = []
        for machine_type in self.machine_registry.machine_types:
            if machine_type.privileged_access_required and user_privilege_level < 1:
                continue
            if user_privilege_level < 1 and not machine_type.shared_access_enabled:
                continue
            available.append(machine_type)
        return available
