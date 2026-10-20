# DR143 evidence

physical-metadata.json records read-only physical inspection commands, exit
codes and outputs. No device contents were changed by these commands.

Regression verification used:

```sh
pytest -q tests/unit/test_truthful_runtime_errors.py tests/unit/test_config_diff.py tests/unit/test_update_pipeline.py tests/unit/test_proxmox_vm_metrics.py tests/unit/test_control_panel_web.py tests/unit/test_config_pipeline.py tests/unit/test_settings_web.py
```

Observed result: 211 passed in 0.52s. Before implementation, the twelve added
cases failed (12 failed, 19 deselected). This is a summary of observed tool
results, not a captured raw test transcript. Tests use synthetic boundaries;
no live Proxmox or physical write behavior was verified. Production imports,
boot/provision.sh shell syntax and git diff whitespace checks also passed.
