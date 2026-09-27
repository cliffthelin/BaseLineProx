//! PSI (Pressure Stall Information) fixture/parsing model (TDD contract
//! §20; G5 handoff §6). Fixture-driven and deterministic at this gate --
//! no real `/proc/pressure/*` read exists here. The real kernel-backed
//! reader that feeds this model live data is G8's `P1-PSI-*` job.
//!
//! `/proc/pressure/{cpu,memory,io}` format: a `some` line, and (for
//! memory/io) a `full` line, each carrying `avg10=`/`avg60=`/`avg300=`/
//! `total=` fields. CPU legitimately has no `full` line on some kernels --
//! that is a distinct, non-error state for CPU specifically, not a parse
//! failure.

use std::fmt;

/// One `some`/`full` line's parsed fields.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PsiLine {
    pub avg10: f64,
    pub avg60: f64,
    pub avg300: f64,
    pub total: u64,
}

/// Which `/proc/pressure/*` resource a line/snapshot belongs to.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum PsiResourceKind {
    Cpu,
    Memory,
    Io,
}

/// A parsed resource file. `full` is legitimately absent for CPU on some
/// kernels -- this is a real, distinct state, never an error.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PsiResource {
    pub some: PsiLine,
    pub full: Option<PsiLine>,
}

/// A malformed PSI line -- a real typed error, never silently treated as
/// "no pressure" (fail-open is exactly the defect this type prevents).
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PsiParseError(pub String);

impl fmt::Display for PsiParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "malformed PSI input: {}", self.0)
    }
}

impl std::error::Error for PsiParseError {}

/// The PSI source's presence, kept structurally distinct from a parse
/// failure of *present* text (§6.2). `Unavailable` is reused as a
/// locally-scoped two-state fit rather than G3's five-variant
/// `Availability`: raw PSI text is either present (parseable or
/// malformed) or genuinely absent -- `Degraded`/`Unsupported`/`Unknown`
/// describe capability-level states this narrower question doesn't have.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum PsiReading {
    Present(PsiResource),
    Unavailable,
}

fn parse_line(text: &str) -> Result<PsiLine, PsiParseError> {
    let mut avg10 = None;
    let mut avg60 = None;
    let mut avg300 = None;
    let mut total = None;

    for field in text.split_whitespace().skip(1) {
        let (key, value) = field
            .split_once('=')
            .ok_or_else(|| PsiParseError(format!("malformed field (no '='): {field}")))?;
        match key {
            "avg10" => {
                avg10 =
                    Some(value.parse::<f64>().map_err(|_| {
                        PsiParseError(format!("avg10 is not a valid float: {value}"))
                    })?);
            }
            "avg60" => {
                avg60 =
                    Some(value.parse::<f64>().map_err(|_| {
                        PsiParseError(format!("avg60 is not a valid float: {value}"))
                    })?);
            }
            "avg300" => {
                avg300 =
                    Some(value.parse::<f64>().map_err(|_| {
                        PsiParseError(format!("avg300 is not a valid float: {value}"))
                    })?);
            }
            "total" => {
                total = Some(value.parse::<u64>().map_err(|_| {
                    PsiParseError(format!("total is not a valid integer: {value}"))
                })?);
            }
            other => return Err(PsiParseError(format!("unrecognized field key: {other}"))),
        }
    }

    Ok(PsiLine {
        avg10: avg10.ok_or_else(|| PsiParseError("missing avg10".to_owned()))?,
        avg60: avg60.ok_or_else(|| PsiParseError("missing avg60".to_owned()))?,
        avg300: avg300.ok_or_else(|| PsiParseError("missing avg300".to_owned()))?,
        total: total.ok_or_else(|| PsiParseError("missing total".to_owned()))?,
    })
}

/// Parses one already-in-memory `/proc/pressure/<resource>` file's
/// contents. Never touches the filesystem -- the real read is a thin,
/// separately-testable G8 wrapper around this function.
///
/// # Errors
///
/// Returns [`PsiParseError`] for any line that is not a recognized
/// `some`/`full` line with valid fields. A missing `full` line is *not*
/// an error for any resource kind -- see module docs.
pub fn parse_resource(text: &str, kind: PsiResourceKind) -> Result<PsiResource, PsiParseError> {
    let mut some = None;
    let mut full = None;

    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        if let Some(rest) = trimmed.strip_prefix("some") {
            some = Some(parse_line(&format!("some{rest}"))?);
        } else if let Some(rest) = trimmed.strip_prefix("full") {
            full = Some(parse_line(&format!("full{rest}"))?);
        } else {
            return Err(PsiParseError(format!(
                "unrecognized PSI line for {kind:?} (expected 'some'/'full'): {trimmed}"
            )));
        }
    }

    let some =
        some.ok_or_else(|| PsiParseError(format!("{kind:?}: missing required 'some' line")))?;
    // A missing 'full' line is a legitimate, distinct state for every
    // resource kind here (documented CPU behavior; leniently extended to
    // memory/io since the contract only requires the CPU case be
    // explicitly non-error, not that others be strict) -- never an error.
    Ok(PsiResource { some, full })
}

