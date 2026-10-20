"""FydeOS's shipped VirtIO modules must precede the boot-splash dependency."""

def early_modules(config):
    marker = '  # Baseline FydeOS virtual hardware\n'
    if marker in config:
        return config
    if config.count('\nscript\n') != 1 or 'udevadm trigger' not in config:
        raise ValueError('unrecognized FydeOS early udev job; refusing to guess')
    return config.replace('\nscript\n', '\nscript\n' + marker +
                          '  modprobe virtio_gpu\n  modprobe virtio_net\n', 1)


def patch_raw(image, work):
    """Patch a regular, disposable raw appliance copy; never a host block device.

    Keep the vendor's state partition untouched and load shipped signed modules.
    No debug shell, account, password, or host settings are added.
    """
    from pathlib import Path
    import struct
    import subprocess
    raw, work = Path(image), Path(work)
    if raw.is_symlink() or not raw.is_file() or raw.resolve().is_relative_to('/dev'):
        raise ValueError('a disposable regular raw image is required')
    with raw.open('rb') as source:
        source.seek(512);header = source.read(512)
        if header[:8] != b'EFI PART':
            raise ValueError('appliance has no GPT header')
        lba = struct.unpack_from('<Q', header, 72)[0]
        count, size = struct.unpack_from('<II', header, 80)
        if not (1 <= count <= 256 and size == 128):
            raise ValueError('unexpected GPT entry layout')
        source.seek(lba * 512);table = source.read(count * size)
        roots = []
        for i in range(count):
            entry = table[i * size:(i + 1) * size]
            if len(entry) != size:
                raise ValueError('truncated GPT entries')
            if entry[56:].decode('utf-16le').rstrip('\0') == 'ROOT-A':
                first, last = struct.unpack_from('<QQ', entry, 32)
                roots.append((first * 512, (last - first + 1) * 512))
        if len(roots) != 1:
            raise ValueError('expected one ROOT-A partition')
        offset, length = roots[0]
        if offset < 17408 or length < 1024**2 or offset + length > raw.stat().st_size:
            raise ValueError('ROOT-A is outside the image')
        work.mkdir(parents=True, exist_ok=True)
        root = work / 'fydeos-root-a.img'
        if root.exists() or root.is_symlink():
            raise ValueError('patch scratch file already exists')
        source.seek(offset)
        with root.open('xb') as target:
            remaining = length
            while remaining:
                chunk = source.read(min(4 * 1024**2, remaining))
                if not chunk:
                    raise ValueError('truncated appliance root')
                target.write(chunk);remaining -= len(chunk)
    config = work / 'fydeos-udev-early.conf'
    job = '/etc/init/udev-trigger-early.conf'
    if any(c in str(work) for c in '\n\r"'):
        raise ValueError('unsafe debugfs scratch path')
    def debug(command, writable=False):
        subprocess.run(['debugfs'] + (['-w'] if writable else []) + ['-R', command, str(root)],
                       check=True, capture_output=True)
    if config.exists() or config.is_symlink():
        raise ValueError('patch config scratch file already exists')
    debug(f'dump {job} "{config}"')
    if not config.is_file():
        raise ValueError('FydeOS early udev job is missing')
    updated = early_modules(config.read_text());config.write_text(updated)
    debug(f'rm {job}', True)
    debug(f'write "{config}" {job}', True)
    debug(f'set_inode_field {job} mode 0100644', True)
    check = work / 'fydeos-udev-check.conf'
    if check.exists() or check.is_symlink():
        raise ValueError('patch verification scratch file already exists')
    debug(f'dump {job} "{check}"')
    if not check.is_file() or check.read_text() != updated:
        raise ValueError('early module patch did not persist')
    with raw.open('r+b') as target, root.open('rb') as source:
        target.seek(offset)
        while chunk := source.read(4 * 1024**2):
            target.write(chunk)
    return {'recipe': 'fydeos-virtio-gl-v1', 'early_modules': ['virtio_gpu', 'virtio_net'],
            'graphics': 'virgl', 'root_partition': 'ROOT-A', 'account_state': 'retained whole-system disk'}
