## Summary

- what changed
- why this change exists

## Validation

- [ ] `python3 -m ruff check .`
- [ ] `python3 -m mypy src`
- [ ] `PYTHONPATH=src python3 -m unittest discover -s tests`
- [ ] `PYTHONPATH=src python3 -m pytest -q`
- [ ] `python3 -m compileall src`
- [ ] `PYTHONPATH=src python3 -m master_control --json doctor`

## Docs

- [ ] `README.md` updated if landing-page messaging or quick-start behavior changed
- [ ] `docs/README.md` updated if documentation navigation changed
- [ ] relevant docs under `docs/` updated if contracts or project status changed
