"""Actual qemu-img conversion and base-integrity checks on disposable files.

No guest boots, physical device, operator credentials or mounted cache involved.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'baseline/lib'))
import ubuntu_environment as ue
import vm_host
import installer_sources
from repair import RealRunner


def main():
    with tempfile.TemporaryDirectory(prefix='baseline-ubuntu-base-receipt-') as directory:
        root=Path(directory);source=root/'source.img'
        try:installer_sources.acquire_ubuntu(RealRunner(),root)
        except installer_sources.SourceError:pass
        else:raise AssertionError('ordinary root-directory cache fallback was accepted')
        assert not (root/'isos').exists()
        subprocess.run(['qemu-img','create','-f','qcow2',str(source),'1M'],check=True,capture_output=True)
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        host=vm_host.VmHost(root/'os',persistence_store=root/'retained')
        target=ue.install_base(host,source=source,expected_sha256=digest)
        assert ue.verify_base(host,target,expected_source_sha256=digest)==target
        subprocess.run(['qemu-img','check','-f','qcow2',str(target)],check=True,capture_output=True)
        target.chmod(0o600);target.write_bytes(b'changed')
        try:ue.verify_base(host,target,expected_source_sha256=digest)
        except ue.UbuntuError as exc:assert 'digest' in str(exc)
        else:raise AssertionError('changed base was trusted')
        print(json.dumps({'real_qemu_img_conversion':True,'receipt_verified':True,'tampered_base_refused':True,
                          'physical_device_used':False,'guest_booted':False,'publisher_image_downloaded':False,'actual_plain_directory_cache_refused':True}))


if __name__=='__main__':main()
