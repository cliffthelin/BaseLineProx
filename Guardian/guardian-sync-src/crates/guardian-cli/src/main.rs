//! `guardian` — the G9 CLI (contract §34), a thin client over
//! `guardian-client` (ADR-007) with human-readable and JSON output
//! modes. Every command's JSON mode emits real `serde_json`-serialized
//! output (P1-CLI-001: "MUST parse as valid JSON") — never hand-formatted
//! strings. Daemon-offline behavior (P1-CLI-002) is a real, deterministic
//! exit code, exercised against a genuinely-stopped daemon, not
//! simulated.
//!
//! **Exit-code convention (fixed here, not left to a future revision):**
//! `0` success; `2` daemon unavailable
//! ([`guardian_client::ClientError::DaemonUnavailable`]); `3` malformed
//! daemon response ([`guardian_client::ClientError::MalformedResponse`]);
//! `64` usage error (unknown command/argument, matching the BSD
//! `sysexits.h` `EX_USAGE` convention).
//!
//! No generic `run`/`exec`/arbitrary-D-Bus-call/provider-method-
//! passthrough command exists anywhere in this binary (contract §40;
//! this handoff's own CLI-scope discipline) — exactly the seven §34
//! minimum commands, no more.

use std::process::ExitCode;

use guardian_client::{ClientError, DaemonConnection};
use serde::Serialize;

const EXIT_SUCCESS: u8 = 0;
const EXIT_DAEMON_UNAVAILABLE: u8 = 2;
const EXIT_MALFORMED_RESPONSE: u8 = 3;
const EXIT_USAGE: u8 = 64;

#[derive(Serialize)]
struct JsonError {
    error: String,
}

fn print_error_and_exit_code(error: &ClientError) -> ExitCode {
    match error {
        ClientError::DaemonUnavailable(_) => ExitCode::from(EXIT_DAEMON_UNAVAILABLE),
        ClientError::MalformedResponse(_) => ExitCode::from(EXIT_MALFORMED_RESPONSE),
    }
}

fn emit_error(error: &ClientError, json: bool) {
    if json {
        let payload = JsonError {
            error: error.to_string(),
        };
        println!(
            "{}",
            serde_json::to_string(&payload).expect("JsonError always serializes")
        );
    } else {
        eprintln!("guardian: {error}");
    }
}

fn usage() -> &'static str {
    "Usage: guardian [--json] <command>\n\n\
     Commands:\n  \
     status         daemon connection state and contract version\n  \
     capabilities   list known capabilities\n  \
     providers      list capabilities grouped by provider\n  \
     incidents      list incidents\n  \
     blockers       list real logind system blockers\n  \
     psi            real PSI pressure summary\n  \
     transactions   list transaction history\n\n\
     A machine-readable JSON mode is available via --json for every command."
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let json = args.iter().any(|arg| arg == "--json");
    let command = args.iter().find(|arg| !arg.starts_with("--"));

    let Some(command) = command else {
        eprintln!("{}", usage());
        return ExitCode::from(EXIT_USAGE);
    };

    async_io::block_on(run(command, json))
}

async fn run(command: &str, json: bool) -> ExitCode {
    let connection = match DaemonConnection::connect().await {
        Ok(connection) => connection,
        Err(error) => {
            emit_error(&error, json);
            return print_error_and_exit_code(&error);
        }
    };

    match command {
        "status" => status(&connection, json).await,
        "capabilities" | "providers" => capabilities(&connection, json).await,
        "incidents" => incidents(&connection, json).await,
        "blockers" => blockers(&connection, json).await,
        "psi" => psi(&connection, json).await,
        "transactions" => transactions(&connection, json).await,
        _ => {
            eprintln!("guardian: unknown command '{command}'\n\n{}", usage());
            ExitCode::from(EXIT_USAGE)
        }
    }
}

async fn status(connection: &DaemonConnection, json: bool) -> ExitCode {
    match connection.contract_info().await {
        Ok(info) => {
            if json {
                println!(
                    "{}",
                    serde_json::to_string(&serde_json::json!({
                        "contract_version": info.contract_version,
                        "service_state": info.service_state,
                    }))
                    .unwrap()
                );
            } else {
                println!("Guardian daemon: connected");
                println!("  contract version: {}", info.contract_version);
                println!("  service state:    {}", info.service_state);
            }
            ExitCode::from(EXIT_SUCCESS)
        }
        Err(error) => {
            emit_error(&error, json);
            print_error_and_exit_code(&error)
        }
    }
}

async fn capabilities(connection: &DaemonConnection, json: bool) -> ExitCode {
    match connection.capabilities().await {
        Ok(capabilities) => {
            if json {
                println!(
                    "{}",
                    serde_json::to_string(&capabilities_json(&capabilities)).unwrap()
                );
            } else if capabilities.is_empty() {
                println!("(no capabilities reported)");
            } else {
                for capability in &capabilities {
                    println!(
                        "{}  <-  {}  availability={} health={} read={} write={} authz={} priv={}",
                        capability.capability_id,
                        capability.provider_id,
                        capability.availability,
                        capability.health,
                        capability.read_support,
                        capability.write_support,
                        capability.authorization_ownership,
                        capability.privilege_requirement,
                    );
                }
            }
            ExitCode::from(EXIT_SUCCESS)
        }
        Err(error) => {
            emit_error(&error, json);
            print_error_and_exit_code(&error)
        }
    }
}

