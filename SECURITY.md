# Security Policy

## Supported versions

Until Causeway hits `1.0`, only the latest minor receives security fixes.

| Version        | Supported           |
| -------------- | ------------------- |
| `0.x` (latest) | Yes                 |
| Older `0.x`    | No — please upgrade |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Open a private **[GitHub Security Advisory][report]** on this repository
with:

- A description of the issue and its impact
- A minimal reproduction (proof-of-concept code is great)
- The affected version(s)
- Any suggested fix, if you have one

I aim to acknowledge reports within **72 hours** and work with you on a
fix and a coordinated disclosure timeline (usually 7–30 days depending on
severity).

[report]: https://github.com/ruwadgroup/causeway/security/advisories/new

## Scope

In scope:

- The `causeway` Python package
- The official plugin contracts published from this repo
- The `causeway` CLI

Out of scope:

- Vulnerabilities in upstream dependencies (please report those to the
  upstream project — I'll bump versions promptly once a fix exists)
- Issues that require an attacker to already have write access to the
  developer's machine
- Bugs in example apps under `examples/` — these are illustrative, not
  production-ready
- Third-party `causeway-*` plugins not maintained from this repository

## Credit

Researchers who report valid issues will be credited in release notes
(with your permission). No bug bounty program exists — this is a
personal project — but you'll have my public thanks.
