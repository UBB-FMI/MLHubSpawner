def spawner_load_state(spawner_self, state):
    if "pid" in state:
        spawner_self.state_pid = state["pid"]
    if "machine_instance_id" in state:
        spawner_self.state_machine_instance_id = state["machine_instance_id"]
    if "notebook_port" in state:
        spawner_self.state_notebook_port = state["notebook_port"]
    if "shared_access_enabled" in state:
        spawner_self.state_shared_access_enabled = state["shared_access_enabled"]

    machine_registry = getattr(type(spawner_self), "_machine_registry", None)
    if machine_registry is None or not spawner_self.state_machine_instance_id:
        spawner_clear_state(spawner_self)
        return

    if not spawner_self.state_pid or not spawner_self.state_notebook_port:
        spawner_clear_state(spawner_self)
        return

    machine_instance = machine_registry.get_instance(spawner_self.state_machine_instance_id)
    if machine_instance is None:
        spawner_clear_state(spawner_self)
        return

    spawner_self.state_machine_instance = machine_instance
    spawner_self.state_hostname = machine_instance.endpoint

    machine_manager = getattr(type(spawner_self), "_machine_manager", None)
    machine_manager_lock = getattr(type(spawner_self), "_machine_manager_lock", None)
    if machine_manager is not None and machine_manager_lock is not None and spawner_self.state_shared_access_enabled is not None:
        machine_manager_lock.acquire()
        try:
            machine_manager.restore_allocation(
                machine_instance,
                spawner_self.user_unique_identifier,
                spawner_self.state_shared_access_enabled,
            )
        finally:
            machine_manager_lock.release()


def spawner_get_state(spawner_self):
    state = {}
    if spawner_self.state_pid:
        state["pid"] = spawner_self.state_pid
    if spawner_self.state_machine_instance_id:
        state["machine_instance_id"] = spawner_self.state_machine_instance_id
    if spawner_self.state_notebook_port:
        state["notebook_port"] = spawner_self.state_notebook_port
    if spawner_self.state_shared_access_enabled is not None:
        state["shared_access_enabled"] = spawner_self.state_shared_access_enabled
    return state


def spawner_clear_state(spawner_self):
    spawner_self.state_pid = 0
    spawner_self.state_hostname = None
    spawner_self.state_notebook_port = None
    spawner_self.state_machine_instance_id = None
    spawner_self.state_machine_instance = None
    spawner_self.state_shared_access_enabled = None