fn capabilities_json(capabilities: &[guardian_client::Capability]) -> serde_json::Value {
    serde_json::Value::Array(
        capabilities
            .iter()
            .map(|capability| {
                serde_json::json!({
                    "capability_id": capability.capability_id,
                    "provider_id": capability.provider_id,
                    "provider_version": capability.provider_version,
                    "availability": capability.availability,
                    "health": capability.health,
                    "read_support": capability.read_support,
                    "write_support": capability.write_support,
                    "authorization_ownership": capability.authorization_ownership,
                    "privilege_requirement": capability.privilege_requirement,
                    "interface_kind": capability.interface_kind,
                    "last_observed_at": capability.last_observed_at,
                })
            })
            .collect(),
    )
}

async fn incidents(connection: &DaemonConnection, json: bool) -> ExitCode {
    match connection.incidents().await {
        Ok(incidents) => {
            if json {
                let payload: Vec<serde_json::Value> = incidents
                    .iter()
                    .map(|incident| {
                        serde_json::json!({
                            "incident_id": incident.incident_id,
                            "opened_at": incident.opened_at,
                            "closed_at": incident.closed_at,
                            "status": incident.status,
                            "summary": incident.summary,
                            "confidence": incident.confidence,
                            "primary_resource": incident.primary_resource,
                        })
                    })
                    .collect();
                println!("{}", serde_json::to_string(&payload).unwrap());
            } else if incidents.is_empty() {
                println!("(no incidents)");
            } else {
                for incident in &incidents {
                    println!(
                        "{}  {}  {}",
                        incident.incident_id, incident.status, incident.summary
                    );
                }
            }
            ExitCode::from(EXIT_SUCCESS)
        }
        Err(error) => {
            emit_error(&error, json);
            print_error_and_exit_code(&error)
        }
    }
}

async fn blockers(connection: &DaemonConnection, json: bool) -> ExitCode {
    match connection.blockers().await {
        Ok(blockers) => {
            if json {
                let payload: Vec<serde_json::Value> = blockers
                    .iter()
                    .map(|blocker| {
                        serde_json::json!({
                            "what": blocker.what,
                            "who": blocker.who,
                            "why": blocker.why,
                            "mode": blocker.mode,
                            "uid": blocker.uid,
                            "pid": blocker.pid,
                        })
                    })
                    .collect();
                println!("{}", serde_json::to_string(&payload).unwrap());
            } else if blockers.is_empty() {
                println!("(no system blockers)");
            } else {
                for blocker in &blockers {
                    println!(
                        "{} by {} ({}): {}",
                        blocker.what, blocker.who, blocker.mode, blocker.why
                    );
                }
            }
            ExitCode::from(EXIT_SUCCESS)
        }
        Err(error) => {
            emit_error(&error, json);
            print_error_and_exit_code(&error)
        }
    }
}

async fn psi(connection: &DaemonConnection, json: bool) -> ExitCode {
    match connection.psi_summary().await {
        Ok(summary) => {
            if json {
                let payload: Vec<serde_json::Value> = summary
                    .iter()
                    .map(|entry| {
                        serde_json::json!({
                            "kind": entry.kind,
                            "avg10": entry.avg10,
                            "avg60": entry.avg60,
                            "avg300": entry.avg300,
                            "available": entry.available,
                        })
                    })
                    .collect();
                println!("{}", serde_json::to_string(&payload).unwrap());
            } else {
                for entry in &summary {
                    if entry.available {
                        println!(
                            "{}: avg10={:.2} avg60={:.2} avg300={:.2}",
                            entry.kind, entry.avg10, entry.avg60, entry.avg300
                        );
                    } else {
                        println!("{}: unavailable", entry.kind);
                    }
                }
            }
            ExitCode::from(EXIT_SUCCESS)
        }
        Err(error) => {
            emit_error(&error, json);
            print_error_and_exit_code(&error)
        }
    }
}

async fn transactions(connection: &DaemonConnection, json: bool) -> ExitCode {
    match connection.transactions().await {
        Ok(transactions) => {
            if json {
                let payload: Vec<serde_json::Value> = transactions
                    .iter()
                    .map(|transaction| {
                        serde_json::json!({
                            "transaction_id": transaction.transaction_id,
                            "state": transaction.state,
                            "created_at": transaction.created_at,
                        })
                    })
                    .collect();
                println!("{}", serde_json::to_string(&payload).unwrap());
            } else if transactions.is_empty() {
                println!("(no transactions)");
            } else {
                for transaction in &transactions {
                    println!("{}  {}", transaction.transaction_id, transaction.state);
                }
            }
            ExitCode::from(EXIT_SUCCESS)
        }
        Err(error) => {
            emit_error(&error, json);
            print_error_and_exit_code(&error)
        }
    }
}
