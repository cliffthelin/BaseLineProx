import json
import pytest
from fake_runner import FakeRunner, FakeProc
import single_drive_storage as storage


def test_identity_isolation_refuses_a_vg_with_more_than_one_physical_volume(monkeypatch):
    disk = {"name":"/dev/sdd", "serial":"DRIVE-A", "size":512110190592,
            "children":[{"name":"/dev/sdd3","type":"part","fstype":"LVM2_member"}]}
    import drive_recovery
    monkeypatch.setattr(drive_recovery,"_offline_disk",lambda *a:disk)
    monkeypatch.setattr(storage.pds,"validate_target_device",lambda *a,**k:
        {"path":"/dev/sdd","serial":"DRIVE-A","size_bytes":512110190592})
    rows = [{"pv_name":"/dev/sdd3","pv_uuid":"pv-a","vg_name":"pve","vg_uuid":"vg-a","pv_count":"2"}]
    runner = FakeRunner(command_responses=[
        (lambda a:a[0]=="id",FakeProc(0,"0\n","")),
        (lambda a:a[0]=="fuser",FakeProc(1,"","")),
        (lambda a:a[0]=="pvs",FakeProc(0,json.dumps({"report":[{"pv":rows}]}),""))])
    with pytest.raises(storage.StorageError,match="one physical volume"):
        storage.isolate_volume_group(runner,expected_serial="DRIVE-A")
    assert not any(a[0]=="vgrename" for a in runner.calls)


def test_identity_isolation_renames_by_uuid_and_limits_the_selected_pv(monkeypatch):
    import hashlib
    import drive_recovery
    disk = {"name":"/dev/sdd","serial":"DRIVE-A","size":512110190592,
        "children":[{"name":"/dev/sdd3","type":"part","fstype":"LVM2_member"}]}
    monkeypatch.setattr(drive_recovery,"_offline_disk",lambda *a:disk)
    monkeypatch.setattr(storage.pds,"validate_target_device",lambda *a,**k:
        {"path":"/dev/sdd","serial":"DRIVE-A","size_bytes":512110190592})
    row = {"pv_name":"/dev/sdd3","pv_uuid":"pv-a","vg_name":"pve","vg_uuid":"vg-a","pv_count":"1"}
    name = "baseline_"+hashlib.sha256(b"DRIVE-A").hexdigest()[:12]
    def response(argv):
        if argv[0]=="pvs":return FakeProc(0,json.dumps({"report":[{"pv":[dict(row)]}]}),"")
        if argv[0]=="vgrename":
            assert argv==["vgrename","--devices","/dev/sdd3","vg-a",name]
            row["vg_name"]=name
            return FakeProc(0,"","")
    class IdentityRunner(FakeRunner):
        def run(self,argv,timeout=10):
            if argv[0] in ("pvs","vgrename"):
                self.calls.append(argv)
                return response(argv)
            return super().run(argv,timeout=timeout)
    runner = IdentityRunner(command_responses=[
        (lambda a:a[0]=="id",FakeProc(0,"0\n","")),
        (lambda a:a[0]=="fuser",FakeProc(1,"","")),
        (lambda a:a[0]=="vgs",FakeProc(0,json.dumps({"report":[{"vg":[
            {"vg_name":"pve","vg_uuid":"vg-a"},{"vg_name":"pve","vg_uuid":"other-drive"}]}]}),"")),
        ])
    result=storage.isolate_volume_group(runner,expected_serial="DRIVE-A")
    assert result["vg_name"]==name
    assert result["pv_uuid"]=="pv-a"
    assert result["boot_verified"] is False
