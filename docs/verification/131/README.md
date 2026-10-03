# DR131 verification

Actual fresh publisher VS Code Linux-x64 archive build, separate profile, Xvfb.
`build.json` records exact publisher source and approved synthetic settings.
`install.json` records CLI materialization only, explicitly runtime false.
`live-vscode.json` independently records actual version/commit and settings consumed.
`runtime-probe.py` records the temporary configuration-API probe used; its absolute
/tmp paths identify this run, not a portable deployment installer. No archive, user
content, credentials or account login included. HTTPS hash checking is not a signature.
No managed guest, physical deployment or app isolation verification.

Regression:2,950 unit tests passed in127.53s;17 focused build/capture tests passed.
Bash provision syntax and git whitespace checks passed.
Temporary .test-work-131 directory remains untracked: automatic review rejected
its rm-style cleanup. It is not part of published verification artifacts.
