"""How the Kasm VM is doing: parsing the probe, keeping history (setting changes with their real values), and turning it into suggestions with evidence and benefit."""
import subprocess

import pytest

import kasm_telemetry as kt

NOW = 1_800_000_000.0
DAY = kt.DAY
VM = {"memory_mb": 6144, "cpus": 4}


@pytest.fixture
def db(tmp_path):
    return kt.open_db(tmp_path / "telemetry.sqlite")


def put(db, metric, values, start=NOW - 3 * DAY, step=600):
    kt.record_many = None
    for i, v in enumerate(values):
        kt.record(db, {metric: v}, [], now=start + i * step)


def test_the_probe_is_valid_shell_and_only_reads():
    assert subprocess.run(["bash", "-n"], input=kt.PROBE, text=True).returncode == 0
    for writer in ("rm ", "mkfs", "dd ", " > /", "systemctl restart", "docker rm", "docker stop", "chmod"):
        assert writer not in kt.PROBE.replace("2>/dev/null", "").replace(">/dev/null", "")


def test_probe_lines_become_metrics_and_events_and_noise_is_ignored():
    out = ("M mem_avail_pct 42\nM cpu_psi_some10 3.5\nM bad notanumber\nE error service_failed docker.service\n"
           "E warning container_restarts kasm_api restarted 3 times\nE panic x y\nrandom text\nE error kernel i915 firmware load failed with error -2\n")
    metrics, events = kt.parse_probe(out)
    assert metrics == {"mem_avail_pct": 42.0, "cpu_psi_some10": 3.5}
    assert [(e["severity"], e["source"]) for e in events] == [("error", "service_failed"), ("warning", "container_restarts"), ("error", "kernel")]
    assert events[2]["message"] == "i915 firmware load failed with error -2"


def test_secrets_in_a_log_line_are_removed_before_anything_is_stored():
    body = '{"message": "login", "password": "hunter2hunter2", "token": "abc123", "key": "' + "A" * 40 + '"}'
    _, other = kt.parse_probe("E error kernel " + body)                  # a source whose line is kept as written: the secret values are redacted in place
    text = other[0]["message"]
    assert "hunter2" not in text and "abc123" not in text and "A" * 28 not in text and "<redacted>" in text and '"message": "login"' in text
    _, kasm = kt.parse_probe("E error kasm:api " + body)                 # Kasm's own JSON lines are reduced to the message, so those fields are not kept at all
    assert kasm[0]["message"] == "login"
    assert "-----BEGIN RSA PRIVATE KEY-----" not in kt.redact("-----BEGIN RSA PRIVATE KEY----- MIIE...")


def test_the_same_problem_with_different_numbers_is_one_fingerprint():
    a = kt.fingerprint("container_restarts", "kasm_api restarted 3 times")
    assert a == kt.fingerprint("container_restarts", "kasm_api restarted 11 times") and a != kt.fingerprint("container_restarts", "kasm_agent restarted 3 times")
    assert kt.fingerprint("kernel", "I/O error, dev vda, sector 123456") == kt.fingerprint("kernel", "I/O error, dev vda, sector 99")


def test_a_repeating_error_is_one_report_line_with_how_often_and_when_not_many_rows(db):
    for i in range(40):
        kt.record(db, {}, [{"severity": "error", "source": "service_failed", "message": "docker.service"}], now=NOW - i * 3600)
    kt.record(db, {}, [{"severity": "warning", "source": "container_exit", "message": "kasm_guac exited with code 1"}], now=NOW - 60)
    report = kt.error_report(db, NOW - 7 * DAY)
    assert [r["count"] for r in report] == [40, 1] and report[0]["source"] == "service_failed"
    assert report[0]["last"] > report[0]["first"]


def test_a_setting_change_keeps_the_real_old_and_new_values_and_never_a_secrets_value(db):
    kt.record_settings(db, {"log_retention": "7", "hec_token": "OLDSECRET", "same": "x"}, {"log_retention": "14", "hec_token": "NEWSECRET", "same": "x", "first_seen": "y"}, secret_names={"hec_token"}, now=NOW - DAY)
    kt.record_settings(db, {"log_retention": "14"}, {"log_retention": "30"}, now=NOW - 60)
    report = {r["name"]: r for r in kt.setting_report(db, NOW - 7 * DAY)}
    assert report["log_retention"]["changes"] == 2 and (report["log_retention"]["last_old"], report["log_retention"]["last_new"]) == ("14", "30")
    assert report["hec_token"]["secret"] and report["hec_token"]["last_old"] is None and report["hec_token"]["last_new"] is None
    assert "OLDSECRET" not in str(db.execute("SELECT * FROM setting_changes").fetchall()) and "NEWSECRET" not in str(db.execute("SELECT * FROM setting_changes").fetchall())
    assert "same" not in report and report["first_seen"]["last_old"] is None                      # unchanged: no event; a first observation has no old value


