# DR128 recipe web verification

14 focused recipe/parser/CLI/HTTP tests passed in0.68s. Actual local HTTP server
and real parser; fixture auth/session/dependencies, no native guest or physical
storage verification. Checks: page, validated export, composed lock, verified
stack, anonymous/limited refusal, ambiguous JSON/private fields/types/unsupported
build-action refusal and digest tampering. No recipe bytes are saved server-side.
recipe-page.html is rendered source output, not a browser screenshot or live-clone
capture. Node syntax check passed for its extracted JavaScript; browser automation
of file picker/download is not claimed. Provision imports/whitespace checks passed.
No private credentials/user data/hardware operations. See DR128 for open work.

Final guarded regression suite: **2,923 passed in130.96s**. Implementation
commite3660b6. Native guest/hardware and browser automation remain unverified.
