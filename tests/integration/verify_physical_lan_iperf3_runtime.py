"""Explicit actual Ethernet/AP/Wi-Fi iperf3 test; no remote credentials/fakes.

Root required. Adds a disposable Ethernet macvlan namespace, one unused /24
address after ARP duplicate detection, one exact host /32 route/neighbor and
port-scoped firewall restriction. Existing adapters/routes are never replaced.
Measures both directions on TCP 5201; finally removes all owned resources.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import time
import uuid


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=20, **kwargs)


def counters():
    return {iface: {kind: int(Path('/sys/class/net', iface, 'statistics', kind + '_bytes').read_text())
                    for kind in ('rx', 'tx')} for iface in ('eno1', 'wlp9s0')}


def physical_evidence(before, after, received, reverse):
    sender, receiver = ('wlp9s0', 'eno1') if reverse else ('eno1', 'wlp9s0')
    delta = {iface: {kind: after[iface][kind] - before[iface][kind] for kind in ('rx', 'tx')}
             for iface in before}
    return received > 1000000 and delta[sender]['tx'] >= received * .8 and delta[receiver]['rx'] >= received * .8, delta


def transfer(executable, destination, prefix=(), reverse=False):
    server = subprocess.Popen([executable, '-s', '-1', '-B', destination, '-p', '5201'],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(30):
            listing = run(['ss', '-H', '-ltnp', 'sport = :5201']).stdout
            if f'{destination}:5201' in listing and f'pid={server.pid},' in listing:
                break
            assert server.poll() is None, server.communicate()
            time.sleep(.1)
        else:
            raise RuntimeError('Owned listener not observed')
        before = counters()
        argv = [*prefix, executable, '-c', destination, '-p', '5201', '-t', '5', '--connect-timeout', '2000', '-J']
        if reverse:
            argv.append('-R')
        result = json.loads(run(argv).stdout)
        after = counters()
        server.communicate(timeout=10)
        assert server.returncode == 0, server.returncode
        received = result['end']['sum_received']['bytes']
        verified, delta = physical_evidence(before, after, received, reverse)
        return result, verified, delta
    finally:
        if server.poll() is None:
            server.terminate()
            server.communicate(timeout=10)


def verify(executable, arping):
    assert os.geteuid() == 0, 'Root required'
    assert not run(['ss', '-H', '-ltn', 'sport = :5201']).stdout.strip(), 'Port occupied; refusing'
    links = json.loads(run(['ip', '-j', 'address']).stdout)
    selected = {link['ifname']: link for link in links if link['ifname'] in ('eno1', 'wlp9s0')}
    assert set(selected) == {'eno1', 'wlp9s0'}
    for iface, link in selected.items():
        assert Path('/sys/class/net', iface, 'device').exists() and 'LOWER_UP' in link['flags']
    assert 'Connected to ' in run(['iw', 'dev', 'wlp9s0', 'link']).stdout
    wifi = [a for a in selected['wlp9s0']['addr_info'] if a['family'] == 'inet']
    ethernet = [a for a in selected['eno1']['addr_info'] if a['family'] == 'inet']
    assert len(wifi) == len(ethernet) == 1
    subnet = ipaddress.ip_network(f"{wifi[0]['local']}/{wifi[0]['prefixlen']}", strict=False)
    assert subnet.is_private and subnet.prefixlen == 24
    assert ipaddress.ip_address(ethernet[0]['local']) in subnet
    destination = wifi[0]['local']
    local_addresses = {a['local'] for link in links for a in link.get('addr_info', [])}
    # Actual negative control: a fast local transfer must not qualify as LAN.
    control, accepted, delta = transfer(executable, '127.0.0.1')
    assert not accepted, 'Local transfer incorrectly qualified as physical LAN'
    print(json.dumps({'loopback_control_refused': True, 'hardware_deltas': delta}), flush=True)
    suffix = uuid.uuid4().hex[:10]
    namespace, child, table = 'bl-lan-' + suffix, 'bl' + suffix, 'bl_iperf_' + suffix
    namespace_created = route_created = neighbor_created = table_created = child_created = False
    candidate = None
    try:
        run(['ip', 'netns', 'add', namespace]); namespace_created = True
        run(['ip', 'link', 'add', 'link', 'eno1', 'name', child, 'type', 'macvlan', 'mode', 'bridge']); child_created = True
        run(['ip', 'link', 'set', child, 'netns', namespace]); child_created = False
        prefix = ['ip', 'netns', 'exec', namespace]
        run([*prefix, 'ip', 'link', 'set', 'lo', 'up'])
        run([*prefix, 'ip', 'link', 'set', child, 'up'])
        known = {n['dst'] for n in json.loads(run(['ip', '-j', 'neigh']).stdout) if n.get('lladdr')}
        for number in range(250, 255):
            address = str(subnet.network_address + number)
            if address in local_addresses or address in known:
                continue
            probe = subprocess.run([*prefix, arping, '-D', '-I', child, '-c', '3', '-w', '4', address],
                                   capture_output=True, text=True, timeout=7)
            if probe.returncode == 0:
                candidate = address
                break
        assert candidate, 'No duplicate-free temporary address found'
        print(json.dumps({'temporary_client': candidate, 'server': destination, 'port': 5201,
                          'path': 'Ethernet macvlan -> physical LAN/AP -> Wi-Fi'}), flush=True)
        # Exact add operations refuse conflicts; no existing route/neighbor replaced.
        assert not json.loads(run(['ip', '-j', 'route', 'show', candidate + '/32']).stdout)
        assert not any(n['dst'] == candidate and n['dev'] == 'wlp9s0' for n in json.loads(run(['ip', '-j', 'neigh']).stdout))
        run([*prefix, 'ip', 'address', 'add', candidate + '/24', 'dev', child])
        child_mac = json.loads(run([*prefix, 'ip', '-j', 'link', 'show', child]).stdout)[0]['address']
        run([*prefix, 'ip', 'neigh', 'add', destination, 'lladdr', selected['wlp9s0']['address'], 'dev', child, 'nud', 'permanent'])
        run(['ip', 'route', 'add', candidate + '/32', 'dev', 'wlp9s0', 'src', destination]); route_created = True
        run(['ip', 'neigh', 'add', candidate, 'lladdr', child_mac, 'dev', 'wlp9s0', 'nud', 'permanent']); neighbor_created = True
        rules = f'''add table inet {table}
add chain inet {table} input {{ type filter hook input priority -10; policy accept; }}
add rule inet {table} input ip daddr {destination} tcp dport 5201 ip saddr != {subnet} drop
'''
        run(['nft', '-f', '-'], input=rules); table_created = True
        for reverse in (False, True):
            result, verified, delta = transfer(executable, destination, prefix, reverse)
            assert verified, f'Physical NIC traffic not corroborated: {delta}'
            measurement = {'direction': 'Wi-Fi to Ethernet' if reverse else 'Ethernet to Wi-Fi',
                           'received_mbit_s': result['end']['sum_received']['bits_per_second'] / 1000000,
                           'received_bytes': result['end']['sum_received']['bytes'], 'hardware_deltas': delta,
                           'physical_path_verified': verified, 'iperf3': result}
            print(json.dumps(measurement), flush=True)
        print(json.dumps({'physical_lan_throughput_verified': True, 'scope': 'same machine, distinct physical Ethernet/Wi-Fi adapters through LAN/AP; not wired-only capacity or separate-host workflow'}), flush=True)
    finally:
        if table_created:
            run(['nft', 'delete', 'table', 'inet', table])
        if neighbor_created:
            run(['ip', 'neigh', 'del', candidate, 'dev', 'wlp9s0'])
        if route_created:
            run(['ip', 'route', 'del', candidate + '/32', 'dev', 'wlp9s0'])
        if child_created:
            run(['ip', 'link', 'del', child])
        if namespace_created:
            run(['ip', 'netns', 'delete', namespace])
        assert not run(['ss', '-H', '-ltn', 'sport = :5201']).stdout.strip()
        print(json.dumps({'cleanup_verified': True, 'owned_namespace': namespace, 'owned_firewall_table': table}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('executable')
    parser.add_argument('arping')
    args = parser.parse_args()
    verify(str(Path(args.executable).resolve(strict=True)), str(Path(args.arping).resolve(strict=True)))
