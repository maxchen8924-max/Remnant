# Security Policy

Remnant handles highly sensitive family memory data. The current v0.1 release is
an architecture preview and has not completed external security review.

## Supported Versions

| Version | Status |
| --- | --- |
| v0.1.x | Architecture preview, security reports accepted |

## Reporting Security Issues

Please do not open public issues for vulnerabilities involving authentication,
data deletion, scope isolation, consent bypass, raw-data integrity, or local
file disclosure.

Until a dedicated private intake exists, send a private report to the project
maintainer before publishing details. Include:

- affected version or commit
- reproduction steps
- expected and actual behavior
- impact on local data, scope isolation, or auditability
- suggested fix if known

## Security Priorities

High-priority areas:

- sidecar auth and localhost exposure
- relationship-scope data isolation
- raw-message immutability
- deletion and audit log correctness
- source file path privacy
- consent/category enforcement
- LLM or voice paths that could invent facts or mimic identity

## Disclosure Expectations

Remnant is early-stage. Please give maintainers time to reproduce and patch
issues before public disclosure. Security fixes should include regression tests
where practical.
