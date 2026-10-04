"""Explicit AppData mappings preserve the six-volume drive and require real identities."""
import copy
import pytest
import install_plan as ip
from test_install_plan import discover,proxmox_disk,baseline_disk,BASELINE_NAMES,OTHER


def test_existing_six_volume_drive_can_use_dedicated_appdata_on_another_enrolled_drive():
    baseline=baseline_disk(names=BASELINE_NAMES[:6]);external=baseline_disk(serial=OTHER,names=BASELINE_NAMES[6:],prefix='d')
    plan=ip.autofill(discover(proxmox_disk(),baseline))
    found=discover(proxmox_disk(),baseline,external)
    for persona,volume in zip(['admin','personal'],found['drives'][2]['volumes']):
        plan=ip.map_appdata(plan,found,persona=persona,serial=OTHER,partuuid=volume['partuuid'])
    assert ip.validate(plan,found)==[]
    stages=ip.compile_plan(plan,found)
    assert stages['executed'] is False and stages['baseline_drive']['action']=='retain'
    assert len(stages['baseline_drive']['mounts'])==6
    assert {m['persona'] for m in stages['appdata']}=={'admin','personal'}
    for mapping in stages['appdata']:
        assert mapping['expected_serial']==OTHER and mapping['source'].startswith('PARTUUID=d')
        assert mapping['mountpoint']=='/mnt/APPDATA_'+mapping['persona'].upper()


def test_appdata_only_drive_does_not_make_baseline_autofill_ambiguous():
    found=discover(proxmox_disk(),baseline_disk(names=BASELINE_NAMES[:6]),
                   baseline_disk(serial=OTHER,names=BASELINE_NAMES[6:],prefix='d'))
    plan=ip.autofill(found)
    assert plan['storage']['baseline']['serial']==found['drives'][1]['serial']


@pytest.mark.parametrize('serial,partuuid,persona',[
    (OTHER,'d0000000-0000-4000-8000-000000000000','personal'),
    (OTHER,'d0000000-0000-4000-8000-000000000000','unknown'),
    ('unenrolled','d0000000-0000-4000-8000-000000000000','admin'),
    (OTHER,'not-a-guid','admin'),
])
def test_wrong_persona_or_identity_mapping_is_refused(serial,partuuid,persona):
    found=discover(proxmox_disk(),baseline_disk(),baseline_disk(serial=OTHER,names=BASELINE_NAMES[6:],prefix='d'))
    plan=ip.autofill(found)
    with pytest.raises(ip.PlanError):ip.map_appdata(plan,found,persona=persona,serial=serial,partuuid=partuuid)


def test_user_and_cache_partitions_cannot_be_disguised_as_appdata():
    found=discover(proxmox_disk(),baseline_disk());plan=ip.autofill(found)
    for volume in found['drives'][1]['volumes'][:6]:
        with pytest.raises(ip.PlanError):ip.map_appdata(plan,found,persona='admin',serial=found['drives'][1]['serial'],partuuid=volume['partuuid'])


def test_cloned_and_replaced_appdata_partitions_are_refused_and_input_is_preserved():
    external=baseline_disk(serial=OTHER,names=BASELINE_NAMES[6:],prefix='d')
    found=discover(proxmox_disk(),baseline_disk(),external);plan=ip.autofill(found);before=copy.deepcopy(plan)
    mapped=ip.map_appdata(plan,found,persona='admin',serial=OTHER,partuuid=external['children'][0]['partuuid'])
    assert plan==before
    replaced=discover(proxmox_disk(),baseline_disk(),baseline_disk(serial=OTHER,names=BASELINE_NAMES[6:],prefix='e'))
    assert ip.validate(mapped,replaced)
    clone=baseline_disk(name='sdd',serial='unmanaged-clone',names=BASELINE_NAMES[6:],prefix='d')
    duplicated=discover(proxmox_disk(),baseline_disk(),external,clone)
    assert ip.validate(mapped,duplicated)


def test_explicit_local_mapping_does_not_emit_two_mounts_for_same_destination():
    found=discover(proxmox_disk(),baseline_disk());plan=ip.autofill(found)
    volume=found['drives'][1]['volumes'][6]
    mapped=ip.map_appdata(plan,found,persona='admin',serial=found['drives'][1]['serial'],partuuid=volume['partuuid'])
    stages=ip.compile_plan(mapped,found)
    destinations=[m['mountpoint'] for m in stages['baseline_drive']['mounts']+stages['appdata']]
    assert len(destinations)==len(set(destinations))


def test_web_mapping_action_validates_target_against_fresh_discovery():
    import install_plan_page as page
    baseline=baseline_disk(names=BASELINE_NAMES[:6]);external=baseline_disk(serial=OTHER,names=BASELINE_NAMES[6:],prefix='d')
    found=discover(proxmox_disk(),baseline,external);plan=ip.autofill(found)
    result=page.perform({'action':'map_appdata','plan':plan,'persona':'admin','serial':OTHER,
                         'partuuid':external['children'][0]['partuuid']},discovery_provider=lambda:found)
    assert result['plan']['storage']['appdata']['admin']['serial']==OTHER
    assert result['executed'] is False and not result['valid']


def test_editor_lists_only_unique_ready_appdata_targets_for_selection():
    import install_plan_page as page
    external=baseline_disk(name='sdc',serial=OTHER,names=BASELINE_NAMES[6:],prefix='d')
    found=discover(proxmox_disk(),baseline_disk(names=BASELINE_NAMES[:6]),external)
    result=page.perform({'action':'autofill'},discovery_provider=lambda:found)
    assert [v['persona'] for v in result['appdata_candidates']]==['admin','personal']
    assert all(v['serial']==OTHER for v in result['appdata_candidates'])
    clone=baseline_disk(name='sdd',serial='unenrolled-clone',names=BASELINE_NAMES[6:],prefix='d')
    duplicated=discover(proxmox_disk(),baseline_disk(names=BASELINE_NAMES[:6]),external,clone)
    assert page.perform({'action':'autofill'},discovery_provider=lambda:duplicated)['appdata_candidates']==[]
