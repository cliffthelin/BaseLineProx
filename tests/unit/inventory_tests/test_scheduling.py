from inventory.redact import Redactor
from inventory.runner import CommandResult
from inventory.collectors import scheduling

from .fake_runner import FakeRunner


def test_other_user_crontabs_are_counted_and_tokenized_never_raw():
    r = FakeRunner()
    r.dirs["/var/spool/cron/crontabs"] = ["root", "baseline", "someone_else", "another_user"]
    redactor = Redactor(key=b"fixed")
    result = scheduling.collect_scheduling(r, redactor)
    assert result["other_user_crontabs_count"] == 2
    assert "someone_else" not in result["other_user_crontabs_tokenized"]
    assert "another_user" not in result["other_user_crontabs_tokenized"]
    assert all(t.startswith("user:") for t in result["other_user_crontabs_tokenized"])


def test_cron_command_arguments_are_sanitized():
    r = FakeRunner()
    r.binaries["crontab"] = "/usr/bin/crontab"
    r.script(
        lambda a: a[:3] == ["crontab", "-l", "-u"] and "root" in a,
        CommandResult(ok=True, stdout="0 3 * * * /usr/local/bin/backup.sh --token=abc123secret\n"),
    )
    redactor = Redactor(key=b"fixed")
    result = scheduling.collect_scheduling(r, redactor)
    assert "abc123secret" not in str(result["root_crontab"])
    assert "0 3 * * *" in result["root_crontab"][0]


def test_allowlisted_service_account_crontab_is_included():
    r = FakeRunner()
    r.binaries["crontab"] = "/usr/bin/crontab"
    r.script(
        lambda a: "baseline" in a,
        CommandResult(ok=True, stdout="*/5 * * * * /opt/baseline/bin/healthcheck\n"),
    )
    redactor = Redactor(key=b"fixed")
    result = scheduling.collect_scheduling(r, redactor)
    assert "baseline" in result["allowlisted_service_crontabs"]
