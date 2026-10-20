"""Native disk/seed/rebuild checks, explicitly separate from guest GUI proof.

Uses synthetic blank backing images and production Ubuntu configuration builders.
No physical drive, published Ubuntu source, guest boot or browser is exercised.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'baseline/lib'))
import ubuntu_environment as ue
from vm_host import VmHost


def run(argv):
    return subprocess.run(argv,check=True,capture_output=True,text=True,timeout=60).stdout


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def configuration_from_seed(folder):
    extracted=folder/'extracted-user-data'
    run(['xorriso','-osirrox','on','-indev',str(folder/'seed.iso'),'-extract','/user-data',str(extracted)])
    extracted.chmod(0o600)
    config=json.loads(extracted.read_text().split('\n',1)[1])
    for command in config['bootcmd']:
        if command[:2]==['bash','-c']:
            subprocess.run(['bash','-n'],input=command[2],text=True,check=True,capture_output=True)
    for command in config['runcmd']:
        if command[:2]==['bash','-ec']:
            subprocess.run(['bash','-n'],input=command[2],text=True,check=True,capture_output=True)
    extracted.unlink()
    return config


def main():
    with tempfile.TemporaryDirectory(prefix='baseline-ubuntu-overlay-') as directory:
        root=Path(directory)
        host=VmHost(root/'os',persistence_store=root/'retained',runtime_dir=root/'run')
        base=host.base_path('synthetic-base');base.parent.mkdir(parents=True)
        run(['qemu-img','create','-f','qcow2',str(base),'8G'])
        base.chmod(0o444)
        original=digest(base)
        ue.create(host,'desktop',base='synthetic-base',locale='en_GB.UTF-8',
                  homepage='https://baseline.invalid:8006',disk_gb=12,persistence_gb=1)
        before=configuration_from_seed(host.vm_dir('desktop'))
        assert before['locale']=='en_GB.UTF-8'
        configuration=next(item for item in before['write_files'] if item['path']=='/etc/baseline/environment-configuration.json')
        assert json.loads(configuration['content'])['locale']=='en_GB.UTF-8'
        info=json.loads(run(['qemu-img','info','--output=json',str(host.disk_path('desktop'))]))
        assert Path(info['full-backing-filename'])==base
        assert info['virtual-size']==12*2**30
        run(['qemu-io','-f','qcow2','-c','write -P 0x41 0 4096',str(host.disk_path('desktop'))])
        run(['qemu-io','-f','qcow2','-c','write -P 0x42 0 4096',str(host.persistence_path('desktop'))])
        retained=digest(host.persistence_path('desktop'))
        ue.rebuild(host,'desktop')
        after=configuration_from_seed(host.vm_dir('desktop'))
        assert after['locale']==before['locale']
        assert after['write_files']==before['write_files']
        assert 'mkfs' not in after['bootcmd'][0][2]
        assert digest(base)==original
        assert digest(host.persistence_path('desktop'))==retained
        run(['qemu-io','-f','qcow2','-c','read -P 0x00 0 4096',str(host.disk_path('desktop'))])
        run(['qemu-io','-f','qcow2','-c','read -P 0x42 0 4096',str(host.persistence_path('desktop'))])
        for disk in (base,host.disk_path('desktop'),host.persistence_path('desktop')):
            run(['qemu-img','check',str(disk)])
        print(json.dumps({'real_qcow2_overlay':True,'real_cloud_init_iso':True,
            'configuration_seed_preserved_after_rebuild':True,'base_unchanged':True,
            'retained_disk_unchanged':True,'os_disk_reset':True,
            'published_ubuntu_source_used':False,'guest_booted':False,
            'browser_page_loaded':False,'physical_device_used':False}))


if __name__=='__main__':main()
