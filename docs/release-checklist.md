# Release Checklist

## Alpha baseline

Run this checklist only after the closeout milestones in `docs/mvp-evolution-plan.md` are satisfied for correctness, context handling, and operator flow quality.

Before calling the narrow local CLI MVP ready for an alpha tag:

1. run the automated baseline
2. validate provider resolution on the target host
3. run a real-host smoke test for service actions
4. run a real-host smoke test for managed config editing
5. run a real-host smoke test for `reconcile-timer install|remove` in `scope=user`
6. confirm documentation matches the operator-visible commands
7. confirm `README.md`, `docs/status.md`, `docs/roadmap.md`, `docs/mvp-plan.md`, `docs/mvp-evolution-plan.md`, and `docs/mvp-closeout-backlog.md` are aligned
8. confirm GitHub Actions CI is green on `main`
9. capture release notes in `CHANGELOG.md`

## Automated baseline

```bash
python3 -m ruff check .
python3 -m mypy src
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall src
PYTHONPATH=src python3 -m master_control --json doctor
```

## Clean-environment install

- prefer `python3 -m venv` when the host provides stdlib `venv`
- if the host lacks `ensurepip/python3-venv`, use `python3 -m virtualenv` as the fallback
- validate `pip install -e .` in that isolated environment
- run `mc doctor` with isolated `MC_STATE_DIR` and `MC_DB_PATH`

## Real-host smoke tests

Preferred execution path for each additional host profile:

```bash
python3 scripts/validate_host_profile.py --output-dir ./artifacts/host-validation
```

Use the generated JSON report as the release evidence artifact for that host.

### Provider resolution

- if using `MC_PROVIDER=auto`, run `mc doctor` and confirm the selected backend matches the host setup
- if using Ollama locally, confirm `ollama serve` is available and `ollama pull <model>` has already been run
- confirm `mc doctor` reports the configured Ollama model as installed before running chat smokes
- if Ollama is listening on a non-default port, set `MC_OLLAMA_BASE_URL` before running `mc doctor`
- if using OpenAI, confirm `OPENAI_API_KEY` is present and `mc doctor` reports the provider as available

### Service actions

- inspect a known service with `mc chat --once "status do servico <name>"`
- trigger a pending restart request through chat
- confirm a restart or reload only on a safe non-critical target
- verify the post-action state returned by the tool
- for workstation-safe validation without root, prefer `scope=user` against a non-critical `systemd --user` unit

### Managed config editing

- create a test file under `<MC_STATE_DIR>/managed-configs/`
- read it with `read_config_file`
- write a valid replacement with `write_config_file --confirm`
- confirm backup creation under `<MC_STATE_DIR>/config-backups/`
- restore the prior version with `restore_config_backup --confirm`

### Reconcile timer automation

- render the units first with `mc reconcile-timer render`
- install the user-scoped timer with `mc reconcile-timer install --scope user`
- confirm it appears in `systemctl --user list-timers master-control-reconcile.timer --all`
- remove it again with `mc reconcile-timer remove --scope user`
- confirm the timer no longer appears in the user timer list

### Operator-utility diagnostics

- run `mc tool process_to_unit --arg name=<process-name>`
- run `mc tool failed_services --arg scope=<system|user> --arg limit=<n>`
- confirm both tools return structured output without requiring confirmation

## Release notes minimum

The alpha notes should mention:

- supported interfaces
- supported providers
- auto provider resolution order
- support for `systemd --user` service operations through `scope=user`
- managed config targets
- service actions currently available
- what is still intentionally out of scope
