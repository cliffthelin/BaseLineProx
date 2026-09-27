//! G8 `UDisks2` read/topology/precondition provider (`P1-UDS-001..004`;
//! contract §27). Native `org.freedesktop.UDisks2` D-Bus only
//! (`org.freedesktop.DBus.ObjectManager.GetManagedObjects`).
//!
//! **Read-only, normatively enforced**: this module contains no callable
//! implementation of `Drive.PowerOff()` — not "untested," genuinely
//! absent from the codebase. It implements the topology model and the
//! six precondition/validation checks contract §27 requires tests to
//! already prove, entirely as pure logic over already-fetched data. No
//! transaction engine is instantiated here, and `guardian-helper` is
//! never invoked. Any future evidence-only `PowerOff()` experiment
//! belongs in a disposable prototype, never in this module.
//!
//! Identity is never a bare `/dev/sdX` string (contract §27/§40) —
//! [`DriveInfo::id`] is `UDisks2`'s own stable `Id` property (derived from
//! vendor/model/serial, not the kernel-assigned device node), so a real
//! `/dev` rename under the same physical hardware does not change it
//! (`P1-UDS-003`).

use std::collections::HashMap;

use zbus::Connection;
use zbus::zvariant::{ObjectPath, OwnedValue};

const DESTINATION: &str = "org.freedesktop.UDisks2";
const ROOT_PATH: &str = "/org/freedesktop/UDisks2";
const DRIVE_INTERFACE: &str = "org.freedesktop.UDisks2.Drive";
const BLOCK_INTERFACE: &str = "org.freedesktop.UDisks2.Block";

/// The raw shape `GetManagedObjects()` returns — object path -> interface
/// name -> property name -> value. Reuses `zbus::fdo`'s own generated
/// type, never a hand-rolled duplicate of the real ABI shape.
pub type ManagedObjects = zbus::fdo::ManagedObjects;

fn interface<'a>(
    interfaces: &'a HashMap<zbus::names::OwnedInterfaceName, HashMap<String, OwnedValue>>,
    name: &str,
) -> Option<&'a HashMap<String, OwnedValue>> {
    interfaces
        .iter()
        .find(|(key, _)| key.as_str() == name)
        .map(|(_, value)| value)
}

/// A physical/topological `Drive` — never identified by `/dev/sdX`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriveInfo {
    pub object_path: String,
    /// `UDisks2`'s own stable identity — survives a `/dev` rename.
    pub id: String,
    pub vendor: String,
    pub model: String,
    pub can_power_off: bool,
    pub removable: bool,
}

/// A `Block` device, distinct from its owning `Drive` — contract §27's
/// required Drive/Block distinction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BlockInfo {
    pub object_path: String,
    /// The volatile kernel device node — retained for display only, never
    /// used as identity.
    pub device_node: String,
    /// Back-reference to the owning `Drive`'s object path.
    pub drive_object_path: String,
}

/// A snapshot of real `UDisks2` topology — `P1-UDS-001`.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct Topology {
    pub drives: Vec<DriveInfo>,
    pub blocks: Vec<BlockInfo>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TopologyEvent {
    Removed {
        drive_id: String,
    },
    Reenumerated {
        drive_id: String,
        previous_nodes: Vec<String>,
        current_nodes: Vec<String>,
    },
}

/// Consecutive-snapshot observer for `P1-UDS-003/004`. Snapshots still
/// come only from the native `UDisks` `ObjectManager`; this type turns a real
/// provider transition into a typed event and never treats `/dev` names
/// as the hardware identity.
#[derive(Clone, Debug, Default)]
pub struct TopologyTracker {
    previous: Option<Topology>,
}

impl TopologyTracker {
    #[must_use]
    pub const fn new() -> Self {
        Self { previous: None }
    }