def test_nothing_is_suggested_for_a_healthy_vm(db):
    for metric, v in (("mem_avail_pct", 60), ("memory_psi_some10", 0.2), ("cpu_psi_some10", 2), ("load1_per_core", 0.3), ("disk_root_used_pct", 40), ("disk_opt_kasm_used_pct", 20)):
        put(db, metric, [v] * 30)
    assert kt.suggestions(db, VM, now=NOW) == []


def test_memory_pressure_suggests_more_memory_with_the_evidence_and_what_it_buys(db):
    put(db, "mem_avail_pct", [4, 5, 6, 30, 40, 50, 6, 5, 4, 45])
    put(db, "memory_psi_some10", [20, 25, 30, 1, 1, 1, 22, 24, 26, 2])
    got = kt.suggestions(db, VM, now=NOW)
    item = next(s for s in got if s["id"] == "more-memory")
    assert item["action"] == {"memory_mb": 9216} and "6144 MB to 9216 MB" in item["title"] and item["benefit"] and len(item["evidence"]) == 2


def test_a_memory_kill_makes_it_an_error_even_without_pressure_samples(db):
    kt.record(db, {}, [{"severity": "error", "source": "container_oom", "message": "kasm_api was killed for lack of memory"}], now=NOW - 3600)
    item = next(s for s in kt.suggestions(db, VM, now=NOW) if s["id"] == "more-memory")
    assert item["severity"] == "error" and any("memory kills" in e for e in item["evidence"])


def test_cpu_waiting_suggests_one_more_core(db):
    put(db, "cpu_psi_some10", [40] * 20)
    item = next(s for s in kt.suggestions(db, VM, now=NOW) if s["id"] == "more-cores")
    assert item["action"] == {"cpus": 5} and "4 to 5" in item["title"]


def test_a_nearly_full_disk_is_named_and_rated_by_how_full(db):
    put(db, "disk_opt_kasm_used_pct", [90] * 10)
    put(db, "disk_root_used_pct", [97] * 10)
    got = {s["id"]: s for s in kt.suggestions(db, VM, now=NOW)}
    assert got["disk-opt_kasm"]["severity"] == "warning" and got["disk-root"]["severity"] == "error" and "97% full" in got["disk-root"]["title"]


def test_failing_services_drivers_and_kasm_errors_each_become_a_suggestion_to_investigate(db):
    kt.record(db, {}, [{"severity": "error", "source": "service_failed", "message": "docker.service"},
                       {"severity": "error", "source": "kernel", "message": "i915 firmware load failed with error -2"},
                       {"severity": "error", "source": "kasm:api", "message": "database connection refused"}], now=NOW - 600)
    titles = [s["title"] for s in kt.suggestions(db, VM, now=NOW)]
    assert any(t.startswith("A service in the VM is failing") for t in titles) and any("driver, firmware or storage error" in t for t in titles)
    assert any(t.startswith("Kasm logs a repeating error") for t in titles)


def test_an_image_nobody_started_in_thirty_days_is_a_suggestion_that_needs_approval_and_a_used_one_is_not(db):
    kt.record_launches(db, {"vs-code": 5, "chrome": 5}, now=NOW - 40 * DAY)
    kt.record_launches(db, {"vs-code": 5, "chrome": 30}, now=NOW - DAY)
    got = {s["id"]: s for s in kt.suggestions(db, VM, now=NOW)}
    assert got["unused-vs-code"]["action"]["needs_approval"] is True and "unused-chrome" not in got
    assert kt.launches_report(db, NOW - 30 * DAY) == {"vs-code": 0, "chrome": 25}


def test_an_image_watched_for_less_than_thirty_days_is_not_called_unused(db):
    kt.record_launches(db, {"firefox": 0}, now=NOW - 5 * DAY)
    assert not [s for s in kt.suggestions(db, VM, now=NOW) if s["id"].startswith("unused-")]


