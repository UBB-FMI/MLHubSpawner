# Agent Notes

## Deployment

- Run `make` from the repository root.
- The `Makefile` syncs the local repository to `jupyterhub@172.30.0.52:/home/jupyterhub/MLHubSpanwer`.
- Keep the remote path spelling exactly as-is: `MLHubSpanwer`.
- The sync is intended to make `/home/jupyterhub/MLHubSpanwer` an exact mirror of the local repository contents.
- Remote execution must happen inside the TLJH hub virtual environment:

```bash
source /opt/tljh/hub/bin/activate
```

- The `Makefile` already handles that by running the remote install through `bash -lc` after activating the venv.
- `ssh -F /dev/null` is used on purpose to avoid local SSH config issues on this machine.
- After the remote install finishes, the `Makefile` restarts `jupyterhub.service` by SSHing as `root` to the same host.

## Remote Apply Step

- After syncing, run the current repo install steps on the remote machine from `/home/jupyterhub/MLHubSpanwer`.
- At the moment that means:

```bash
make install
make restart
```

- Inside the venv, that resolves to:

```bash
pip uninstall mlspawner -y
python3 setup.py install
```

- The restart step is:

```bash
ssh -F /dev/null root@172.30.0.52 'systemctl restart jupyterhub'
ssh -F /dev/null root@172.30.0.52 'systemctl is-active jupyterhub'
```

## Manual Verification

- Visible dev instance:

```text
https://www.cs.ubbcluj.ro/apps/mlhubdev/hub/home
```

- Test credentials are stored in `SECERTS.md`.
- `SECERTS.md` is intentionally ignored by git and must remain local-only.
