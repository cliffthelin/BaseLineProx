use guardian_core::error::{GuardianDbusError, GuardianErrorCategory};
use guardian_daemon::{GuardianContract, INTERFACE_NAME, OBJECT_PATH};
use guardian_testkit::PrivateSessionBus;
use roxmltree::{Document, Node};
use std::any::Any;
use std::collections::{BTreeMap, HashSet};
use std::panic::{AssertUnwindSafe, catch_unwind};
use zbus::blocking::{Connection, Proxy, connection};

const EXPECTED_XML: &str =
    include_str!("../../../dbus/interfaces/io.github.cliffthelin.Guardian1.xml");
const GUARDIAN_INTERFACE_PREFIX: &str = "io.github.cliffthelin.";
const ERROR_PROBE_INTERFACE: &str = "io.github.cliffthelin.ErrorProbe1";
const ERROR_PROBE_PATH: &str = "/io/github/cliffthelin/ErrorProbe1";

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct AnnotationContract {
    name: String,
    value: String,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct ArgumentContract {
    name: Option<String>,
    signature: String,
    direction: Option<String>,
    annotations: Vec<AnnotationContract>,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct MethodContract {
    name: String,
    arguments: Vec<ArgumentContract>,
    annotations: Vec<AnnotationContract>,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct PropertyContract {
    name: String,
    signature: String,
    access: String,
    annotations: Vec<AnnotationContract>,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct SignalContract {
    name: String,
    arguments: Vec<ArgumentContract>,
    annotations: Vec<AnnotationContract>,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct InterfaceContract {
    name: String,
    methods: Vec<MethodContract>,
    properties: Vec<PropertyContract>,
    signals: Vec<SignalContract>,
    annotations: Vec<AnnotationContract>,
}

#[derive(Debug, Eq, Ord, PartialEq, PartialOrd)]
struct QualifiedMethodContract {
    object_path: String,
    interface_name: String,
    method: MethodContract,
}

type ContractTree = BTreeMap<String, Vec<InterfaceContract>>;

struct ErrorProbe {
    message: &'static str,
}

#[zbus::interface(name = "io.github.cliffthelin.ErrorProbe1")]
impl ErrorProbe {
    fn representative_failure(&self) -> Result<(), GuardianDbusError> {
        Err(GuardianErrorCategory::ProviderChanged.with_message(self.message))
    }
}

fn with_private_connection(test: impl FnOnce(&Connection)) {
    let bus = PrivateSessionBus::launch().expect("private D-Bus must launch");
    let connection = connection::Builder::address(bus.address())
        .expect("parse private D-Bus address")
        .build()
        .expect("connect to private D-Bus");
    test(&connection);
}

fn introspect(connection: &Connection, path: &str) -> String {
    let proxy = Proxy::new(
        connection,
        connection.unique_name().expect("unique bus name").as_str(),
        path,
        "org.freedesktop.DBus.Introspectable",
    )
    .expect("create introspection proxy");
    proxy
        .call("Introspect", &())
        .expect("live introspection works")
}

fn required_attribute(node: Node<'_, '_>, attribute: &str) -> String {
    node.attribute(attribute)
        .unwrap_or_else(|| panic!("{} requires {attribute}", node.tag_name().name()))
        .to_owned()
}

fn annotation_contracts(node: Node<'_, '_>) -> Vec<AnnotationContract> {
    let mut annotations = node
        .children()
        .filter(|child| child.has_tag_name("annotation"))
        .map(|annotation| AnnotationContract {
            name: required_attribute(annotation, "name"),
            value: required_attribute(annotation, "value"),
        })
        .collect::<Vec<_>>();
    annotations.sort();
    annotations
}

fn argument_contract(node: Node<'_, '_>) -> ArgumentContract {
    ArgumentContract {
        name: node.attribute("name").map(str::to_owned),
        signature: required_attribute(node, "type"),
        direction: node.attribute("direction").map(str::to_owned),
        annotations: annotation_contracts(node),
    }
}

fn guardian_interfaces(node: Node<'_, '_>) -> Vec<InterfaceContract> {
    let mut interfaces = node
        .children()
        .filter(|child| child.has_tag_name("interface"))
        .filter(|interface| {
            interface
                .attribute("name")
                .is_some_and(|name| name.starts_with(GUARDIAN_INTERFACE_PREFIX))
        })
        .map(|interface| {
            let mut methods = interface
                .children()
                .filter(|child| child.has_tag_name("method"))
                .map(|method| MethodContract {
                    name: required_attribute(method, "name"),
                    arguments: method
                        .children()
                        .filter(|child| child.has_tag_name("arg"))
                        .map(argument_contract)
                        .collect(),
                    annotations: annotation_contracts(method),
                })
                .collect::<Vec<_>>();
            let mut properties = interface
                .children()
                .filter(|child| child.has_tag_name("property"))
                .map(|property| PropertyContract {
                    name: required_attribute(property, "name"),
                    signature: required_attribute(property, "type"),
                    access: required_attribute(property, "access"),
                    annotations: annotation_contracts(property),
                })
                .collect::<Vec<_>>();
            let mut signals = interface
                .children()
                .filter(|child| child.has_tag_name("signal"))
                .map(|signal| SignalContract {
                    name: required_attribute(signal, "name"),
                    arguments: signal
                        .children()
                        .filter(|child| child.has_tag_name("arg"))
                        .map(argument_contract)
                        .collect(),
                    annotations: annotation_contracts(signal),
                })
                .collect::<Vec<_>>();
            methods.sort();
            properties.sort();
            signals.sort();
            InterfaceContract {
                name: required_attribute(interface, "name"),
                methods,
                properties,
                signals,
                annotations: annotation_contracts(interface),
            }
        })
        .collect::<Vec<_>>();
    interfaces.sort();
    interfaces
}

fn child_path(parent: &str, child: &str) -> String {
    if child.starts_with('/') {
        child.to_owned()
    } else {
        format!("{}/{child}", parent.trim_end_matches('/'))
    }
}

fn parse_expected_node(node: Node<'_, '_>, path: &str, tree: &mut ContractTree) {
    tree.insert(path.to_owned(), guardian_interfaces(node));
    for child in node.children().filter(|child| child.has_tag_name("node")) {
        let name = required_attribute(child, "name");
        let path = child_path(path, &name);
        parse_expected_node(child, &path, tree);
    }
}

fn expected_contract_tree() -> ContractTree {
    let document = Document::parse(EXPECTED_XML).expect("expected XML must parse");
    let root = document.root_element();
    assert_eq!(root.attribute("name"), Some(OBJECT_PATH));
    let mut tree = ContractTree::new();
    parse_expected_node(root, OBJECT_PATH, &mut tree);
    tree
}

fn introspection_node_xml(xml: &str) -> &str {
    &xml[xml
        .find("<node")
        .expect("introspection XML must contain a root node")..]
}

fn inspect_live_node(
    connection: &Connection,
    path: &str,
    visited: &mut HashSet<String>,
    tree: &mut ContractTree,
) {
    assert!(
        visited.insert(path.to_owned()),
        "object-tree cycle at {path}"
    );
    let xml = introspect(connection, path);
    let document =
        Document::parse(introspection_node_xml(&xml)).expect("live introspection XML must parse");
    let root = document.root_element();
    tree.insert(path.to_owned(), guardian_interfaces(root));
    for child in root.children().filter(|child| child.has_tag_name("node")) {
        let name = required_attribute(child, "name");
        inspect_live_node(connection, &child_path(path, &name), visited, tree);
    }
}

fn live_contract_tree(connection: &Connection) -> ContractTree {
    let mut tree = ContractTree::new();
    inspect_live_node(connection, OBJECT_PATH, &mut HashSet::new(), &mut tree);
    tree
}

fn method_error_name(error: &zbus::Error) -> &str {
    match error {
        zbus::Error::MethodError(name, _, _) => name.as_str(),
        other => panic!("expected structured D-Bus method error, got {other:?}"),
    }
}

fn guardian_method_surface(tree: ContractTree) -> Vec<QualifiedMethodContract> {
    let mut surface = Vec::new();
    for (object_path, interfaces) in tree {
        for interface in interfaces {
            for method in interface.methods {
                surface.push(QualifiedMethodContract {
                    object_path: object_path.clone(),
                    interface_name: interface.name.clone(),
                    method,
                });
            }
        }
    }
    surface.sort();
    surface
}

fn approved_g0_method(name: &str) -> QualifiedMethodContract {
    QualifiedMethodContract {
        object_path: OBJECT_PATH.to_owned(),
        interface_name: INTERFACE_NAME.to_owned(),
        method: MethodContract {
            name: name.to_owned(),
            arguments: vec![ArgumentContract {
                name: None,
                signature: "s".to_owned(),
                direction: Some("out".to_owned()),
                annotations: Vec::new(),
            }],
            annotations: Vec::new(),
        },
    }
}

fn approved_g0_method_surface() -> Vec<QualifiedMethodContract> {
    let mut methods = vec![
        approved_g0_method("ContractVersion"),
        approved_g0_method("ServiceState"),
    ];
    methods.sort();
    methods
}

fn assert_p0_dbus_001_live_export_matches_complete_expected_contract(connection: &Connection) {
    assert_annotation_parser_preserves_presence_and_value();
    assert_eq!(live_contract_tree(connection), expected_contract_tree());
}

fn assert_p0_dbus_002_every_guardian_interface_has_terminal_major_one(connection: &Connection) {
    let tree = live_contract_tree(connection);
    let interfaces = tree.values().flatten().collect::<Vec<_>>();
    assert!(!interfaces.is_empty(), "Guardian must export an interface");
    for interface in interfaces {
        let terminal_component = interface.name.rsplit('.').next().unwrap();
        let first_digit = terminal_component
            .find(|character: char| character.is_ascii_digit())
            .expect("Guardian interface must end in an explicit major");
        assert_eq!(&terminal_component[first_digit..], "1");
        assert!(first_digit > 0, "major requires a named interface stem");
    }
}

fn assert_p0_dbus_003_entire_live_tree_has_exact_g0_method_allowlist(connection: &Connection) {
    assert_eq!(
        guardian_method_surface(live_contract_tree(connection)),
        approved_g0_method_surface()
    );
}

fn assert_p0_dbus_004_representative_typed_error_crosses_private_bus(connection: &Connection) {
    let proxy = Proxy::new(
        connection,
        connection.unique_name().unwrap().as_str(),
        ERROR_PROBE_PATH,
        ERROR_PROBE_INTERFACE,
    )
    .unwrap();
    let error = proxy
        .call::<_, _, ()>("RepresentativeFailure", &())
        .unwrap_err();
    assert_eq!(
        method_error_name(&error),
        "io.github.cliffthelin.Guardian1.Error.ProviderChanged"
    );
}

fn assert_p0_dbus_005_unknown_method_is_structured_and_service_survives(connection: &Connection) {
    let proxy = Proxy::new(
        connection,
        connection.unique_name().unwrap().as_str(),
        OBJECT_PATH,
        INTERFACE_NAME,
    )
    .unwrap();
    let error = proxy
        .call::<_, _, ()>("DefinitelyUnknown", &())
        .unwrap_err();
    assert_eq!(
        method_error_name(&error),
        "org.freedesktop.DBus.Error.UnknownMethod"
    );
    let version: String = proxy.call("ContractVersion", &()).unwrap();
    assert_eq!(version, "1.0");
}

fn panic_message(payload: &(dyn Any + Send)) -> String {
    if let Some(message) = payload.downcast_ref::<String>() {
        message.clone()
    } else if let Some(message) = payload.downcast_ref::<&str>() {
        (*message).to_owned()
    } else {
        "non-string panic payload".to_owned()
    }
}

fn record_contract_check(failures: &mut Vec<String>, contract_id: &str, check: impl FnOnce()) {
    if let Err(payload) = catch_unwind(AssertUnwindSafe(check)) {
        failures.push(format!(
            "{contract_id}: {}",
            panic_message(payload.as_ref())
        ));
    }
}

#[test]
fn p0_dbus_001_through_005_live_private_bus_contract_suite() {
    with_private_connection(|connection| {
        connection
            .object_server()
            .at(OBJECT_PATH, GuardianContract::default())
            .expect("register Guardian contract object");
        connection
            .object_server()
            .at(
                ERROR_PROBE_PATH,
                ErrorProbe {
                    message: "provider contract changed",
                },
            )
            .expect("register test-only typed error probe");

        let mut failures = Vec::new();
        record_contract_check(&mut failures, "P0-DBUS-001", || {
            assert_p0_dbus_001_live_export_matches_complete_expected_contract(connection);
        });
        record_contract_check(&mut failures, "P0-DBUS-002", || {
            assert_p0_dbus_002_every_guardian_interface_has_terminal_major_one(connection);
        });
        record_contract_check(&mut failures, "P0-DBUS-003", || {
            assert_p0_dbus_003_entire_live_tree_has_exact_g0_method_allowlist(connection);
        });
        record_contract_check(&mut failures, "P0-DBUS-004", || {
            assert_p0_dbus_004_representative_typed_error_crosses_private_bus(connection);
        });
        record_contract_check(&mut failures, "P0-DBUS-005", || {
            assert_p0_dbus_005_unknown_method_is_structured_and_service_survives(connection);
        });
        assert!(
            failures.is_empty(),
            "G0 private-bus contract failures:\n{}",
            failures.join("\n")
        );
    });
}

fn assert_annotation_parser_preserves_presence_and_value() {
    let without =
        Document::parse(r#"<node><interface name="io.github.cliffthelin.Guardian1"/></node>"#)
            .unwrap();
    let first = Document::parse(
        r#"<node><interface name="io.github.cliffthelin.Guardian1"><annotation name="org.example.Contract" value="first"/></interface></node>"#,
    )
    .unwrap();
    let changed = Document::parse(
        r#"<node><interface name="io.github.cliffthelin.Guardian1"><annotation name="org.example.Contract" value="changed"/></interface></node>"#,
    )
    .unwrap();

    assert_ne!(
        guardian_interfaces(without.root_element()),
        guardian_interfaces(first.root_element())
    );
    assert_ne!(
        guardian_interfaces(first.root_element()),
        guardian_interfaces(changed.root_element())
    );
}