def test_suggestions_are_ordered_by_severity(db):
    put(db, "cpu_psi_some10", [40] * 10)
    kt.record(db, {}, [{"severity": "error", "source": "container_oom", "message": "x was killed for lack of memory"}], now=NOW - 60)
    kt.record_launches(db, {"firefox": 0}, now=NOW - 40 * DAY)
    assert [s["severity"] for s in kt.suggestions(db, VM, now=NOW)] == ["error", "warning", "info"]


def test_old_samples_events_and_launches_are_pruned_but_setting_history_is_kept(db):
    kt.record(db, {"mem_avail_pct": 50}, [{"severity": "error", "source": "kernel", "message": "x"}], now=NOW - 100 * DAY)
    kt.record_launches(db, {"a": 1}, now=NOW - 100 * DAY)
    kt.record_settings(db, {}, {"log_retention": "7"}, now=NOW - 100 * DAY)
    kt.prune(db, NOW - 30 * DAY)
    assert [db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("samples", "events", "launches", "setting_changes")] == [0, 0, 0, 1]


def test_the_settings_script_is_valid_shell_reads_the_password_from_stdin_and_drops_a_secrets_value():
    assert subprocess.run(["bash", "-n"], input=kt.SETTINGS_SCRIPT, text=True).returncode == 0
    assert "read -r pw" in kt.SETTINGS_SCRIPT and "--arg p \"$pw\"" in kt.SETTINGS_SCRIPT and "echo" not in kt.SETTINGS_SCRIPT.replace("# ", "")
    assert "if $s then null else .value end" in kt.SETTINGS_SCRIPT                          # a secret's value never leaves the VM


def test_settings_json_becomes_values_secret_names_and_a_marker_for_the_secret():
    values, secrets_ = kt.parse_settings('noise\n[{"name":"a","secret":false,"value":"1"},{"name":"t","secret":true,"value":null},{"name":"b","secret":false,"value":null}]')
    assert values == {"a": "1", "t": "<secret>"} and secrets_ == {"t"}
    assert kt.parse_settings("not json") == ({}, set()) and kt.parse_settings("") == ({}, set())


def test_accounting_rows_parse_and_a_bad_line_is_skipped():
    assert kt.parse_accounting("Chrome|12|3.5|1\nbad line\nVS Code|x|1|0\nFirefox|2|0|0\n") == [("Chrome", 12, 3.5, 1), ("Firefox", 2, 0.0, 0)]
    assert "user_name" not in kt.ACCOUNTING_SQL and "user_ip" not in kt.ACCOUNTING_SQL         # no person's name or address is read


def test_the_latest_value_of_each_setting_is_what_the_next_look_compares_with(db):
    kt.record_settings(db, {}, {"a": "1", "t": "<secret>"}, secret_names={"t"}, now=NOW - 100)
    kt.record_settings(db, {"a": "1", "t": "<secret>"}, {"a": "2", "t": "<secret>"}, secret_names={"t"}, now=NOW)
    assert kt.latest_settings(db) == {"a": "2", "t": "<secret>"}


def test_a_kasm_json_log_line_is_kept_as_what_happened_and_not_its_request_details():
    """From a real Kasm 1.19.0 line (2026-10-17): the JSON carried a request address and user agent that are not wanted in the history."""
    line = ('E error kasm:api_server {"asctime": "2026-10-17 18:44:19", "funcName": "refresh_token", "levelname": "ERROR", "message": "Error while decoding token: Not enough segments", '
            '"request_ip": "172.18.0.6", "user_agent": "python-requests/2.33.1", "token_lifespan_seconds": 259200}')
    _, events = kt.parse_probe(line)
    assert events[0]["message"] == "refresh_token: Error while decoding token: Not enough segments"
    assert "172.18" not in events[0]["message"] and "python-requests" not in events[0]["message"]
    _, listed = kt.parse_probe('E error kasm:kasmguac {"levelname":"ERROR","message":["[server] Healthcheck failed for x. Error: 502"]}')
    assert listed[0]["message"] == "[server] Healthcheck failed for x. Error: 502"
    _, plain = kt.parse_probe("E error kasm:agent not json at all")
    assert plain[0]["message"] == "not json at all"


def test_the_probe_reports_each_disk_once():
    assert kt.PROBE.count("disk_root_used_pct") == 0 and "df -P" in kt.PROBE                 # named by the loop over mounts, so `/` appears once, as root


