# DR123 verification

live-login.json records actual authenticated durable VM actions and checks,
not bare-metal deployment. Initial script crypt-verified the fresh guest login,
proved one-time retrieval and unchanged original document, then performed the
explicit web OS rebuild. It timed out after that rebuild waiting for the agent:
normal seed lacked the old fixture's proxy settings in restrict=on networking.
The completed reset/rebuild outcomes were retained in the app's job store.

Continuation restored only test-network apt proxy seed configuration and fresh
synthetic instance ID to the same already-rebuilt OS; no further OS reset or home
initialization. Guest became ready and reported original retained document and
exact rotated profile hash. Final service restart retained outcome. No hashes,
cleartext credentials or private keys are included. vm-page.html is the final
stopped-VM page, so it does not show the running-only Reset login button.

2,892 guarded unit tests passed in135.19s. source-sha256.json identifies final
source/tests. Ordinary-network firstboot, physical deployment, unsupported guest
adapters and host power-loss handling are not verified. See DR123 and queue75.
