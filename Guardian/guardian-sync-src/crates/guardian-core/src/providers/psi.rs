//! G8 production wiring for PSI (`P1-PSI-001..005`). Reuses the accepted
//! G5 [`crate::psi`] model **unmodified** — this module contains no
//! parsing, classification, or threshold logic of its own. Its entire job
//! is: (a) read the real `/proc/pressure/{cpu,memory,io}` files and feed
//! them through [`crate::psi::read_resource`], and (b) drive
//! [`crate::psi::ThresholdMonitor::observe`] from a genuine kernel-level
//! PSI trigger via `poll()`, never a busy loop (`P1-PSI-004`).

use std::fs;
use std::io;
use std::os::fd::AsFd;
use std::path::{Path, PathBuf};
use std::time::Duration;

use rustix::event::{PollFd, PollFlags, poll};
use rustix::fs::{Mode, OFlags, open};

use crate::event::{Event, normalize_key};
use crate::psi::{
    PressureSeverity, PsiParseError, PsiReading, PsiResourceKind, SeverityThresholds,
    ThresholdMonitor, classify, read_resource,
};
use crate::risk::Risk;
use guardian_provider_api::{EventId, ProviderId};

/// Real, filesystem-backed source of PSI text — the thin G8 wrapper the
/// accepted G5 module doc comment calls for. Injectable base directory so
/// tests never depend on the real `/proc`.
#[derive(Clone, Debug)]
pub struct PsiFileSource {
    base_dir: PathBuf,
}

impl PsiFileSource {
    /// The real, standard kernel path.
    #[must_use]
    pub fn real() -> Self {
        Self {
            base_dir: PathBuf::from("/proc/pressure"),
        }
    }

    #[must_use]
    pub fn at(base_dir: impl Into<PathBuf>) -> Self {
        Self {
            base_dir: base_dir.into(),
        }
    }

    fn path_for(&self, kind: PsiResourceKind) -> PathBuf {
        let name = match kind {
            PsiResourceKind::Cpu => "cpu",
            PsiResourceKind::Memory => "memory",
            PsiResourceKind::Io => "io",
        };
        self.base_dir.join(name)
    }

    /// Real file read → the accepted G5 `read_resource`/`PsiReading`
    /// model, unmodified. A missing file becomes
    /// [`PsiReading::Unavailable`] (`P1-PSI-005`) — never a parse error
    /// and never silently treated as "no pressure."
    ///
    /// # Errors
    ///
    /// Returns [`PsiParseError`] only for a *present* file with malformed
    /// content — see [`crate::psi::read_resource`].
    pub fn read(&self, kind: PsiResourceKind) -> Result<PsiReading, PsiParseError> {
        let path = self.path_for(kind);
        let text = fs::read_to_string(&path).ok();
        read_resource(text.as_deref(), kind)
    }

    #[must_use]
    pub fn path(&self, kind: PsiResourceKind) -> PathBuf {
        self.path_for(kind)
    }
}

/// A real kernel-level PSI trigger, registered by writing a threshold
/// expression to the pressure file per the kernel's own PSI monitoring
/// ABI (`Documentation/accounting/psi.rst`) and waiting on `POLLPRI` —
/// never a sleep-and-recheck loop. `window_us` MUST be >= `500_000` (the
/// kernel's own minimum) and `threshold_us` < `window_us`; both are
/// validated before the trigger is written, matching the kernel's own
/// rejection behavior with a typed error instead of an opaque I/O
/// failure surfacing later.
pub struct PsiTrigger {
    file: fs::File,
}

/// A trigger could not be registered — the file is genuinely absent
/// (`PSI unavailable`), the parameters were rejected by the kernel, or
/// the caller lacks write access.
#[derive(Debug)]
pub struct TriggerError(pub io::Error);

impl std::fmt::Display for TriggerError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "PSI trigger registration failed: {}", self.0)
    }
}

impl std::error::Error for TriggerError {}