def test_redaction_removes_secret_values_and_leaves_ordinary_words_alone():
    """Found on a real Kasm line (2026-10-17): a plain "decoding token: Not enough segments" was mangled by an over-eager pattern."""
    assert kt.redact("refresh_token: Error while decoding token: Not enough segments") == "refresh_token: Error while decoding token: Not enough segments"
    assert kt.redact("login failed password=hunter2 for user") == "login failed password=<redacted> for user"
    assert kt.redact('{"api_key": "abc", "name": "keep"}') == '{"api_key": "<redacted>", "name": "keep"}'
    assert kt.redact("Authorization: Bearer abc.def-ghi") == "Authorization: Bearer <redacted>"
    assert kt.redact("sent " + "x" * 30 + " ok") == "sent <redacted> ok"


VM_STATUS = {"cpu": 0.42, "cpus": 4, "mem": 3221225472, "maxmem": 6442450944, "pressurecpusome": 3.5, "pressurememorysome": 12.0, "pressureiosome": 0.5, "netin": 1}
NODE_STATUS = {"cpu": 0.31, "memory": {"total": 17179869184, "used": 8589934592, "free": 8589934592}, "swap": {"total": 2147483648, "used": 214748364}}


def test_proxmoxs_view_of_the_vm_and_the_host_becomes_metrics():
    got = kt.parse_host_view(VM_STATUS, NODE_STATUS)
    assert got == {"host_vm_cpu_pct": 42.0, "host_vm_mem_used_pct": 50.0, "host_vm_pressure_cpu": 3.5, "host_vm_pressure_memory": 12.0, "host_vm_pressure_io": 0.5,
                   "host_node_mem_used_pct": 50.0, "host_node_mem_total_mb": 16384, "host_node_mem_free_mb": 8192, "host_node_swap_used_pct": 10.0, "host_node_cpu_pct": 31.0}


def test_an_older_proxmox_without_pressure_figures_or_a_bad_field_is_not_an_error():
    got = kt.parse_host_view({"cpu": "x", "mem": 100, "maxmem": 0}, {"memory": "nonsense", "swap": {}})
    assert got == {}
    assert "host_vm_pressure_cpu" not in kt.parse_host_view({"cpu": 0.1}, {})


def _memory_pressure(db):
    put(db, "mem_avail_pct", [4, 5, 6, 40, 50, 6, 5, 4])
    put(db, "memory_psi_some10", [25, 30, 1, 1, 22, 24, 26, 2])


def test_more_memory_says_the_host_has_room_when_it_does(db):
    _memory_pressure(db)
    put(db, "host_node_mem_used_pct", [40] * 10)
    put(db, "host_node_mem_free_mb", [9000] * 10)
    item = next(s for s in kt.suggestions(db, VM, now=NOW) if s["id"] == "more-memory")
    assert item["action"] == {"memory_mb": 9216} and any("the host has room: it used at most 40%" in e for e in item["evidence"])


def test_more_memory_is_held_back_when_the_host_itself_is_short_so_the_host_is_not_starved(db):
    _memory_pressure(db)
    put(db, "host_node_mem_used_pct", [95] * 10)
    put(db, "host_node_mem_free_mb", [1500] * 10)                                                    # the VM would need 3072 MB more
    item = next(s for s in kt.suggestions(db, VM, now=NOW) if s["id"] == "more-memory")
    assert "the host has only 1500 MB free" in item["title"] and item["action"]["blocked_by_host"] is True and item["action"]["host_free_mb"] == 1500
    assert "without pushing the host into swap" in item["benefit"]


def test_more_cores_says_so_when_the_hosts_own_cpus_are_busy_too(db):
    put(db, "cpu_psi_some10", [40] * 10)
    put(db, "host_node_cpu_pct", [96] * 10)
    item = next(s for s in kt.suggestions(db, VM, now=NOW) if s["id"] == "more-cores")
    assert item["title"].endswith("(the host is busy too)") and any("less than its full share" in e for e in item["evidence"])
    other = kt.open_db(":memory:")
    put(other, "cpu_psi_some10", [40] * 10)
    assert not next(s for s in kt.suggestions(other, VM, now=NOW) if s["id"] == "more-cores")["title"].endswith("(the host is busy too)")


def test_a_host_that_is_swapping_is_called_out_as_the_hosts_problem_not_the_vms(db):
    put(db, "host_node_swap_used_pct", [35] * 10)
    item = next(s for s in kt.suggestions(db, VM, now=NOW) if s["id"] == "host-swapping")
    assert "35%" in item["title"] and "not this VM alone" in item["benefit"]
    quiet = kt.open_db(":memory:")
    put(quiet, "host_node_swap_used_pct", [3] * 10)
    assert not [s for s in kt.suggestions(quiet, VM, now=NOW) if s["id"] == "host-swapping"]
