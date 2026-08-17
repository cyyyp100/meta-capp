# Security Policy

## Threat model in one paragraph

Meta-Capp is a **local-first desktop application**. The FastAPI backend binds to
`127.0.0.1:8756` and is embedded in the desktop shell; the only outbound traffic the app
is allowed to make is to a local Ollama instance on `127.0.0.1:11434`. There is no
account, no telemetry, no remote API. All learner data — documents, sessions, answers,
gauges, flashcards — lives in a local SQLite database (`data/nwol.db` in development,
the OS application-data directory when packaged).

That shapes what counts as a vulnerability here: anything that makes the app process
untrusted input unsafely (a malicious PDF or source file), exposes the local server or
database beyond the machine, leaks data off the device, or lets an imported document
influence execution.

## Supported versions

Security fixes land on `main` and ship in the next release. Only the latest release is
supported.

| Version | Supported |
|---|:--:|
| Latest release | ✅ |
| Older releases | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through **GitHub Security Advisories**: the *Security* tab →
*Report a vulnerability*. The report stays visible only to you and the maintainers until
a fix ships.

Please include:

- what the issue is and why it matters,
- the affected version, OS and Python version,
- reproduction steps, ideally with a minimal sample (a PDF, a request, a payload),
- the impact you believe it has, and any suggested fix.

## What to expect

| Stage | Target |
|---|---|
| Acknowledgement of your report | within **72 hours** |
| Initial assessment and severity | within **7 days** |
| Fix or mitigation plan communicated | within **30 days** |

This is a small, largely single-maintainer project — those are honest targets, not a
contractual SLA. You will be kept informed if something takes longer.

Please give a reasonable window for a fix before public disclosure. Reporters are
credited in the release notes unless they prefer to stay anonymous.

## Out of scope

- Vulnerabilities that require an attacker to already have local user-level access to
  the machine, or physical access to it.
- The local SQLite database being readable by the user who owns it — this is by design.
- Findings from automated scanners with no demonstrated impact.
- Issues in Ollama, the models it serves, or other upstream dependencies; report those
  upstream (tell us too if Meta-Capp makes the impact worse).
- Model output quality: hallucinations, bad pedagogy or wrong answers are bugs, not
  vulnerabilities — open a normal issue.

## Automated checks

CI runs `pip-audit`, `npm audit` and secret scanning (gitleaks) on every push and pull
request, and the release pipeline re-runs them as a blocking gate before publishing a
binary.