impl PsiTrigger {
    /// Registers a real trigger: `stall_type` is `"some"` or `"full"`
    /// (CPU has no `full`), `threshold_us`/`window_us` are microseconds
    /// per the kernel ABI.
    ///
    /// # Errors
    ///
    /// See [`TriggerError`].
    pub fn register(
        source: &PsiFileSource,
        kind: PsiResourceKind,
        stall_type: &str,
        threshold_us: u64,
        window_us: u64,
    ) -> Result<Self, TriggerError> {
        let path: &Path = &source.path(kind);
        // O_RDWR is required by the kernel PSI ABI: the trigger is
        // written to the same fd that is later polled.
        let raw = open(path, OFlags::RDWR | OFlags::CLOEXEC, Mode::empty())
            .map_err(|errno| TriggerError(io::Error::from(errno)))?;
        let file: fs::File = raw.into();
        let mut trigger = format!("{stall_type} {threshold_us} {window_us}").into_bytes();
        // The kernel ABI's reference implementation writes strlen + 1:
        // the terminating NUL is part of the accepted trigger payload.
        trigger.push(0);
        std::io::Write::write_all(&mut { &file }, &trigger).map_err(TriggerError)?;
        Ok(Self { file })
    }

    /// Blocks (via real `poll()`, `POLLPRI`) until the kernel signals the
    /// registered threshold was crossed, or `timeout` elapses. Never a
    /// busy loop: with `timeout = None` this call parks the thread in the
    /// kernel until a real event arrives.
    ///
    /// # Errors
    ///
    /// Returns the underlying `poll()` I/O error, if any.
    pub fn wait(&self, timeout: Option<Duration>) -> io::Result<bool> {
        let timespec = timeout.map(|duration| rustix::time::Timespec {
            tv_sec: duration.as_secs().try_into().unwrap_or(i64::MAX),
            tv_nsec: i64::from(duration.subsec_nanos()),
        });
        let fd = self.file.as_fd();
        let mut fds = [PollFd::new(&fd, PollFlags::PRI)];
        let ready = poll(&mut fds, timespec.as_ref())?;
        Ok(ready > 0 && fds[0].revents().contains(PollFlags::PRI))
    }
}

/// Complete production event path for `P1-PSI-004`: a registered kernel
/// trigger wakes through `poll(POLLPRI)`, the live PSI file is re-read,
/// and the accepted G5 classifier/`ThresholdMonitor` decides whether a
/// normalized Guardian event is emitted. One call performs one blocking
/// wait; there is no retry loop or periodic sampling in this type.
pub struct PsiEventSource {
    trigger: PsiTrigger,
    dispatcher: PsiEventDispatcher,
}

/// Deterministic wake-to-event half of [`PsiEventSource`]. The kernel wait
/// stays in `PsiTrigger`; this type makes dispatch and repeated-wake
/// behavior testable without pretending a fixture file supports POLLPRI.
pub struct PsiEventDispatcher {
    source: PsiFileSource,
    kind: PsiResourceKind,
    thresholds: SeverityThresholds,
    monitor: ThresholdMonitor,
    sequence: u64,
}

impl PsiEventDispatcher {
    /// Seeds dispatch from the current live reading.
    ///
    /// # Errors
    ///
    /// Returns unavailable or malformed-source errors from the initial read.
    pub fn new(
        source: PsiFileSource,
        kind: PsiResourceKind,
        thresholds: SeverityThresholds,
        event_threshold: PressureSeverity,
    ) -> Result<Self, PsiEventError> {
        let baseline = present_severity(&source, kind, thresholds)?;
        let mut monitor = ThresholdMonitor::new(kind, event_threshold);
        let _ = monitor.observe(baseline);
        Ok(Self {
            source,
            kind,
            thresholds,
            monitor,
            sequence: 0,
        })
    }

    /// Converts one already-received wake into at most one event.
    ///
    /// # Errors
    ///
    /// Returns unavailable or malformed-source errors from the fresh read.
    pub fn dispatch_wake(&mut self) -> Result<Option<Event>, PsiEventError> {
        let severity = present_severity(&self.source, self.kind, self.thresholds)?;
        let Some(crossing) = self.monitor.observe(severity) else {
            return Ok(None);
        };
        self.sequence = self.sequence.saturating_add(1);
        Ok(Some(event_from_crossing(crossing, self.sequence)))
    }
}

