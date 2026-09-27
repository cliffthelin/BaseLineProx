//! Disposable-VM-only `P1-PSI-004` evidence driver. It registers the real
//! production `PsiEventSource` and waits only through kernel `poll(POLLPRI)`;
//! the bounded pressure workload is launched separately by the VM harness.

use std::time::Duration;

use guardian_core::providers::psi::{PsiEventSource, PsiFileSource};
use guardian_core::psi::{PressureSeverity, PsiReading, PsiResourceKind, SeverityThresholds};

fn main() {
    let source = PsiFileSource::real();
    let baseline = match source.read(PsiResourceKind::Cpu).expect("read CPU PSI") {
        PsiReading::Present(resource) => resource.some.avg10,
        PsiReading::Unavailable => panic!("CPU PSI unavailable"),
    };
    let thresholds = SeverityThresholds::new(baseline + 0.01, baseline + 50.0);
    let mut events = PsiEventSource::register(
        &source,
        PsiResourceKind::Cpu,
        "some",
        10_000,
        2_000_000,
        thresholds,
        PressureSeverity::Elevated,
    )
    .expect("register real PSI trigger");
    println!(
        "registered=true path=/proc/pressure/cpu trigger='some 10000 2000000' wait=poll(POLLPRI) baseline_avg10={baseline}"
    );
    for wake in 1..=20 {
        match events
            .wait_for_event(Some(Duration::from_secs(2)))
            .expect("wait for real PSI event")
        {
            Some(event) => {
                println!("wake={wake} guardian_event={event:?}");
                return;
            }
            None => println!("wake={wake} crossing=false"),
        }
    }
    panic!("real PSI wakes did not produce a G5 threshold crossing");
}