    pub fn observe(&mut self, current: &Topology) -> Vec<TopologyEvent> {
        let Some(previous) = self.previous.replace(current.clone()) else {
            return Vec::new();
        };
        let mut events = Vec::new();
        for drive in &previous.drives {
            let Some(current_drive) = current.drive_by_id(&drive.id) else {
                events.push(TopologyEvent::Removed {
                    drive_id: drive.id.clone(),
                });
                continue;
            };
            let mut previous_nodes = previous
                .siblings_of_drive(&drive.object_path)
                .into_iter()
                .map(|block| block.device_node.clone())
                .collect::<Vec<_>>();
            let mut current_nodes = current
                .siblings_of_drive(&current_drive.object_path)
                .into_iter()
                .map(|block| block.device_node.clone())
                .collect::<Vec<_>>();
            previous_nodes.sort();
            current_nodes.sort();
            if previous_nodes != current_nodes {
                events.push(TopologyEvent::Reenumerated {
                    drive_id: drive.id.clone(),
                    previous_nodes,
                    current_nodes,
                });
            }
        }
        events
    }
}

impl Topology {
    /// Every block sharing one drive's object path — `P1-UDS-002`.
    #[must_use]
    pub fn siblings_of_drive(&self, drive_object_path: &str) -> Vec<&BlockInfo> {
        self.blocks
            .iter()
            .filter(|block| block.drive_object_path == drive_object_path)
            .collect()
    }

    #[must_use]
    pub fn drive_by_id(&self, id: &str) -> Option<&DriveInfo> {
        self.drives.iter().find(|drive| drive.id == id)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum UdisksError {
    ProviderUnavailable(String),
    MalformedResponse(String),
}

impl std::fmt::Display for UdisksError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ProviderUnavailable(message) => {
                write!(formatter, "UDisks2 unavailable: {message}")
            }
            Self::MalformedResponse(message) => {
                write!(formatter, "malformed UDisks2 response: {message}")
            }
        }
    }
}

impl std::error::Error for UdisksError {}

fn optional_str_prop(properties: &HashMap<String, OwnedValue>, key: &str) -> String {
    properties
        .get(key)
        .and_then(|v| v.downcast_ref::<zbus::zvariant::Str>().ok())
        .map(|s| s.as_str().to_owned())
        .unwrap_or_default()
}

fn bool_prop(properties: &HashMap<String, OwnedValue>, key: &str) -> bool {
    properties
        .get(key)
        .and_then(|v| v.downcast_ref::<bool>().ok())
        .unwrap_or(false)
}

/// Normalizes an already-fetched `GetManagedObjects()` reply into typed
/// topology (Layer 1 testable — no D-Bus involved).
/// # Errors
///
/// Returns [`UdisksError::MalformedResponse`] when required identity or
/// topology properties are absent, empty, duplicated, or have the wrong type.
pub fn normalize_topology(objects: &ManagedObjects) -> Result<Topology, UdisksError> {
    let mut topology = Topology::default();
    for (path, interfaces) in objects {
        if let Some(drive_props) = interface(interfaces, DRIVE_INTERFACE) {
            let provider_id = optional_str_prop(drive_props, "Id");
            // UDisks legitimately reports an empty Drive.Id for some
            // hardware (for example the VM floppy). Its Drive object path
            // is still provider-owned physical identity and, unlike a
            // Block device node, survives `/dev` renaming.
            let id = if provider_id.is_empty() {
                path.to_string()
            } else {
                provider_id
            };
            if topology.drives.iter().any(|drive| drive.id == id) {
                return Err(UdisksError::MalformedResponse(format!(
                    "duplicate drive identity: {id}"
                )));
            }
            topology.drives.push(DriveInfo {
                object_path: path.to_string(),
                id,
                vendor: optional_str_prop(drive_props, "Vendor"),
                model: optional_str_prop(drive_props, "Model"),
                can_power_off: bool_prop(drive_props, "CanPowerOff"),
                removable: bool_prop(drive_props, "Removable"),
            });
        }
        if let Some(block_props) = interface(interfaces, BLOCK_INTERFACE) {
            let drive_object_path = block_props
                .get("Drive")
                .and_then(|v| v.downcast_ref::<ObjectPath<'_>>().ok())
                .map(|p| p.as_str().to_owned())
                .ok_or_else(|| {
                    UdisksError::MalformedResponse("missing/invalid Block.Drive".to_owned())
                })?;
            let device_node = block_props
                .get("PreferredDevice")
                .or_else(|| block_props.get("Device"))
                .and_then(|v| Vec::<u8>::try_from(v.clone()).ok())
                .map(|bytes| {
                    String::from_utf8_lossy(&bytes)
                        .trim_end_matches('\0')
                        .to_owned()
                })
                .filter(|node| !node.is_empty())
                .ok_or_else(|| {
                    UdisksError::MalformedResponse(
                        "missing/invalid Block.PreferredDevice/Device".to_owned(),
                    )
                })?;
            topology.blocks.push(BlockInfo {
                object_path: path.to_string(),
                device_node,
                drive_object_path,
            });
        }
    }
    Ok(topology)
}

/// A `PowerOff()` precondition check failed — contract §27's six required
/// proofs, as a real typed rejection, never a bare bool.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PowerOffRejection {
    /// `CanPowerOff == false` — the drive itself does not support it.
    NotSupported,
    /// The requested drive `id` no longer appears in the current
    /// topology snapshot — genuinely removed, or a stale identity from an
    /// earlier read.
    StaleOrRemovedIdentity,
    /// The caller did not mark this as a real, user-initiated action —
    /// contract §27: "action is marked user-initiated only."
    NotUserInitiated,
}