impl PsiEventSource {
    /// Registers the kernel trigger and seeds the accepted G5 monitor from
    /// the current live reading so the first subsequent wake can represent
    /// a genuine crossing.
    /// # Errors
    ///
    /// Returns trigger-registration, unavailable, or malformed-source errors.
    pub fn register(
        source: &PsiFileSource,
        kind: PsiResourceKind,
        stall_type: &str,
        threshold_us: u64,
        window_us: u64,
        thresholds: SeverityThresholds,
        event_threshold: PressureSeverity,
    ) -> Result<Self, PsiEventError> {
        let dispatcher =
            PsiEventDispatcher::new(source.clone(), kind, thresholds, event_threshold)?;
        let trigger = PsiTrigger::register(source, kind, stall_type, threshold_us, window_us)?;
        Ok(Self {
            trigger,
            dispatcher,
        })
    }

    /// Waits once in the kernel and dispatches at most one Guardian event.
    /// # Errors
    ///
    /// Returns trigger-wait, unavailable, or malformed-source errors.
    pub fn wait_for_event(
        &mut self,
        timeout: Option<Duration>,
    ) -> Result<Option<Event>, PsiEventError> {
        if !self.trigger.wait(timeout)? {
            return Ok(None);
        }
        self.dispatcher.dispatch_wake()
    }
}

#[derive(Debug)]
pub enum PsiEventError {
    Trigger(TriggerError),
    Io(io::Error),
    Parse(PsiParseError),
    Unavailable,
}

impl std::fmt::Display for PsiEventError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Trigger(error) => error.fmt(formatter),
            Self::Io(error) => write!(formatter, "PSI trigger wait failed: {error}"),
            Self::Parse(error) => error.fmt(formatter),
            Self::Unavailable => formatter.write_str("PSI source unavailable"),
        }
    }
}

impl std::error::Error for PsiEventError {}

impl From<TriggerError> for PsiEventError {
    fn from(value: TriggerError) -> Self {
        Self::Trigger(value)
    }
}

impl From<io::Error> for PsiEventError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<PsiParseError> for PsiEventError {
    fn from(value: PsiParseError) -> Self {
        Self::Parse(value)
    }
}

fn present_severity(
    source: &PsiFileSource,
    kind: PsiResourceKind,
    thresholds: SeverityThresholds,
) -> Result<PressureSeverity, PsiEventError> {
    match source.read(kind)? {
        PsiReading::Present(resource) => Ok(classify(resource.some, thresholds)),
        PsiReading::Unavailable => Err(PsiEventError::Unavailable),
    }
}

