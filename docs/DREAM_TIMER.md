# Nightly Automatic Dream

## What "nightly automatic" means

MasterControl runs `mc-dream` automatically every night through `systemd timer`.

- You do not need to remember running it manually.
- It runs in background.
- `Persistent=true` means: if the machine was off at schedule time, it runs on next boot.

## Install

```bash
/home/irving/ruas/repos/master-control/scripts/install-dream-timer.sh
```

Custom schedule example:

```bash
/home/irving/ruas/repos/master-control/scripts/install-dream-timer.sh \
  --operator-id irving \
  --time 02:30 \
  --window-days 14
```

## Verify

```bash
systemctl status mastercontrol-dream.timer
systemctl list-timers mastercontrol-dream.timer
journalctl -u mastercontrol-dream.service -n 50 --no-pager
```

## What it writes

- Insights in SQLite (`dream_insights` table):
  - `~/.local/share/mastercontrol/mastercontrol.db`
- Logs in system journal (`journald`).

## Safety model

- Suggestion-only; no automatic system mutation.
- Runs with restricted service hardening.
- Does not bypass privilege policy.

