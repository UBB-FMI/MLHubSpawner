
# JupyterHub imports
from traitlets import List, Instance, Unicode
from jupyterhub.spawner import Spawner

# Local imports
from .remote_hosts.remote_ml_host import RemoteMLHost
from .config_parsers import DictionaryInstanceParser
from .form_builder import JupyterFormBuilder
from .exceptions.jupyter_html_exception import JupyterHubHTMLException
from .state_manager import spawner_load_state, spawner_get_state, spawner_clear_state
from .account_manager import get_privilege, get_safe_username
from .machine_manager import MachineManager
from .machine_registry import MachineInstance, MachineRegistry
from .node_health_monitor import NodeHealthMonitor
from .notebook_manager import NotebookManager
from .minio_manager import MinIOManager

# Python imports
import time
from threading import Lock


class MLHubSpawner(Spawner):

    # Remote hosts read from the configuration file. This is initialized per-instance!!
    remote_hosts = List(DictionaryInstanceParser(RemoteMLHost), help="Possible remote hosts from which to choose remote_host.", config=True)

    # MinIO credentials and URLs
    minio_url = Unicode(help="The URL endpoint for the MinIO server.", config=True)
    minio_access_key = Unicode(help="Access key for MinIO authentication.", config=True)
    minio_secret_key = Unicode(help="Secret key for MinIO authentication.", config=True)

    # Class-level MachineManager for load balancing
    _machine_manager = None

    # Class-level Lock for machine allocation
    _machine_manager_lock = None

    # Class-level singleton instance for MinIOManager
    _minio_manager = None

    # Class-level singleton instance for node health monitoring
    _node_health_monitor = None

    # Class-level singleton instance for the shared machine registry
    _machine_registry = None

    # Used to detect config drift after the first registry build.
    _machine_registry_signature = None
    _machine_registry_warning_emitted = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        #=== SINGLETONS ===
        cls = type(self)
        current_config_signature = MachineRegistry.compute_config_signature(self.remote_hosts)
        if cls._machine_registry is None:
            cls._machine_registry = MachineRegistry.from_config(self.remote_hosts)
            cls._machine_registry_signature = current_config_signature
        elif cls._machine_registry_signature != current_config_signature and not cls._machine_registry_warning_emitted:
            self.log.warning(
                "[MLHubSpawner] remote_hosts config changed after the shared machine registry was initialized. Keeping the first loaded registry for this Hub process."
            )
            cls._machine_registry_warning_emitted = True

        if cls._machine_manager is None:
            cls._machine_manager = MachineManager(self.log, cls._machine_registry)

        if cls._machine_manager_lock is None:
            cls._machine_manager_lock = Lock()

        # Initialize MinIOManager singleton if not already created.
        if (cls._minio_manager is None) and (self.minio_url):
            cls._minio_manager = MinIOManager(self.minio_url, self.minio_access_key, self.minio_secret_key)

        if cls._node_health_monitor is None:
            cls._node_health_monitor = NodeHealthMonitor(self.log, cls._machine_registry)

        #=== NORMAL INIT ===
        self.user_unique_identifier = self.user.name
        self.user_safe_username = get_safe_username(self.user.name) # This is already set here already
        self.user_privilege_level = get_privilege(self.user.name)

        self.form_builder = JupyterFormBuilder()
        self.notebook_manager = NotebookManager(self.log,"jupyterhub-singleuser --config=~/.jupyter/jupyter_notebook_config.py --ip 0.0.0.0", self.user_safe_username)

        self.state_pid = 0
        self.state_hostname = None
        self.state_notebook_port = None
        self.state_machine_instance_id = None
        self.state_machine_instance = None
        self.state_shared_access_enabled = None
        self.state_allocation_started_at = None

        self.machine_offers = {}

        def build_options_form_for_request(spawner):
            return spawner._build_options_form()

        # Keep options_form callable so JupyterHub rebuilds the HTML on each spawn-page request.
        self.options_form = build_options_form_for_request
        self._ensure_node_health_monitor_started()

    def _ensure_node_health_monitor_started(self):
        cls = type(self)
        if cls._node_health_monitor is not None:
            cls._node_health_monitor.start()

    def get_node_health_snapshots(self):
        cls = type(self)
        if cls._node_health_monitor is None:
            return {}
        return cls._node_health_monitor.get_all_snapshots()

    def get_node_health_snapshot(self, machine_instance: MachineInstance):
        cls = type(self)
        if cls._node_health_monitor is None:
            return None
        return cls._node_health_monitor.get_snapshot(machine_instance)

    def get_node_health_snapshot_payloads(self):
        cls = type(self)
        if cls._node_health_monitor is None:
            return {}
        return cls._node_health_monitor.get_all_snapshot_payloads()

    def get_node_health_snapshot_history_payloads(self):
        cls = type(self)
        if cls._node_health_monitor is None:
            return {}
        return cls._node_health_monitor.get_all_snapshot_history_payloads()

    def get_node_health_snapshot_payload(self, machine_instance: MachineInstance):
        cls = type(self)
        if cls._node_health_monitor is None:
            return None
        return cls._node_health_monitor.get_snapshot_payload(machine_instance)

    #==== STARTING, STOPPPING, POLLING ====
    def __slowError(self, errorMessage : str):
        time.sleep(10) # Needed until https://github.com/jupyterhub/jupyterhub/pull/5020 is merged
        raise JupyterHubHTMLException(errorMessage) 

    def _release_reserved_machine_allocation(self, reason: str) -> bool:
        machine_manager = getattr(self.__class__, "_machine_manager", None)
        machine_manager_lock = getattr(self.__class__, "_machine_manager_lock", None)

        if machine_manager is None or machine_manager_lock is None:
            return False

        machine_manager_lock.acquire()
        try:
            allocation = machine_manager.allocations.get(self.user_unique_identifier)
            if allocation is None:
                return False

            self.log.info(
                "Releasing the machine of %s on %s. Reason: %s",
                self.user_unique_identifier,
                allocation.machine_instance.endpoint,
                reason,
            )
            machine_manager.release_machine(self.user_unique_identifier)
            return True
        finally:
            machine_manager_lock.release()

    async def start(self):
        selected_machine_index = self.user_options['machineSelect']
        shared_access_enabled = self.user_options['sharedAccess']
        selected_machine_instance_id = self.user_options.get('machineInstanceId')

        if self.user_unique_identifier not in self.machine_offers:
            self.__slowError("Something didn't go well. Please go to the main page and try again.")

        available_machine_types = self.machine_offers[self.user_unique_identifier]
        if selected_machine_index < 0 or selected_machine_index >= len(available_machine_types):
            self.__slowError("The selected machine type is no longer available. Please choose again.")

        chosen_machine_type = available_machine_types[selected_machine_index]
        is_privileged = (self.user_privilege_level >= 1)

        if shared_access_enabled == False and is_privileged == False:
            self.__slowError("Your account privilege does not allow for exclusive access to GPU machines.")

        if not selected_machine_instance_id:
            self.__slowError("Please choose a node before starting your session.")

        selected_machine_instance = None
        allocation_error_message = None

        #=== RESERVE CHOSEN MACHINE ===
        self.__class__._machine_manager_lock.acquire()
        try:
            selected_machine_instance = self.__class__._machine_registry.resolve_instance(selected_machine_instance_id)

            if selected_machine_instance is None:
                allocation_error_message = "The selected node could not be found. Please choose a different node and try again."
            elif selected_machine_instance.machine_type is not chosen_machine_type:
                allocation_error_message = "The selected node does not belong to the chosen machine type. Please choose again."
            elif not self.__class__._machine_manager.take_machine(
                chosen_machine_type,
                selected_machine_instance,
                self.user_unique_identifier,
                shared_access_enabled,
            ):
                allocation_error_message = "The selected node is no longer available. Please choose a different node and try again."
            else:
                machine_allocation = self.__class__._machine_manager.allocations.get(self.user_unique_identifier)
                self.log.info(
                    f"Reserved requested machine for {self.user_unique_identifier}: {chosen_machine_type.codename} at {selected_machine_instance.endpoint}. Shared access: {shared_access_enabled}"
                )
                self.state_machine_instance = selected_machine_instance
                self.state_machine_instance_id = selected_machine_instance.instance_id
                self.state_hostname = selected_machine_instance.endpoint
                self.state_shared_access_enabled = shared_access_enabled
                self.state_allocation_started_at = machine_allocation.assigned_at if machine_allocation is not None else None
        finally:
            self.__class__._machine_manager_lock.release()

        if allocation_error_message:
            self.__slowError(allocation_error_message)

        try:
            #=== CREATE BUCKET ===
            if self.minio_url:
                try:
                    auth_state = await self.user.get_auth_state()
                    
                    if not auth_state or 'user' not in auth_state:
                        self.__slowError("Authentication state is missing. Did you log in via OAuth?")

                    # try Azure OID first
                    azure_id = auth_state['user'].get('oid')
                    if not azure_id:
                        # fall back to a sanitized UID
                        raw_uid = getattr(self, "user_unique_identifier", "") or ""
                        azure_id = self.__class__._minio_manager.generate_fallback_oid(raw_uid)
                        self.log.info(f"No Azure OID found; using fallback ID: {azure_id}")

                    # now create the bucket using either the real OID or our fallback
                    if not self.__class__._minio_manager.create(azure_id):
                        self.__slowError(f"Bucket creation failed for user with ID: {azure_id}.")
                    else:
                        self.log.info(f"Bucket successfully created (or already exists) for user with ID: {azure_id}.")
                except Exception as error:
                    self.__slowError(f"Error during bucket creation: {error}")
            else:
                self.log.info("Minio URL not provided in config, skipping bucket creation")


            #=== LAUNCH NOTEBOOK ===
            host_ip = selected_machine_instance.hostname
            host_port = str(selected_machine_instance.ssh_port)

            (notebook_port, notebook_pid) = await self.notebook_manager.launch_notebook(self.get_env(), self.hub.api_url, host_ip, host_port)

            if notebook_port == None or notebook_pid == None:
                self.__slowError("We're sorry, we were unable to launch your notebook instance. Your reserved spot was therefore released.")

            self.log.info(
                f"Launched a notebook for {self.user_unique_identifier} on {selected_machine_instance.endpoint} with port {notebook_port} and PID {notebook_pid}"
            )

            self.state_notebook_port = notebook_port
            self.state_pid = notebook_pid

            return (host_ip, notebook_port)
        except Exception:
            self._release_reserved_machine_allocation("spawn failed before the server became ready")
            self.clear_state()
            raise


    async def poll(self):
        #=== NOT CONFIGURED ===
        if not self.state_pid or self.state_pid == 0:
            self._release_reserved_machine_allocation("spawner has no notebook PID")
            self.clear_state()
            return 0
        
        #=== NOTEBOOK DEAD ===
        notebook_alive = await self.notebook_manager.check_notebook_alive()
        if not notebook_alive:
            self._release_reserved_machine_allocation("notebook process is no longer alive during poll")
            self.clear_state()
            return 0

        #=== ALL GOOD ===
        return None

    async def stop(self, now = False):
        try:
            #=== KILL THE NOTEBOOK ===
            await self.notebook_manager.kill_notebook()
        finally:
            self._release_reserved_machine_allocation("server stop requested")
            self.clear_state()

    #==== STATE RESTORE ===

    # Load spawner state from a saved state dictionary.
    def load_state(self, state):
        super().load_state(state)
        spawner_load_state(self, state)
        # Load the state into the NotebookManager as well, now that we have it (if any)
        if self.state_machine_instance_id and self.state_hostname and self.state_notebook_port:
            self.notebook_manager.restore_state(self.state_pid, self.state_hostname, self.state_notebook_port)

    # Retrieve the current state of the spawner as a dictionary.
    def get_state(self):
        state = super().get_state()
        state.update(spawner_get_state(self))
        return state

    # Clear the spawner state, resetting remote IP, PID, codename, and hostname.
    def clear_state(self):
        super().clear_state()
        spawner_clear_state(self)

    #==== FORM DATA ====

    # Build a fresh HTML snippet for the spawn page request.
    def _build_options_form(self):
        available_remote_hosts = self.__class__._machine_manager.get_available_types(self.user_privilege_level)

        self.machine_offers[self.user_unique_identifier] = available_remote_hosts

        available_remote_hosts_dictionary = [
            iterated_host.to_display_dict(include_instances=True)
            for iterated_host in available_remote_hosts
        ]

        return self.form_builder.get_html_page(
            available_remote_hosts_dictionary,
            nodeHealthSnapshots=self.get_node_health_snapshot_payloads(),
            uiContext={
                "canRequestExclusive": self.user_privilege_level >= 1,
            },
            nodeHealthHistory=self.get_node_health_snapshot_history_payloads(),
        )

    # Parse the form data into the correct types. The values here are available in the "start" method as "self.user_options"
    def options_from_form(self, formdata):
        return self.form_builder.get_form_options(formdata)