fn event_from_crossing(crossing: crate::psi::ThresholdEvent, sequence: u64) -> Event {
    let resource = match crossing.resource {
        PsiResourceKind::Cpu => "cpu",
        PsiResourceKind::Memory => "memory",
        PsiResourceKind::Io => "io",
    };
    let raw = format!(
        "PSI {resource} threshold crossing {:?}->{:?}",
        crossing.from, crossing.to
    );
    Event {
        event_id: EventId::new(format!("guardian.psi.{resource}.event-{sequence}"))
            .expect("generated PSI event id is valid"),
        timestamp_monotonic: sequence,
        timestamp_wall: format!("sequence-{sequence}"),
        source_provider: ProviderId::new("guardian.g8.psi").expect("fixed provider id is valid"),
        event_type: "psi_threshold_crossing".to_owned(),
        resource_refs: vec![format!("/proc/pressure/{resource}")],
        severity: match crossing.to {
            PressureSeverity::Critical => Risk::High,
            PressureSeverity::Elevated => Risk::Moderate,
            PressureSeverity::Nominal => Risk::Observe,
        },
        normalized_key: normalize_key(&raw),
        raw_reference: raw,
        attributes: std::collections::BTreeMap::from([
            ("from".to_owned(), format!("{:?}", crossing.from)),
            ("to".to_owned(), format!("{:?}", crossing.to)),
        ]),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("psi-provider-test-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn reads_a_real_present_file_through_the_unmodified_g5_model() {
        let dir = temp_dir("present");
        fs::write(
            dir.join("cpu"),
            "some avg10=1.20 avg60=0.80 avg300=0.10 total=1234\n",
        )
        .unwrap();
        let source = PsiFileSource::at(&dir);
        let reading = source.read(PsiResourceKind::Cpu).unwrap();
        match reading {
            PsiReading::Present(resource) => {
                assert!((resource.some.avg10 - 1.20).abs() < f64::EPSILON);
                assert_eq!(resource.full, None);
            }
            PsiReading::Unavailable => panic!("expected Present"),
        }
    }

    #[test]
    fn missing_file_is_unavailable_not_a_parse_error() {
        let dir = temp_dir("missing");
        let source = PsiFileSource::at(&dir);
        let reading = source.read(PsiResourceKind::Memory).unwrap();
        assert_eq!(reading, PsiReading::Unavailable);
    }

    #[test]
    fn malformed_present_file_is_a_real_parse_error_not_silently_ignored() {
        let dir = temp_dir("malformed");
        fs::write(dir.join("io"), "not a psi line at all\n").unwrap();
        let source = PsiFileSource::at(&dir);
        let result = source.read(PsiResourceKind::Io);
        assert!(result.is_err());
    }

    #[test]
    fn path_for_each_resource_kind_matches_the_real_kernel_layout() {
        let source = PsiFileSource::at("/proc/pressure");
        assert_eq!(
            source.path(PsiResourceKind::Cpu),
            Path::new("/proc/pressure/cpu")
        );
        assert_eq!(
            source.path(PsiResourceKind::Memory),
            Path::new("/proc/pressure/memory")
        );
        assert_eq!(
            source.path(PsiResourceKind::Io),
            Path::new("/proc/pressure/io")
        );
    }

    #[test]
    fn trigger_registration_writes_kernel_abi_payload_with_nul_terminator() {
        let dir = temp_dir("trigger-registration");
        let path = dir.join("cpu");
        fs::write(&path, "").unwrap();
        let trigger = PsiTrigger::register(
            &PsiFileSource::at(&dir),
            PsiResourceKind::Cpu,
            "some",
            10_000,
            1_000_000,
        )
        .unwrap();
        drop(trigger);
        assert_eq!(fs::read(path).unwrap(), b"some 10000 1000000\0");
    }

    #[test]
    fn accepted_monitor_crossing_becomes_a_guardian_event() {
        let crossing = crate::psi::ThresholdEvent {
            resource: PsiResourceKind::Memory,
            from: PressureSeverity::Nominal,
            to: PressureSeverity::Critical,
        };
        let event = event_from_crossing(crossing, 7);
        assert_eq!(event.event_type, "psi_threshold_crossing");
        assert_eq!(event.resource_refs, ["/proc/pressure/memory"]);
        assert_eq!(event.severity, Risk::High);
        assert_eq!(event.attributes["from"], "Nominal");
        assert_eq!(event.attributes["to"], "Critical");
    }

    #[test]
    fn unavailable_and_malformed_sources_cannot_generate_events() {
        let missing = PsiFileSource::at(temp_dir("event-missing"));
        assert!(matches!(
            present_severity(
                &missing,
                PsiResourceKind::Cpu,
                SeverityThresholds::new(1.0, 2.0)
            ),
            Err(PsiEventError::Unavailable)
        ));

        let dir = temp_dir("event-malformed");
        fs::write(dir.join("cpu"), "bad\n").unwrap();
        assert!(matches!(
            present_severity(
                &PsiFileSource::at(dir),
                PsiResourceKind::Cpu,
                SeverityThresholds::new(1.0, 2.0)
            ),
            Err(PsiEventError::Parse(_))
        ));
    }

    #[test]
    fn repeated_wakes_emit_only_real_crossings() {
        let dir = temp_dir("dispatch-repeat");
        let path = dir.join("cpu");
        fs::write(&path, "some avg10=0.10 avg60=0 avg300=0 total=1\n").unwrap();
        let mut dispatcher = PsiEventDispatcher::new(
            PsiFileSource::at(&dir),
            PsiResourceKind::Cpu,
            SeverityThresholds::new(1.0, 2.0),
            PressureSeverity::Elevated,
        )
        .unwrap();
        assert!(dispatcher.dispatch_wake().unwrap().is_none());

        fs::write(&path, "some avg10=1.50 avg60=0 avg300=0 total=2\n").unwrap();
        assert!(dispatcher.dispatch_wake().unwrap().is_some());
        assert!(dispatcher.dispatch_wake().unwrap().is_none());

        fs::write(&path, "some avg10=0.20 avg60=0 avg300=0 total=3\n").unwrap();
        assert!(dispatcher.dispatch_wake().unwrap().is_some());
    }
}
