//! Disposable-VM-only `P1-UDS-003/004` evidence driver. External harness
//! operations create/remove/re-enumerate a virtual SCSI disk; this process
//! observes every state through the production `UDisks` provider.

use std::time::Duration;

use guardian_core::providers::udisks::{
    PowerOffRejection, Topology, TopologyTracker, UdisksProvider,
    revalidate_before_hypothetical_apply,
};
use zbus::Connection;

fn debug_drive<'a>(topology: &'a Topology, stable_id: Option<&str>) -> (&'a str, Vec<String>) {
    let drive = topology
        .drives
        .iter()
        .find(|drive| {
            drive.model.contains("scsi_debug")
                && stable_id.is_none_or(|expected| drive.id == expected)
        })
        .expect("scsi_debug drive visible through UDisks");
    let nodes = topology
        .siblings_of_drive(&drive.object_path)
        .into_iter()
        .map(|block| block.device_node.clone())
        .collect();
    (&drive.id, nodes)
}

async fn run() {
    let connection = Connection::system().await.expect("real system bus");
    let provider = UdisksProvider::new(&connection);
    let initial = provider.topology().await.expect("initial topology");
    let (initial_id, initial_nodes) = debug_drive(&initial, None);
    let initial_id = initial_id.to_owned();
    println!("phase=initial stable_id={initial_id} nodes={initial_nodes:?}");

    async_io::Timer::after(Duration::from_secs(5)).await;
    let removed = provider.topology().await.expect("removed topology");
    let mut removal_tracker = TopologyTracker::new();
    let _ = removal_tracker.observe(&initial);
    let removal_events = removal_tracker.observe(&removed);
    let stale = revalidate_before_hypothetical_apply(&removed, &initial_id);
    println!("phase=removed events={removal_events:?} stale_result={stale:?}");
    assert!(matches!(
        stale,
        Err(PowerOffRejection::StaleOrRemovedIdentity)
    ));

    async_io::Timer::after(Duration::from_secs(7)).await;
    let reenumerated = provider.topology().await.expect("re-enumerated topology");
    let (current_id, current_nodes) = debug_drive(&reenumerated, Some(&initial_id));
    let mut rename_tracker = TopologyTracker::new();
    let _ = rename_tracker.observe(&initial);
    let rename_events = rename_tracker.observe(&reenumerated);
    println!(
        "phase=reenumerated stable_id={current_id} nodes={current_nodes:?} events={rename_events:?}"
    );
    assert_eq!(initial_id, current_id);
    assert_ne!(initial_nodes, current_nodes);
}

fn main() {
    async_io::block_on(run());
}
