# Summary

<!-- What does this change, and why? The intent is what a reviewer cannot reconstruct. -->

Closes #

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Pedagogy / prompt change
- [ ] Refactor (no behaviour change)
- [ ] Documentation
- [ ] Build, CI or packaging

## How it was verified

<!-- Commands you ran, the document you tested with, the OS, whether Ollama was up. -->

```bash
cd nwol && python -m pytest
cd nwol && ruff check .
cd frontend && npm run build && npx vitest run
```

## Checklist

- [ ] Backend suite passes (`cd nwol && python -m pytest`)
- [ ] Lint passes (`cd nwol && ruff check .`)
- [ ] Frontend type-check, build and tests pass
- [ ] New behaviour lives in `nwol/services/`, not in a router or a component
- [ ] No duplicated policy or magic threshold — `nwol/config/settings.py` stays the source of truth
- [ ] Schema change (if any) bumps `DB_SCHEMA_VERSION` and adds an idempotent migration step
- [ ] New user-facing strings added to **both** i18n dictionaries (FR and EN)
- [ ] New behaviour is covered by a test
- [ ] Stays 100 % offline: no remote call, no account, no telemetry, no plan gating
- [ ] `CHANGELOG.md` updated under *Unreleased* if this is user-visible

## Screenshots / recordings

<!-- For any UI change. -->
