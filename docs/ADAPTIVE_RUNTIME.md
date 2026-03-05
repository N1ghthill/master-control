# Adaptive Runtime Usage

## Commands

Tone analysis:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-tone-analyzer \
  --text "PELO AMOR resolve dns agora"
```

Intent classification (local-first):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-intent-classifier \
  --text "reiniciar serviço unbound urgente"
```

Operator profile snapshot:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-operator-profiler \
  profile --operator-id irving
```

Run dream insights:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-dream \
  --operator-id irving --window-days 30
```

Install nightly automatic dream:

```bash
/home/irving/ruas/repos/master-control/scripts/install-dream-timer.sh \
  --operator-id irving --time 03:00 --window-days 30
```

MasterControl core loop (auto adaptive):

```bash
/home/irving/ruas/repos/master-control/scripts/mastercontrol \
  --operator-name Irving \
  --intent "Please flush DNS cache quickly and verify resolver" \
  --risk-level medium
```

## Notes

- Profile and insights are local in:
  - `~/.local/share/mastercontrol/mastercontrol.db`
- Learned path rules are also local in `learned_rules` (same SQLite DB).
- Dream output is suggestion-only.
- Adaptive logic does not bypass privilege policy.
