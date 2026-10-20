from concurrent.futures import ThreadPoolExecutor
from settings_web import LocalAppStore


def test_request_threads_share_store_and_preserve_concurrent_updates(tmp_path):
    store = LocalAppStore(tmp_path / 'settings.db', mac_key=b'x' * 32)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: store.update_section('thread-proof', {str(n): n}), range(40)))
        values = list(pool.map(lambda _: store.settings()['thread-proof'], range(8)))
    assert all(value == {str(n): n for n in range(40)} for value in values)
