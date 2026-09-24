"""BoundedEventLog - a repeated condition must consume bounded
resources regardless of how long it continues. Proves total emitted
records stay small even across 100,000+ identical occurrences."""
import bounded_log


def test_first_occurrence_is_recorded_in_full():
    log = bounded_log.BoundedEventLog(early_repetitions=3)
    log.record("sig-a", detail={"x": 1})
    assert len(log.records) == 1
    assert log.records[0]["kind"] == "occurrence"
    assert log.records[0]["detail"] == {"x": 1}


def test_early_repetitions_are_recorded_then_suppressed():
    log = bounded_log.BoundedEventLog(early_repetitions=3, summary_interval=0)
    for _ in range(10):
        log.record("sig-a")
    # 1 occurrence + 3 early repetitions = 4 records; the remaining 6
    # calls are suppressed (summary_interval=0 disables periodic
    # summaries for this test, isolating the early-repetition bound).
    assert len(log.records) == 4
    assert log.count("sig-a") == 10


def test_periodic_summary_appears_at_the_configured_interval():
    log = bounded_log.BoundedEventLog(early_repetitions=2, summary_interval=100)
    for _ in range(250):
        log.record("sig-a")
    kinds = [r["kind"] for r in log.records]
    assert kinds.count("periodic_summary") == 2  # at 100 and 200
    assert log.count("sig-a") == 250


def test_100000_repeated_identical_failures_produce_bounded_records():
    """The concrete requirement: a condition repeating 100,000+ times
    must not produce anywhere close to 100,000 log records."""
    log = bounded_log.BoundedEventLog(early_repetitions=3, summary_interval=1000)
    for _ in range(100_000):
        log.record("renderer_negative_latency")
    assert log.count("renderer_negative_latency") == 100_000
    # 1 + 3 early + one periodic summary every 1000 occurrences (100 of them)
    assert len(log.records) < 200
    assert len(log.records) == 1 + 3 + 100


def test_finalize_gives_exactly_one_summary_per_signature_regardless_of_count():
    log = bounded_log.BoundedEventLog()
    for _ in range(100_000):
        log.record("sig-a")
    for _ in range(50):
        log.record("sig-b")
    summaries = log.finalize()
    assert len(summaries) == 2
    by_sig = {s["event_signature"]: s for s in summaries}
    assert by_sig["sig-a"]["count"] == 100_000
    assert by_sig["sig-b"]["count"] == 50
    assert by_sig["sig-a"]["suppressed"] > 0
    assert by_sig["sig-a"]["examples_retained"] <= 1 + log.early_repetitions


def test_distinct_signatures_are_tracked_independently():
    log = bounded_log.BoundedEventLog(early_repetitions=1, summary_interval=0)
    for _ in range(5):
        log.record("sig-a")
        log.record("sig-b")
    assert log.count("sig-a") == 5
    assert log.count("sig-b") == 5
    # 2 records per signature (occurrence + 1 early repetition) x 2 signatures
    assert len(log.records) == 4


def test_total_emitted_records_property_matches_records_length():
    log = bounded_log.BoundedEventLog()
    for _ in range(1000):
        log.record("sig-a")
    assert log.total_emitted_records == len(log.records)


def test_unknown_signature_has_zero_count():
    log = bounded_log.BoundedEventLog()
    assert log.count("never-seen") == 0


def test_finalize_is_idempotent_and_read_only():
    log = bounded_log.BoundedEventLog()
    log.record("sig-a")
    first = log.finalize()
    second = log.finalize()
    assert first == second
