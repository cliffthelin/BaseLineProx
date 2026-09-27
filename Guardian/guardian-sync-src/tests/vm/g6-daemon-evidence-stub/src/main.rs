//! G6 EVIDENCE-ONLY STUB — NON-PRODUCTION. DISPOSABLE.
//! NOT A G7 DAEMON SKELETON.
//!
//! This exists for exactly one purpose: to give
//! `tests/vm/g6-candidate-ksni/` a real, observable D-Bus name it can
//! watch for presence/absence, so that G6's "daemon unavailable shows
//! degraded state" required test (contract §30) can be evidenced against
//! a real absent/present signal rather than a manually-simulated toggle.
//!
//! Per `docs/guardian/30_TDD/GUARDIAN_G6_IMPLEMENTATION_HANDOFF.md` §8:
//! "No real production daemon ... unless needed as minimal evidence
//! infrastructure ... keep it to the minimal skeleton needed to prove
//! that one claim ... must be explicitly marked non-production ... and
//! must not be silently adopted, extended, or reused as the real G7
//! daemon skeleton when that gate begins."
//!
//! This binary does exactly one thing: claim the well-known bus name
//! `io.github.cliffthelin.GuardianG6EvidenceStub1` on the session bus
//! and hold it until terminated. It exposes no interfaces, no methods,
//! no properties, no persistent state, no authorization model, and no
//! connection whatsoever to `guardian-core`, `guardian-daemon`, or the
//! real `io.github.cliffthelin.Guardian1` namespace reserved by ADR-001.
//! "Daemon unavailable" is evidenced simply by killing this process (the
//! name is released automatically when its connection closes); "daemon
//! available" is evidenced by it running. Not part of the Cargo
//! workspace (own `[workspace]` table). DISPOSABLE: built and run only
//! inside a disposable VM, never on a primary workstation.

const STUB_BUS_NAME: &str = "io.github.cliffthelin.GuardianG6EvidenceStub1";

#[tokio::main(flavor = "current_thread")]
async fn main() {
    eprintln!(
        "[g6-evidence-stub] G6 EVIDENCE-ONLY / NON-PRODUCTION / DISPOSABLE daemon stub starting, pid={}",
        std::process::id()
    );

    let conn = match zbus::connection::Builder::session()
        .and_then(|b| b.name(STUB_BUS_NAME))
    {
        Ok(builder) => match builder.build().await {
            Ok(c) => c,
            Err(error) => {
                eprintln!("[g6-evidence-stub] failed to build/connect: {error:?}");
                std::process::exit(1);
            }
        },
        Err(error) => {
            eprintln!("[g6-evidence-stub] failed to configure name request: {error:?}");
            std::process::exit(1);
        }
    };
    eprintln!(
        "[g6-evidence-stub] claimed well-known name {} -- evidence-stub daemon considered 'available'",
        STUB_BUS_NAME
    );

    let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        .expect("install SIGTERM handler");
    term.recv().await;
    eprintln!("[g6-evidence-stub] SIGTERM received, releasing name and exiting");
    drop(conn);
}