/// Reads PSI text that may be entirely absent (source unavailable) --
/// `None` becomes [`PsiReading::Unavailable`], never a silent "zero
/// pressure" default. `Some(text)` is parsed for real and surfaces a real
/// [`PsiParseError`] on malformed content.
///
/// # Errors
///
/// See [`parse_resource`].
pub fn read_resource(
    text: Option<&str>,
    kind: PsiResourceKind,
) -> Result<PsiReading, PsiParseError> {
    match text {
        None => Ok(PsiReading::Unavailable),
        Some(text) => parse_resource(text, kind).map(PsiReading::Present),
    }
}

/// A minimal, dependency-free classification of raw pressure into a
/// discrete severity the Diagnostic Budget Manager can veto on. Kept
/// deliberately coarse (three levels) -- this gate's job is proving the
/// veto/decision *model* works, not tuning production thresholds.
#[derive(Clone, Copy, Debug, Eq, PartialEq, PartialOrd, Ord)]
pub enum PressureSeverity {
    Nominal,
    Elevated,
    Critical,
}

/// `avg10` thresholds (percent stalled, matching the kernel's own PSI
/// units) above which pressure is considered `Elevated`/`Critical`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SeverityThresholds {
    pub elevated_avg10: f64,
    pub critical_avg10: f64,
}

impl SeverityThresholds {
    #[must_use]
    pub const fn new(elevated_avg10: f64, critical_avg10: f64) -> Self {
        Self {
            elevated_avg10,
            critical_avg10,
        }
    }
}

/// Classifies one `some` line's `avg10` against `thresholds`.
#[must_use]
pub fn classify(line: PsiLine, thresholds: SeverityThresholds) -> PressureSeverity {
    if line.avg10 >= thresholds.critical_avg10 {
        PressureSeverity::Critical
    } else if line.avg10 >= thresholds.elevated_avg10 {
        PressureSeverity::Elevated
    } else {
        PressureSeverity::Nominal
    }
}

/// A real, forced non-monotonicity of `total=` across successive samples
/// for the same resource -- required to be detectable, not merely
/// assumed true by construction (§20 "counter monotonicity").
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NonMonotonicTotal {
    pub previous: u64,
    pub observed: u64,
}

impl fmt::Display for NonMonotonicTotal {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "PSI total counter went backward: {} -> {}",
            self.previous, self.observed
        )
    }
}

impl std::error::Error for NonMonotonicTotal {}

/// A thin sequencing wrapper proving `total=` monotonicity across
/// successive samples for one resource -- not an assumption, a checked
/// invariant.
#[derive(Clone, Copy, Debug, Default)]
pub struct MonotonicTotalCheck {
    last: Option<u64>,
}

impl MonotonicTotalCheck {
    #[must_use]
    pub const fn new() -> Self {
        Self { last: None }
    }

    /// # Errors
    ///
    /// Returns [`NonMonotonicTotal`] if `total` is strictly less than the
    /// previously observed value.
    pub fn observe(&mut self, total: u64) -> Result<(), NonMonotonicTotal> {
        if let Some(previous) = self.last {
            if total < previous {
                return Err(NonMonotonicTotal {
                    previous,
                    observed: total,
                });
            }
        }
        self.last = Some(total);
        Ok(())
    }
}

/// A detected transition across the monitor's configured threshold.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ThresholdEvent {
    pub resource: PsiResourceKind,
    pub from: PressureSeverity,
    pub to: PressureSeverity,
}

/// A push-based (never polling) threshold monitor: the only way to learn
/// anything from it is to call [`ThresholdMonitor::observe`] with a
/// caller-supplied severity -- there is no method that spins or blocks
/// waiting for a real kernel event, so "no busy-loop when there is no
/// event" holds structurally, by the shape of this API, not by timing
/// behavior this gate cannot test.
#[derive(Clone, Copy, Debug)]
pub struct ThresholdMonitor {
    resource: PsiResourceKind,
    threshold: PressureSeverity,
    last: Option<PressureSeverity>,
    torn_down: bool,
}

impl ThresholdMonitor {
    #[must_use]
    pub const fn new(resource: PsiResourceKind, threshold: PressureSeverity) -> Self {
        Self {
            resource,
            threshold,
            last: None,
            torn_down: false,
        }
    }

    /// Feeds one fresh severity sample. Returns `Some(event)` only on a
    /// genuine crossing of `threshold` (below -> at/above, or the
    /// reverse) -- never on every call, and never after teardown.
    pub fn observe(&mut self, current: PressureSeverity) -> Option<ThresholdEvent> {
        if self.torn_down {
            return None;
        }
        let previous = self.last.replace(current)?;
        let was_above = previous >= self.threshold;
        let is_above = current >= self.threshold;
        if was_above == is_above {
            return None;
        }
        Some(ThresholdEvent {
            resource: self.resource,
            from: previous,
            to: current,
        })
    }

    /// Explicit stop path -- after this, [`ThresholdMonitor::observe`]
    /// never produces another event, proven by a dedicated test rather
    /// than assumed correct because the type could implement `Drop`.
    pub fn teardown(&mut self) {
        self.torn_down = true;
    }

    #[must_use]
    pub const fn is_torn_down(&self) -> bool {
        self.torn_down
    }
}
