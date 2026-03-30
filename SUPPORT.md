# Support Policy

## Scope

Master Control is currently a public alpha project.
Support is best-effort and focused on the bounded local-runtime use case documented in the repository.

The maintainership priority today is:

- correctness of the runtime boundary
- safety of policy-gated host actions
- installation and validation on supported Linux environments
- MCP and CLI behavior that matches the documented alpha scope

## Supported Usage

Current support is primarily for:

- source-checkout installs via `install.sh`
- single-host Linux environments
- the latest `main` branch
- the latest published pre-release

## Not A Support Commitment

The following are not currently promised:

- response-time SLA
- custom environment debugging
- support for remote multi-user deployment
- support for unrestricted shell-style host automation
- backward compatibility for undocumented internal APIs

## Where To Ask For Help

- use GitHub Issues for reproducible bugs, install failures, and documentation gaps
- use GitHub Discussions, if enabled, for usage questions and product-direction discussion
- use `SECURITY.md` instead of public issues for vulnerabilities

## What To Include In A Support Request

- operating system and version
- Python version
- install path used
- exact command run
- full error text
- whether the issue reproduces on `main` or only on a specific release/tag

## Compatibility Expectations

Public compatibility should be assumed only for:

- documented CLI behavior
- documented MCP behavior inside the declared alpha scope
- policy and approval guarantees described in the repository docs

Internal module paths may continue to change before 1.0, especially in the architecture-cleanup track.
