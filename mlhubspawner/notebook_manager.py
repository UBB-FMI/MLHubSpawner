import asyncio
import asyncssh
import random

NOTEBOOK_ALIVE_CHECK_MAX_ATTEMPTS = 5
NOTEBOOK_ALIVE_CHECK_RETRY_DELAY_SECONDS = 5

class NotebookManager():
    def __init__(self, logger, launch_command: str, safe_username: str):
        self.notebook_launch_command = launch_command
        self.log = logger
        # These will be set upon a successful launch.
        self.pid = None
        self.port = None
        self.remote_ip = None
        self.host_port = None
        # The safe username is static, unique to this instance of the manager, and never changes. It's therefore safe to set it here, and just re-use it everywhere.
        self.safe_username = safe_username

    async def probe_connection(self, host_ip: str, host_port: int):
        self.log.info(
            "Probing SSH on %s:%s with user %s before key-based launch.",
            host_ip,
            host_port,
            self.safe_username,
        )
        try:
            async with asyncssh.connect(
                host_ip,
                port=host_port,
                username=self.safe_username,
                password="bogus-password",
                known_hosts=None,
                connect_timeout=10
            ):
                pass
        except Exception as error:
            self.log.info("SSH probe finished with expected failure for %s: %s", self.safe_username, error)

    async def launch_notebook(self, jupyter_env: dict, hub_api_url: str, host_ip: str, host_port: str):

        notebook_jupyter_env = jupyter_env
        notebook_jupyter_env['JUPYTERHUB_API_URL'] = hub_api_url

        ssh_key_path = "~/.ssh/id_rsa"  # client key
        max_attempts = 3

        # Save connection info for later use.
        self.remote_ip = host_ip
        self.host_port = int(host_port)
        await self.probe_connection(host_ip, self.host_port)

        for attempt in range(max_attempts):
            random_port = random.randint(2000, 65535)
            self.log.info(f"Attempt {attempt+1}: Launching notebook on random port {random_port}.")

            # Build the bash script.
            bash_script_lines = ["#!/bin/bash"]
            for key, value in notebook_jupyter_env.items():
                bash_script_lines.append(f"export {key}='{value}'")
            bash_script_lines += [
                "unset XDG_RUNTIME_DIR",
                "touch .jupyter.log",
                "chmod 600 .jupyter.log",
                "run=true source initialSetup.sh >> .jupyter.log",
                f"{self.notebook_launch_command} --port {random_port} < /dev/null >> .jupyter.log 2>&1 & pid=$!",
                "echo $pid"
            ]
            bash_script_content = "\n".join(bash_script_lines)

            try:
                async with asyncssh.connect(
                    host_ip,
                    port=self.host_port,
                    username=self.safe_username,
                    client_keys=[ssh_key_path],
                    known_hosts=None,
                    connect_timeout=10
                ) as conn:
                    # Execute the constructed bash script.
                    result = await conn.run("bash -s", input=bash_script_content)

                stdout = result.stdout.strip() if result.stdout else ""
                stderr = result.stderr.strip() if result.stderr else ""
                return_code = result.exit_status

                if return_code == 0 and stdout:
                    try:
                        pid = int(stdout)
                        # Save the process ID and port for later operations.
                        self.pid = pid
                        self.port = random_port
                        self.log.info(f"Notebook launched successfully on port {random_port} with PID {pid}.")
                        return (random_port, pid)
                    except ValueError:
                        self.log.info(f"Attempt {attempt+1}: Unexpected output format '{stdout}'. Retrying with a new port...")
                else:
                    self.log.info(f"Attempt {attempt+1}: Error launching notebook on port {random_port}: "
                                  f"{stderr if stderr else 'No output'}. Retrying...")
            except Exception as e:
                self.log.info(f"Attempt {attempt+1}: Exception occurred: {e}. Retrying...")

        # If all attempts fail, return (None, None)
        self.log.info("All attempts to launch the notebook failed.")
        return (None, None)

    async def check_notebook_alive(self):
        """
        Check if the notebook process is running on the remote host by sending signal 0.
        """
        if not self.pid:
            self.log.info("No PID available to check. Notebook is not running.")
            return False

        ssh_key_path = "~/.ssh/id_rsa"
        command = f"kill -s 0 {self.pid} < /dev/null"

        for attempt in range(1, NOTEBOOK_ALIVE_CHECK_MAX_ATTEMPTS + 1):
            try:
                async with asyncssh.connect(
                    self.remote_ip,
                    port=self.host_port,
                    username=self.safe_username,
                    client_keys=[ssh_key_path],
                    known_hosts=None,
                    connect_timeout=10
                ) as conn:
                    result = await conn.run(command)
                alive = (result.exit_status == 0)
                self.log.info(
                    f"Check notebook alive: PID {self.pid} is {'alive' if alive else 'dead'} "
                    f"(exit status {result.exit_status}) on attempt {attempt}."
                )
                return alive
            except Exception as e:
                self.log.info(
                    "Error checking notebook alive on attempt %s/%s: %s",
                    attempt,
                    NOTEBOOK_ALIVE_CHECK_MAX_ATTEMPTS,
                    e,
                )
                if attempt == NOTEBOOK_ALIVE_CHECK_MAX_ATTEMPTS:
                    return False
                await asyncio.sleep(NOTEBOOK_ALIVE_CHECK_RETRY_DELAY_SECONDS)

    async def kill_notebook(self):
        """
        Kill all processes belonging to the safe_username on the remote host using SIGKILL.
        """
        ssh_key_path = "~/.ssh/id_rsa"
        command = f"pkill -9 -u {self.safe_username} < /dev/null"

        try:
            async with asyncssh.connect(
                self.remote_ip,
                port=self.host_port,
                username=self.safe_username,
                client_keys=[ssh_key_path],
                known_hosts=None,
                connect_timeout=10
            ) as conn:
                # Don't raise on non-zero; inspect exit_status & exit_signal ourselves
                result = await conn.run(command, check=False)

            status   = result.exit_status
            sig_info = result.exit_signal

            # Success if:
            #  - killed ≥1 process (status == 0)
            #  - pkill killed the SSH child so we get no status (status is None)
            #  - old AsyncSSH pattern: status == -1 and exit_signal set
            if status == 0 or status is None or (status == -1 and sig_info):
                self.log.info(f"All processes for user '{self.safe_username}' were killed successfully.")
                self.pid = None
                return True

            # No matching processes
            if status == 1:
                self.log.info(f"No processes found for user '{self.safe_username}'. Nothing to kill.")
                return False

            # Anything else is unexpected (should no longer fire on your “None” case)
            self.log.info(
                f"Unexpected result killing processes for '{self.safe_username}': exit_status={status!r}, exit_signal={sig_info!r}"
            )
            return False

        except Exception as e:
            self.log.info(f"Exception while trying to kill processes for '{self.safe_username}': {e}")
            return False




    def restore_state(self, pid: int, hostname: str, notebook_port: int):
        """
        Restore the last‐saved notebook process info so that future
        alive/poll/kill calls will work after a hub restart.
        - pid: the remote process ID
        - hostname: "ip:ssh_port" string you saved in spawner.state_hostname
        - notebook_port: the port the notebook is listening on
        """
        # If any of the required values are missing or falsy, bail out with a single error.
        if not all([pid, hostname, notebook_port]):
            self.log.info("Unable to restore state: pid, hostname, and notebook_port must all be non-empty.")
            return False

        # Parse out host IP and SSH port
        try:
            ip, ssh_port_str = hostname.split(":", 1)
            ssh_port = int(ssh_port_str)
        except Exception:
            self.log.info(f"Unable to restore state: invalid hostname format {hostname!r}.")
            return False

        # Stash them for later
        self.pid        = pid
        self.port       = notebook_port
        self.remote_ip  = ip
        self.host_port  = ssh_port

        # One-line info log, however long it gets
        self.log.info(f"Successfully restored notebook state: PID={self.pid}, notebook_port={self.port}, remote_ip={self.remote_ip}, ssh_port={self.host_port}")
        return True