impl std::fmt::Display for PowerOffRejection {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotSupported => formatter.write_str("CanPowerOff is false for this drive"),
            Self::StaleOrRemovedIdentity => {
                formatter.write_str("drive identity is stale or the device has been removed")
            }
            Self::NotUserInitiated => formatter.write_str("action was not marked user-initiated"),
        }
    }
}

impl std::error::Error for PowerOffRejection {}

/// What a client would be shown before any future authorization step —
/// contract §27: "affected siblings are returned to the client before
/// authorization." This function performs no authorization itself; it
/// only assembles the disclosure a future gate's authorization step would
/// consume.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PowerOffPreconditions {
    pub drive: DriveInfo,
    pub affected_siblings: Vec<BlockInfo>,
}

/// Validates every §27-required precondition for a (never executed, in
/// this gate) `PowerOff()` against a real topology snapshot. This is the
/// complete validation/rejection surface contract §27 requires exist —
/// there is no corresponding `apply_power_off` anywhere in this codebase.
///
/// # Errors
///
/// See [`PowerOffRejection`].
pub fn validate_power_off_preconditions(
    topology: &Topology,
    drive_id: &str,
    user_initiated: bool,
) -> Result<PowerOffPreconditions, PowerOffRejection> {
    if !user_initiated {
        return Err(PowerOffRejection::NotUserInitiated);
    }
    let drive = topology
        .drive_by_id(drive_id)
        .ok_or(PowerOffRejection::StaleOrRemovedIdentity)?;
    if !drive.can_power_off {
        return Err(PowerOffRejection::NotSupported);
    }
    let affected_siblings = topology
        .siblings_of_drive(&drive.object_path)
        .into_iter()
        .cloned()
        .collect();
    Ok(PowerOffPreconditions {
        drive: drive.clone(),
        affected_siblings,
    })
}

/// Contract §27: "device removal between validation and apply rejects."
/// Compares an earlier validated snapshot's drive identity against a
/// freshly re-fetched topology — real re-validation, never trusting a
/// stale in-memory result across time. There is no `apply` step this
/// feeds into in this gate; this function exists so that step's real
/// implementation (a later gate) has a proven, tested re-check to call.
///
/// # Errors
///
/// See [`PowerOffRejection`].
pub fn revalidate_before_hypothetical_apply(
    fresh_topology: &Topology,
    drive_id: &str,
) -> Result<(), PowerOffRejection> {
    if fresh_topology.drive_by_id(drive_id).is_some() {
        Ok(())
    } else {
        Err(PowerOffRejection::StaleOrRemovedIdentity)
    }
}

pub struct UdisksProvider<'c> {
    connection: &'c Connection,
}

impl<'c> UdisksProvider<'c> {
    #[must_use]
    pub const fn new(connection: &'c Connection) -> Self {
        Self { connection }
    }

    pub async fn probe(&self) -> bool {
        let Ok(dbus) = zbus::fdo::DBusProxy::new(self.connection).await else {
            return false;
        };
        let Ok(destination) = zbus::names::BusName::try_from(DESTINATION) else {
            return false;
        };
        dbus.name_has_owner(destination).await.unwrap_or(false)
    }

