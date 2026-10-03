# Reusable installer tasks and compatibility evidence

DR134 selects Ansible Core collection roles with argument_specs and Ansible
Runner instead of inventing an instruction interpreter. The registry is a
SQLite execution-evidence store (not a second settings store): component revisions,
runs and scoped observations. Integration into Baseline's general registry and
web Operations/jobs remains open.

Two registered tasks exist: baseline.environment.native_runtime installs native
Linux prerequisites as root; baseline.environment.native_suite materializes or
inspects locked application files as the named administrator. The canonical
playbook contains one suite play or both plays in that order. Each role has a
real module wrapping the existing Baseline lifecycle rather than an AI command.

An AI author can read publisher directions, classify the installation medium,
select an existing registered component, supply reviewed literal variables and
source/configuration locks, then generate a recipe. It cannot invent a support
claim, use arbitrary shell tasks in this executor, smuggle executable template
expressions into variables, or record success from a plan. A new installation
mechanism requires code, RED/GREEN tests, typed arguments and a new registered
component before its recipes can execute. Windows/macOS, Flatpak/OCI, OS install,
cloud restore and arbitrary application builders are not implemented here.

Catalog expectations include Ubuntu24.04/26.04 and Debian13 amd64, but current
DR134 native-install observations cover five apps on Debian13 and Chrome on
Ubuntu24.04 only. DR133 separately covers all five actual GUI windows on both.
A role result records capability, platform, source/application version, target
instance, kernel/virtualization facts and actual backend SHA256. Root ownership,
non-writable source/parents and five backend fingerprints are checked on the
target before invoking its CLI. Source changes invalidate current-revision proof;
history remains available. Controller component drift during a run is refused.

No observations from injected unit runners count as native proof. Check mode
records no native observations. Whole-run failure does not promote partial
success. A killed controller can leave running status: restart reconciliation,
per-resource cross-controller locking, capability completeness across multiple
hosts, artifact retention and journal/web integration remain work. The underlying
app locks handle launch/apply, but they do not replace a durable orchestration job.

See ../BASELINE_BUILD_WALKTHROUGH.md for executable template/run instructions.
