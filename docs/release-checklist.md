# Release Checklist

## Alpha baseline

Before calling the narrow local CLI MVP ready for an alpha tag:

1. run the automated baseline
2. validate provider resolution on the target host
3. run a real-host smoke test for service actions
4. run a real-host smoke test for managed config editing
5. confirm documentation matches the operator-visible commands
6. capture release notes in `CHANGELOG.md`

## Automated baseline

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall src
PYTHONPATH=src python3 -m master_control doctor
```

## Real-host smoke tests

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

## Release notes minimum

The alpha notes should mention:

- supported interfaces
- supported providers
- auto provider resolution order
- support for `systemd --user` service operations through `scope=user`
- managed config targets
- service actions currently available
- what is still intentionally out of scope