    /// Real `GetManagedObjects()` + normalization — `P1-UDS-001`.
    ///
    /// # Errors
    ///
    /// See [`UdisksError`].
    pub async fn topology(&self) -> Result<Topology, UdisksError> {
        let object_manager = zbus::fdo::ObjectManagerProxy::builder(self.connection)
            .destination(DESTINATION)
            .map_err(|error| UdisksError::ProviderUnavailable(error.to_string()))?
            .path(ROOT_PATH)
            .map_err(|error| UdisksError::ProviderUnavailable(error.to_string()))?
            .build()
            .await
            .map_err(|error| UdisksError::ProviderUnavailable(error.to_string()))?;

        let objects = object_manager
            .get_managed_objects()
            .await
            .map_err(|error| classify_get_managed_objects_error(&error))?;

        normalize_topology(&objects)
    }
}

/// `GetManagedObjects()` is `topology`'s first live call — building the
/// `ObjectManagerProxy` above never confirms `UDisks2` is actually present
/// (zbus proxy construction is lazy), so any failure here (in particular a
/// real `org.freedesktop.DBus.Error.ServiceUnknown`, confirmed via real-VM
/// evidence: masking `UDisks2` produces exactly this error) means the
/// provider itself is unreachable, never a malformed *response* — there is
/// no response yet to be malformed.
fn classify_get_managed_objects_error(error: &zbus::fdo::Error) -> UdisksError {
    match error {
        zbus::fdo::Error::ServiceUnknown(_) | zbus::fdo::Error::NameHasNoOwner(_) => {
            UdisksError::ProviderUnavailable(error.to_string())
        }
        other => UdisksError::MalformedResponse(other.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use zbus::zvariant::OwnedObjectPath;

    fn drive_props(id: &str, can_power_off: bool) -> HashMap<String, OwnedValue> {
        HashMap::from([
            (
                "Id".to_owned(),
                OwnedValue::from(zbus::zvariant::Str::from(id.to_owned())),
            ),
            (
                "Vendor".to_owned(),
                OwnedValue::from(zbus::zvariant::Str::from("TestVendor")),
            ),
            (
                "Model".to_owned(),
                OwnedValue::from(zbus::zvariant::Str::from("TestModel")),
            ),
            ("CanPowerOff".to_owned(), OwnedValue::from(can_power_off)),
            ("Removable".to_owned(), OwnedValue::from(true)),
        ])
    }

    fn block_props(drive_path: &str) -> HashMap<String, OwnedValue> {
        HashMap::from([
            (
                "Drive".to_owned(),
                OwnedValue::from(ObjectPath::try_from(drive_path).unwrap()),
            ),
            (
                "PreferredDevice".to_owned(),
                OwnedValue::try_from(zbus::zvariant::Value::new(b"/dev/sda\0".to_vec())).unwrap(),
            ),
        ])
    }

    fn managed_objects_with_one_drive_two_blocks() -> ManagedObjects {
        let mut objects: ManagedObjects = HashMap::new();
        let drive_path =
            OwnedObjectPath::try_from("/org/freedesktop/UDisks2/drives/Test_1").unwrap();
        objects.insert(
            drive_path.clone(),
            HashMap::from([(
                zbus::names::OwnedInterfaceName::try_from(DRIVE_INTERFACE).unwrap(),
                drive_props("Test_1", true),
            )]),
        );
        for n in 1..=2 {
            let block_path =
                OwnedObjectPath::try_from(format!("/org/freedesktop/UDisks2/block_devices/sda{n}"))
                    .unwrap();
            objects.insert(
                block_path,
                HashMap::from([(
                    zbus::names::OwnedInterfaceName::try_from(BLOCK_INTERFACE).unwrap(),
                    block_props(drive_path.as_str()),
                )]),
            );
        }
        objects
    }

    #[test]
    fn topology_preserves_drive_block_relationship() {
        let topology = normalize_topology(&managed_objects_with_one_drive_two_blocks()).unwrap();
        assert_eq!(topology.drives.len(), 1);
        assert_eq!(topology.blocks.len(), 2);
        assert_eq!(topology.drives[0].id, "Test_1");
    }

    #[test]
    fn siblings_are_visible_for_a_shared_physical_parent() {
        let topology = normalize_topology(&managed_objects_with_one_drive_two_blocks()).unwrap();
        let drive = &topology.drives[0];
        let siblings = topology.siblings_of_drive(&drive.object_path);
        assert_eq!(siblings.len(), 2);
    }

    #[test]
    fn identity_is_the_stable_id_never_the_dev_node() {
        let topology = normalize_topology(&managed_objects_with_one_drive_two_blocks()).unwrap();
        assert_eq!(topology.drives[0].id, "Test_1");
        // Confirms the block's device node is tracked separately from
        // drive identity -- a rename of the node must never change `id`.
        assert!(
            topology
                .blocks
                .iter()
                .all(|b| b.drive_object_path == topology.drives[0].object_path)
        );
    }

    #[test]
    fn changing_dev_name_does_not_break_identity_across_two_snapshots() {
        // Simulates a real /dev rename: same drive `Id`, different block
        // object paths/device nodes between two snapshots.
        let first = normalize_topology(&managed_objects_with_one_drive_two_blocks()).unwrap();
        let mut renamed_objects: ManagedObjects = HashMap::new();
        let drive_path =
            OwnedObjectPath::try_from("/org/freedesktop/UDisks2/drives/Test_1").unwrap();
        renamed_objects.insert(
            drive_path.clone(),
            HashMap::from([(
                zbus::names::OwnedInterfaceName::try_from(DRIVE_INTERFACE).unwrap(),
                drive_props("Test_1", true),
            )]),
        );
        let renamed_block =
            OwnedObjectPath::try_from("/org/freedesktop/UDisks2/block_devices/sdb1").unwrap();
        renamed_objects.insert(
            renamed_block,
            HashMap::from([(
                zbus::names::OwnedInterfaceName::try_from(BLOCK_INTERFACE).unwrap(),
                block_props(drive_path.as_str()),
            )]),
        );
        let second = normalize_topology(&renamed_objects).unwrap();
        assert_eq!(
            first.drives[0].id, second.drives[0].id,
            "identity must survive a /dev rename"
        );
    }

    #[test]
    fn tracker_emits_reenumeration_for_same_identity_with_new_node() {
        let first = normalize_topology(&managed_objects_with_one_drive_two_blocks()).unwrap();
        let mut second = first.clone();
        second.blocks[0].device_node = "/dev/sdz1".to_owned();
        let mut tracker = TopologyTracker::new();
        assert!(tracker.observe(&first).is_empty());
        let events = tracker.observe(&second);
        assert!(matches!(
            events.as_slice(),
            [TopologyEvent::Reenumerated { drive_id, .. }] if drive_id == "Test_1"
        ));
    }

    #[test]
    fn tracker_emits_removal_and_stale_reference_rejects() {
        let first = normalize_topology(&managed_objects_with_one_drive_two_blocks()).unwrap();
        let mut tracker = TopologyTracker::new();
        assert!(tracker.observe(&first).is_empty());
        let current = Topology::default();
        assert_eq!(
            tracker.observe(&current),
            vec![TopologyEvent::Removed {
                drive_id: "Test_1".to_owned()
            }]
        );
        assert_eq!(
            revalidate_before_hypothetical_apply(&current, "Test_1"),
            Err(PowerOffRejection::StaleOrRemovedIdentity)
        );
    }

    #[test]
    fn can_power_off_false_rejects() {
        let mut objects: ManagedObjects = HashMap::new();
        objects.insert(
            OwnedObjectPath::try_from("/org/freedesktop/UDisks2/drives/NoPower").unwrap(),
            HashMap::from([(
                zbus::names::OwnedInterfaceName::try_from(DRIVE_INTERFACE).unwrap(),
                drive_props("NoPower", false),
            )]),
        );
        let topology = normalize_topology(&objects).unwrap();
        let result = validate_power_off_preconditions(&topology, "NoPower", true);
        assert_eq!(result, Err(PowerOffRejection::NotSupported));
    }

    #[test]
    fn stale_identity_rejects() {
        let topology = normalize_topology(&managed_objects_with_one_drive_two_blocks()).unwrap();
        let result = validate_power_off_preconditions(&topology, "DoesNotExist", true);
        assert_eq!(result, Err(PowerOffRejection::StaleOrRemovedIdentity));
    }

    #[test]
    fn not_user_initiated_rejects_before_anything_else() {
        let topology = normalize_topology(&managed_objects_with_one_drive_two_blocks()).unwrap();
        let result = validate_power_off_preconditions(&topology, "Test_1", false);
        assert_eq!(result, Err(PowerOffRejection::NotUserInitiated));
    }

    #[test]
    fn valid_request_discloses_siblings_before_any_authorization() {
        let topology = normalize_topology(&managed_objects_with_one_drive_two_blocks()).unwrap();
        let preconditions = validate_power_off_preconditions(&topology, "Test_1", true).unwrap();
        assert_eq!(preconditions.affected_siblings.len(), 2);
        assert_eq!(preconditions.drive.id, "Test_1");
    }

    #[test]
    fn removal_between_validation_and_apply_rejects() {
        let topology = normalize_topology(&managed_objects_with_one_drive_two_blocks()).unwrap();
        validate_power_off_preconditions(&topology, "Test_1", true).unwrap();

        // Device removed before the (hypothetical, never-implemented)
        // apply step -- a fresh, empty topology.
        let empty_topology = Topology::default();
        let result = revalidate_before_hypothetical_apply(&empty_topology, "Test_1");
        assert_eq!(result, Err(PowerOffRejection::StaleOrRemovedIdentity));
    }

    #[test]
    fn zero_siblings_is_a_real_distinct_case() {
        let mut objects: ManagedObjects = HashMap::new();
        objects.insert(
            OwnedObjectPath::try_from("/org/freedesktop/UDisks2/drives/Lonely").unwrap(),
            HashMap::from([(
                zbus::names::OwnedInterfaceName::try_from(DRIVE_INTERFACE).unwrap(),
                drive_props("Lonely", true),
            )]),
        );
        let topology = normalize_topology(&objects).unwrap();
        let preconditions = validate_power_off_preconditions(&topology, "Lonely", true).unwrap();
        assert!(preconditions.affected_siblings.is_empty());
    }

    #[test]
    fn empty_provider_id_falls_back_to_stable_drive_object_path() {
        let mut objects: ManagedObjects = HashMap::new();
        objects.insert(
            OwnedObjectPath::try_from("/org/freedesktop/UDisks2/drives/Sparse").unwrap(),
            HashMap::from([(
                zbus::names::OwnedInterfaceName::try_from(DRIVE_INTERFACE).unwrap(),
                HashMap::new(),
            )]),
        );
        let topology = normalize_topology(&objects).unwrap();
        assert_eq!(
            topology.drives[0].id,
            "/org/freedesktop/UDisks2/drives/Sparse"
        );
    }

    /// Real-VM regression (G8 evidence): masking `UDisks2` produced a real
    /// `ServiceUnknown` error from `GetManagedObjects()`, and the
    /// production code originally misclassified it as `MalformedResponse`
    /// — a real provider outage must never be reported as a malformed
    /// response.
    #[test]
    fn get_managed_objects_failure_is_provider_unavailable_not_malformed() {
        let error = zbus::fdo::Error::ServiceUnknown(
            "The name org.freedesktop.UDisks2 was not provided by any .service files".to_owned(),
        );
        let classified = classify_get_managed_objects_error(&error);
        assert!(matches!(classified, UdisksError::ProviderUnavailable(_)));
    }

    /// Real dbusmock regression (G8 evidence): a live mock object present
    /// on the bus but not implementing `GetManagedObjects` produced a real
    /// `UnknownMethod` error — a real, live provider responding with an
    /// unexpected shape must be reported as malformed, never conflated
    /// with the provider being absent.
    #[test]
    fn get_managed_objects_unknown_method_is_malformed_not_provider_unavailable() {
        let error = zbus::fdo::Error::UnknownMethod("GetManagedObjects not found".to_owned());
        let classified = classify_get_managed_objects_error(&error);
        assert!(matches!(classified, UdisksError::MalformedResponse(_)));
    }
}
