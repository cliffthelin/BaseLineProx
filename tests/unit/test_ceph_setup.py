"""Ceph on the Proxmox host (operator: "still no Ceph installed"): the package install through Proxmox's own tool, run in the background
with a readable state; initialising a cluster is a separate, deliberate step and is not done here."""
import time
from types import SimpleNamespace as NS

import ceph_setup as cs


class Runner:
    def __init__(self, rc=0, installed=False, delay=0.0):
        self.calls, self.rc, self.installed, self.delay = [], rc, installed, delay

    def run(self, argv, timeout=0):
        self.calls.append(list(argv))
        if argv[:2] == ["dpkg-query", "-W"]:
            return NS(returncode=0 if self.installed else 1, stdout="ceph-common 19.2.0" if self.installed else "", stderr="")
        time.sleep(self.delay)
        if self.rc == 0:
            self.installed = True
        return NS(returncode=self.rc, stdout="done", stderr="" if self.rc == 0 else "Temporary failure resolving 'download.proxmox.com'")


def wait(job, phase, seconds=5):
    end = time.time() + seconds
    while time.time() < end:
        if job.state()["phase"] == phase:
            return job.state()
        time.sleep(0.02)
    raise AssertionError(job.state())


def test_installed_state_is_read_from_the_package_database():
    assert cs.is_installed(Runner(installed=True)) is True and cs.is_installed(Runner(installed=False)) is False


def test_the_install_uses_proxmox_own_tool_with_the_no_subscription_repository_and_reports_done():
    runner = Runner()
    job = cs.InstallJob(runner)
    job.start()
    wait(job, "done")
    assert ["pveceph", "install", "--repository", "no-subscription"] in runner.calls
    assert cs.is_installed(runner)


def test_a_network_failure_is_reported_in_plain_words_and_can_be_retried():
    job = cs.InstallJob(Runner(rc=100))
    job.start()
    state = wait(job, "failed")
    assert "internet" in state["message"].lower() and "download.proxmox.com" in state["message"]
    job2 = cs.InstallJob(Runner())
    job2.start()
    wait(job2, "done")


def test_an_install_that_is_already_there_is_not_run_again():
    runner = Runner(installed=True)
    job = cs.InstallJob(runner)
    job.start()
    assert wait(job, "done")["message"].startswith("Ceph is already installed")
    assert not any(c[:2] == ["pveceph", "install"] for c in runner.calls)
