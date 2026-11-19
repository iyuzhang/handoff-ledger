# Security

Report a suspected vulnerability through the repository's [private advisory form](https://github.com/iyuzhang/handoff-ledger/security/advisories/new). Include the Handoff Ledger version, the deployment method, and enough detail to reproduce the issue with synthetic data. Keep credentials, private source documents, and live database files out of reports.

Handoff Ledger v1 is a single-user service. Its application interface has no login or per-user authorization. Use its loopback listener or an SSH tunnel for private access. Anyone who can reach an unprotected listener can access the workspace. See the [deployment and data handling guide](docs/operations.md).
