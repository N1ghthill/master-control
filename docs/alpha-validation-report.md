# Alpha Validation Report

Snapshot date: 2026-03-18

## Environment

- Host: local Linux workstation
- Distribution: Debian GNU/Linux forky/sid
- Kernel: `6.19.6+deb14-amd64`
- Interface under validation: CLI
- Local LLM baseline: `qwen2.5:7b`
- Local Ollama endpoint validated on this host: `http://127.0.0.1:11435/api`

## Automated baseline

Validated successfully:

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m compileall src`
- `PYTHONPATH=src python3 -m master_control --json doctor`

Current automated suite size at this snapshot:

- 92 tests

Additional trust-boundary regressions now covered in the automated suite:

- slow-host diagnosis does not infer a service action from the hottest process alone
- service follow-ups preserve `scope=user|system`
- service restart recommendations require explicit service evidence
- stale service signals degrade to refresh-oriented recommendations instead of risky actions
- service and log follow-ups can reuse structured session context without relying on summary text alone
- diagnostic summaries can complete from fresh observations even when the compact summary is absent
- slow-host diagnosis can use `process_to_unit` before `service_status` and still conclude within one turn
- hot-process recommendations do not repeat process-correlation actions once the correlation already exists

## Provider validation

Validated successfully:

- `MC_PROVIDER=auto` resolves to `ollama` when `MC_OLLAMA_BASE_URL=http://127.0.0.1:11435/api`
- `mc doctor` reports the local endpoint as reachable and `qwen2.5:7b` as installed
- conversational planning works through the real local Ollama endpoint

Real chat smokes completed:

- `mostre o uso de memoria`
- `o host esta lento`
- `o host esta lento` now completes through memory, processes, process correlation, and service status when correlation evidence exists

Current trust note for the heuristic path:

- `o host esta lento` can now use a dedicated typed correlation step before a service lookup
- service lookup still requires explicit service evidence, tracked service state, or typed process -> unit correlation

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

## Additional operator-utility validation

Validated successfully on this host:

- `PYTHONPATH=src python3 -m master_control --json tool process_to_unit --arg name=python3`
- `PYTHONPATH=src python3 -m master_control --json tool failed_services --arg scope=system --arg limit=5`

Observed behavior:

- `process_to_unit` returned a real user-scoped `systemd` unit correlation for `python3`
- `failed_services` returned a real failed system-scoped unit on this host

Operational conclusion:

- the new read-only diagnostics are useful on a real host, not only in tests
- they expand operator evidence without widening the mutation boundary

## Clean-environment install validation

Validated successfully:

- `python3 -m virtualenv <tmp>/venv`
- `<tmp>/venv/bin/pip install -e .`
- `MC_STATE_DIR=<tmp>/state MC_DB_PATH=<tmp>/state/mc.sqlite3 MC_PROVIDER=heuristic <tmp>/venv/bin/mc doctor`

Observed behavior:

- editable install succeeded in the isolated environment
- `mc doctor` bootstrapped a fresh state directory and reported the expected tool inventory

Note:

- on this host, stdlib `python3 -m venv` was unavailable because `ensurepip/python3-venv` is not installed
- `python3 -m virtualenv` was used as the clean-environment fallback for the validation baseline

## Alpha assessment

What is validated strongly enough for the narrow local alpha:

- CLI bootstrap
- provider resolution
- local Ollama integration
- structured planning and execution
- structured session context for the core high-risk planner and recommendation flows
- read-only operator diagnostics for process correlation and failed-service listing
- persistent session/audit flow
- managed config workflow
- user-scoped service workflow
- service recommendation trust hardening for the current service/operator boundary
- recommendation evidence and approval guidance for the main operator journeys
- clean-environment install and bootstrap on the validated host profile

What remains outside this narrow local alpha baseline:

- broader production hardening
- daemon/API work and external interfaces
- utility expansion beyond the narrow MVP scope
