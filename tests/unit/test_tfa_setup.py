"""Two-factor enrolment (TOTP) for Proxmox users, guided from Baseline's web app. RFC 6238 vectors prove the code arithmetic; the Proxmox call is
the exact `pvesh create /access/tfa` argument list."""
import base64

import pytest

import tfa_setup as t

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()          # the RFC 6238 SHA-1 test key


@pytest.mark.parametrize("when,code", [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"),
                                       (2000000000, "279037")])
def test_totp_matches_the_rfc_6238_sha1_vectors(when, code):
    assert t.totp(RFC_SECRET, when) == code


def test_a_code_is_accepted_one_step_either_side_and_no_further():
    assert t.verify(RFC_SECRET, "287082", now=59) is True
    assert t.verify(RFC_SECRET, "287082", now=59 + 30) is True
    assert t.verify(RFC_SECRET, "287082", now=59 + 90) is False
    assert t.verify(RFC_SECRET, "000000", now=59) is False
    assert t.verify(RFC_SECRET, "28708", now=59) is False and t.verify(RFC_SECRET, "abcdef", now=59) is False


def test_a_new_secret_is_random_base32_of_enough_length_and_the_uri_names_user_and_issuer():
    a, b = t.new_secret(), t.new_secret()
    assert a != b and len(a) >= 32 and set(a) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    uri = t.otpauth_uri("baseline@pam", a, issuer="Baseline PC601")
    assert uri.startswith("otpauth://totp/Baseline%20PC601:baseline%40pam?") and f"secret={a}" in uri and "issuer=Baseline%20PC601" in uri


def test_the_proxmox_call_carries_the_uri_and_the_confirming_code_as_separate_arguments():
    argv = t.enroll_argv("baseline@pam", "otpauth://totp/x?secret=ABC", "123456", "Baseline authenticator")
    assert argv[:4] == ["pvesh", "create", "/access/tfa", "--userid"] and argv[4] == "baseline@pam"
    assert argv[argv.index("--type") + 1] == "totp" and argv[argv.index("--totp") + 1] == "otpauth://totp/x?secret=ABC"
    assert argv[argv.index("--value") + 1] == "123456"


def test_only_plain_proxmox_user_ids_are_accepted():
    assert t.check_userid("baseline@pam") == "baseline@pam" and t.check_userid("root@pam") == "root@pam"
    for bad in ("", "no-realm", "a b@pam", "x@pam; rm -rf /", "../../x@pam"):
        with pytest.raises(ValueError):
            t.check_userid(bad)
