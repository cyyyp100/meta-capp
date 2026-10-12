# Security Policy

## Threat model in one paragraph

Meta-Capp is a **local-first desktop application**. The FastAPI backend binds to
`127.0.0.1:8756` and is embedded in the desktop shell; every API call and WebSocket must
carry a per-launch token, and requests from another origin or another local site are
refused. The app talks to a local Ollama instance on `127.0.0.1:11434`. There is no
account, no telemetry, no remote API. All learner data — documents, sessions, answers,
gauges, flashcards — lives in a local SQLite database (`data/nwol.db` in development,
the OS application-data directory when packaged).

**One outbound request exists, opt-in and off by default**: the update check
(`nwol/services/updates.py`) reads the latest version number from GitHub's API when the
user asks for it. Its response is treated as untrusted input: only a strictly validated
version number is kept, the download URL is hard-coded, redirects are not followed and
TLS is always verified.

That shapes what counts as a vulnerability here: anything that makes the app process
untrusted input unsafely (a malicious PDF or source file, a hostile update response),
exposes the local server or database beyond the machine, lets a web page reach the local
API or the native bridge, leaks data off the device, or lets an imported document
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

CI runs `pip-audit`, `npm audit`, secret scanning (gitleaks) and a dependency licence
check (`scripts/third_party_notices.py --check`) on every push and pull request, and the
release pipeline re-runs them as a blocking gate before publishing a binary. Each release
publishes `SHA256SUMS.txt` next to the archives; signed builds can also be checked with
`codesign --verify` (macOS) or the file's *Digital Signatures* tab (Windows).
