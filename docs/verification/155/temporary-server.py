import json, subprocess, time, uuid
from pathlib import Path
address = '10.0.0.231'
links = json.loads(subprocess.check_output(['ip', '-j', 'address'], text=True))
assert any(Path('/sys/class/net', link['ifname'], 'device').exists() and any(a.get('local') == address for a in link.get('addr_info', [])) for link in links), 'LAN address changed; refusing'
assert not subprocess.check_output(['ss', '-H', '-ltn', 'sport = :5201'], text=True).strip(), '5201 already occupied; refusing'
table = 'baseline_iperf_' + uuid.uuid4().hex
rules = f'''add table inet {table}
add chain inet {table} input {{ type filter hook input priority -10; policy accept; }}
add rule inet {table} input ip daddr {address} tcp dport 5201 ip saddr != 10.0.0.0/24 drop
'''
subprocess.run(['nft', '-f', '-'], input=rules, text=True, check=True)
process = None
try:
    process = subprocess.Popen(['/tmp/baseline-iperf-real/root/usr/bin/iperf3', '-s', '-1', '-B', address, '-p', '5201'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(20):
        listing = subprocess.check_output(['ss', '-H', '-ltnp', 'sport = :5201'], text=True)
        if f'{address}:5201' in listing and f'pid={process.pid},' in listing:
            break
        assert process.poll() is None, 'server exited before ready'
        time.sleep(.1)
    else:
        raise RuntimeError('listener readiness not observed')
    print(json.dumps({'listener': address + ':5201', 'pid': process.pid, 'source_scope': '10.0.0.0/24', 'max_seconds': 600, 'single_use': True, 'physical_throughput_verified': False}), flush=True)
    try:
        output, _ = process.communicate(timeout=600)
    except subprocess.TimeoutExpired:
        process.terminate()
        output, _ = process.communicate(timeout=10)
    print(output, flush=True)
finally:
    if process is not None and process.poll() is None:
        process.kill()
        process.wait()
    subprocess.run(['nft', 'delete', 'table', 'inet', table], check=True)
    print('Temporary listener and source restriction cleaned up.', flush=True)
