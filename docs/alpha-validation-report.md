# Alpha Validation Report

Snapshot date: 2026-03-17

## Environment

- Host: local Linux workstation
- Distribution: Debian GNU/Linux forky/sid
- Kernel: `6.19.6+deb14-amd64`
- Interface under validation: CLI
- Local LLM baseline: `qwen2.5:7b`
- Local Ollama endpoint validated on this host: `http://127.0.0.1:11435/api`

## Automated baseline

Validated successfully:

- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m compileall src`

Current automated suite size at this snapshot:

- 43 tests

## Provider validation

Validated successfully:

- `MC_PROVIDER=auto` resolves to `ollama` when `MC_OLLAMA_BASE_URL=http://127.0.0.1:11435/api`
- `mc doctor` reports the local endpoint as reachable and `qwen2.5:7b` as installed
- conversational planning works through the real local Ollama endpoint

Real chat smokes completed:

- `mostre o uso de memoria`
- `o host esta lento`

## Service operation validation

### User-scoped systemd

Validated successfully on this host:

- `service_status` against `ollama-local.service` with `scope=user`
- `reload_service` against a temporary `systemd --user` validation unit with `CanReload=yes`
- `restart_service` against the same temporary `systemd --user` validation unit

Observed behavior:

- reload preserved `MainPID`
- restart changed `MainPID`
- post-action state remained `active/running`

Operational conclusion:

- typed service operations are validated for real `systemd --user` targets
- the `scope=user` path is suitable for workstation-safe alpha validation without root

### System-scoped systemd

Validated successfully in this environment with a temporary root-scoped validation unit:

- `service_status` against `mc-system-validation.service`
- `reload_service` against the same unit
- `restart_service` against the same unit

Observed behavior:

- reload preserved `MainPID`
- restart changed `MainPID`
- post-action state remained `active/running`

Operational conclusion:

- typed service operations are validated for real system-scoped targets
- the system validation path requires an elevation mechanism on the target host

## Managed config validation

Validated successfully on a real managed file:

- target path: `/home/irving/.local/state/master-control/managed-configs/alpha-validation.ini`
- read via `read_config_file`
- updated via `write_config_file --confirm`
- backup created under `<MC_STATE_DIR>/config-backups/`
- restored via `restore_config_backup --confirm`

Observed behavior:

- write path created a managed backup
- validation succeeded with `ini_parse`
- restore returned the file to the original content

## Alpha assessment

What is validated strongly enough for the narrow local alpha:

- CLI bootstrap
- provider resolution
- local Ollama integration
- structured planning and execution
- persistent session/audit flow
- managed config workflow
- user-scoped service workflow

What still remains before calling the milestone fully hardened:

- release packaging and release note polish
