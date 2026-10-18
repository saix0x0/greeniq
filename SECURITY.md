# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Instead, report it privately through GitHub's
[**Private vulnerability reporting**](https://github.com/saix0x0/greeniq/security/advisories/new)
(the *Security* tab → *Report a vulnerability*). We aim to acknowledge reports within a few days.

When reporting, please include:

- a description of the issue and its impact,
- steps to reproduce, and
- any relevant logs or proof-of-concept.

## Scope

GreenIQ runs locally and requires no API key by default. It does not collect personal data and
ships with synthetic data only. The most relevant areas for review are:

- the local web server and API ([`greeniq/api.py`](greeniq/api.py)),
- the optional LLM integration and its grounding gate ([`greeniq/trust/`](greeniq/trust/)), and
- dependency vulnerabilities (tracked via Dependabot).

## Supported versions

The `main` branch receives fixes. There are no long-term support branches.
