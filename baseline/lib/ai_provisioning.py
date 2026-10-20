"""Opt-in AI profiles: sealed in USER_ADMIN, materialized in RAM, never in plans.

Profiles carry native config/auth files opaquely. Import does not authenticate or
execute MCP commands. Native application keyrings/browser cookies are not copied.
"""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

import vault
import vault_crypto

PROFILE = 'AI_SETUP_DEFAULT'
MAX_BYTES = 1024 * 1024
# Provider catalog extends, rather than changes, the executable harness registry.
CATALOG = {
 'openai': {'name': 'OpenAI API', 'env': ['OPENAI_API_KEY', 'OPENAI_BASE_URL'], 'files': []},
 'codex': {'name': 'OpenAI Codex', 'env': ['OPENAI_API_KEY'], 'files': ['.codex/auth.json', '.codex/config.toml'], 'notice': 'File-based account login can migrate; OS keyring login may need sign-in.'},
 'chatgpt': {'name': 'ChatGPT', 'env': [], 'files': [], 'notice': 'Browser/desktop account sign-in required; API keys do not sign into ChatGPT.'},
 'gemini': {'name': 'Google Gemini', 'env': ['GEMINI_API_KEY', 'GOOGLE_API_KEY'], 'files': ['.gemini/settings.json', '.gemini/oauth_creds.json']},
 'antigravity': {'name': 'Antigravity', 'env': [], 'files': ['.gemini/antigravity/mcp_config.json'], 'notice': 'MCP configuration only; native account/keyring sign-in requires the application.'},
 'claude-code': {'name': 'Claude Code CLI', 'env': ['CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_API_KEY'], 'files': ['.claude.json', '.claude/settings.json', '.claude/.credentials.json']},
 'claude-desktop': {'name': 'Claude Desktop', 'env': [], 'files': ['.config/Claude/claude_desktop_config.json'], 'notice': 'MCP configuration only; desktop account sign-in requires the application.'},
 'opencode': {'name': 'OpenCode', 'env': [], 'files': ['.config/opencode/opencode.json', '.config/opencode/opencode.jsonc', '.local/share/opencode/auth.json', '.local/share/opencode/mcp-auth.json']},
 'openrouter': {'name': 'OpenRouter', 'env': ['OPENROUTER_API_KEY'], 'files': []},
 'ollama': {'name': 'Ollama', 'env': ['OLLAMA_HOST'], 'files': []},
 'lm-studio': {'name': 'LM Studio', 'env': ['OPENAI_BASE_URL', 'OPENAI_API_KEY'], 'files': [], 'notice': 'Enter the target-accessible server URL; local model installation is separate.'},
 'muse': {'name': 'Muse', 'env': [], 'files': [], 'notice': 'Native adapter needs the exact application identity; custom environment/config supported.'},
 'grokbot': {'name': 'Grokbot', 'env': [], 'files': [], 'notice': 'Native adapter needs the exact application identity; custom environment/config supported.'},
 'deepseek-harness': {'name': 'DeepSeekHarness', 'env': [], 'files': [], 'notice': 'Native adapter needs the exact application identity; custom environment/config supported.'},
}
_NAME = re.compile(r'^[A-Z][A-Z0-9_]{2,63}$')
_TARGET = re.compile(r'^(substrate|baseline|(vm|ct|kasm):(?:\*|[A-Za-z0-9][A-Za-z0-9_.-]{0,63}))$')

class SetupError(ValueError):
    pass


def choice(plan):
    raw = plan.get('host_configuration', {}).get('ai_setup')
    if raw is None:
        return {'mode': 'none', 'providers': [], 'targets': [], 'profile': PROFILE}
    if not isinstance(raw, dict) or not {'mode', 'providers', 'targets', 'profile'} <= set(raw) <= {'mode', 'providers', 'targets', 'profile', 'profile_sha256', 'claude_history'}:
        raise SetupError('AI setup stores only mode, provider IDs, target grants and a vault profile reference')
    if type(raw.get('claude_history', False)) is not bool:
        raise SetupError('Claude Code history choice must be a boolean')
    if 'profile_sha256' in raw and (not isinstance(raw['profile_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', raw['profile_sha256'])):
        raise SetupError('invalid encrypted AI profile fingerprint')
    if raw['mode'] not in ('none', 'parent', 'custom') or raw['profile'] != PROFILE:
        raise SetupError('invalid AI setup mode or vault profile reference')
    if not isinstance(raw['providers'], list) or any(p not in CATALOG for p in raw['providers']):
        raise SetupError('unknown AI provider selection')
    if not isinstance(raw['targets'], list) or any(not isinstance(t, str) or not _TARGET.fullmatch(t) for t in raw['targets']):
        raise SetupError('invalid AI setup target grant')
    if raw['mode'] != 'none' and (not raw['providers'] or not raw['targets']):
        raise SetupError('select AI providers and permitted targets')
    return raw


def _relative(name):
    p = Path(name)
    if not isinstance(name, str) or not name or p.is_absolute() or '..' in p.parts or '\\' in name or '\x00' in name:
        raise SetupError('AI files must have safe home-relative paths')
    if not (name.startswith(('.codex/', '.claude/', '.gemini/', '.config/', '.local/share/', '.baseline/')) or name == '.claude.json'):
        raise SetupError('AI file path is outside supported configuration folders')
    return name


def validate_profile(profile):
    if not isinstance(profile, dict) or set(profile) != {'providers', 'mcp'} or not isinstance(profile['providers'], dict) or not isinstance(profile['mcp'], dict):
        raise SetupError('AI profile must contain provider configurations and MCP settings')
    for ident, row in profile['providers'].items():
        if ident not in CATALOG or not isinstance(row, dict) or set(row) != {'env', 'files'} or not isinstance(row['env'], dict) or not isinstance(row['files'], dict):
            raise SetupError('invalid AI provider configuration')
        for name, value in row['env'].items():
            if not _NAME.fullmatch(name) or name in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONPATH', 'PATH', 'HOME', 'BASH_ENV', 'ENV') or not isinstance(value, str) or '\x00' in value:
                raise SetupError('invalid AI environment setting')
        for name, encoded in row['files'].items():
            _relative(name)
            try:
                base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise SetupError('AI config files must be base64 encoded') from None
    if len(json.dumps(profile).encode()) > MAX_BYTES:
        raise SetupError('AI profile exceeds 1 MiB')
    return profile


def save_profile(store, name, profile, passphrase):
    profile = with_mcp(validate_profile(profile))
    if name != PROFILE:
        raise SetupError('invalid AI profile name')
    if not store.has_passphrase():
        raise SetupError('set the USER_ADMIN vault passphrase before saving AI setup')
    if not store.check_passphrase(passphrase):
        raise vault.WrongPassphrase('wrong passphrase')
    store._write(name, vault_crypto.seal(json.dumps(profile, separators=(',', ':')), passphrase))


def load_profile(store, name=PROFILE, passphrase=None):
    value = store.get(name, passphrase=passphrase)
    if value is None:
        raise SetupError('AI profile is missing from the USER_ADMIN vault')
    try:
        return validate_profile(json.loads(value))
    except (ValueError, TypeError, UnicodeError):
        raise SetupError('AI profile is invalid; no values were displayed') from None


def discover(home, environ=None):
    """Metadata only; discovery never opens auth files or returns credential values."""
    env = os.environ if environ is None else environ
    root = Path(home)
    return [dict(id=ident, name=row['name'], files=[f for f in row['files'] if (root / f).is_file() and not (root / f).is_symlink()],
                 environment=[n for n in row['env'] if env.get(n)], notice=row.get('notice', '')) for ident, row in CATALOG.items()]


def import_parent(home, selected, environ=None):
    """Application runtime operation; caller seals the returned profile immediately."""
    env = os.environ if environ is None else environ
    root = Path(home)
    result = {'providers': {}, 'mcp': {}}
    for ident in selected:
        if ident not in CATALOG:
            raise SetupError('unknown parent AI provider')
        row = CATALOG[ident]
        files = {}
        for rel in row['files']:
            p = root / rel
            if p.is_symlink() or any(parent.is_symlink() for parent in p.parents if parent != root):
                raise SetupError('parent AI config path contains a symbolic link')
            if p.exists():
                if not p.is_file() or p.stat().st_size > MAX_BYTES:
                    raise SetupError('parent AI config is not a bounded regular file')
                files[rel] = base64.b64encode(p.read_bytes()).decode()
        result['providers'][ident] = {'env': {n: env[n] for n in row['env'] if env.get(n)}, 'files': files}
    return validate_profile(result)


def materialize(profile, runtime):
    """Private RAM tree; caller must use /run in production. No persistent HOME writes."""
    validate_profile(profile)
    root = Path(runtime)
    if root.is_symlink():
        raise SetupError('runtime profile directory cannot be a symlink')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    env = {}
    seen = {}
    for ident, row in profile['providers'].items():
        for name, value in row['env'].items():
            if name in env and env[name] != value:
                raise SetupError('selected providers have conflicting environment settings; launch one provider at a time')
            env[name] = value
        for rel, encoded in row['files'].items():
            if rel in seen and seen[rel] != encoded:
                raise SetupError('selected providers have conflicting native files')
            seen[rel] = encoded
    for rel, encoded in seen.items():
        dest = root / 'home' / _relative(rel)
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if dest.is_symlink() or any(p.is_symlink() for p in dest.parents if p != root):
            raise SetupError('runtime file path contains a symbolic link')
        dest.write_bytes(base64.b64decode(encoded)); dest.chmod(0o600)
    for name, value in [('environment.json', env), ('mcp.json', profile['mcp'])]:
        dest = root / name
        if dest.is_symlink():
            raise SetupError('runtime file cannot be a symlink')
        dest.write_text(json.dumps(value)); dest.chmod(0o600)
    return {'providers': sorted(profile['providers']), 'native_files': len(seen), 'authenticated': False}


def apply_plan(plan, user_admin, *, source_vault=None):
    """Offline executor: copied bytes are encrypted; never asks a build process to decrypt."""
    selected = choice(plan)
    import claude_history
    history = claude_history.apply_plan(plan, user_admin)
    if selected.get('claude_history'):
        history['workspace'] = claude_history.prepare_workspace(__import__('installer_inputs').source_root(__file__), claude_history.data_root(user_admin))
    if selected['mode'] == 'none':
        admin = Path(user_admin)
        if 'ai_setup' in plan.get('host_configuration', {}) and admin.is_dir() and not admin.is_symlink():
            import write_once
            write_once.write_if_changed(admin / 'ai-setup.json', json.dumps(selected, sort_keys=True) + '\n', mode=0o600)
        return {'state': 'not requested', 'claude_history': history}
    admin = Path(user_admin)
    if admin.is_symlink() or not admin.is_dir():
        raise SetupError('AI setup requires the verified USER_ADMIN mount')
    source = vault.Vault(source_vault or vault.build_aware_roots()[0])
    source._folder()
    if not source.has_passphrase():
        raise SetupError('parent AI setup vault is not sealed; prepare AI setup first')
    envelope = source.root / selected['profile']
    if envelope.is_symlink() or not envelope.is_file() or not envelope.read_text().startswith(vault_crypto.PREFIX):
        raise SetupError('prepare the selected encrypted AI profile before building')
    if selected.get('profile_sha256') and __import__('hashlib').sha256(envelope.read_bytes()).hexdigest() != selected['profile_sha256']:
        raise SetupError('prepared AI profile changed; capture a new installer plan before building')
    destination = vault.Vault(admin / 'vault')
    destination._folder(create=True)
    verifier = source.root / vault.VERIFIER
    if verifier.is_symlink() or not verifier.is_file():
        raise SetupError('source vault verifier is not a regular file')
    target_verifier = destination.root / vault.VERIFIER
    if target_verifier.exists() and (target_verifier.is_symlink() or target_verifier.read_bytes() != verifier.read_bytes()):
        raise SetupError('child uses a different vault; unlock and re-seal its AI profile before rebuilding')
    if source.root.resolve() != destination.root.resolve():
        if not target_verifier.exists():
            destination._write_file(target_verifier, verifier.read_text().strip())
        destination._write(selected['profile'], envelope.read_text().strip())
    import write_once
    write_once.write_if_changed(admin / 'ai-setup.json', json.dumps(selected, sort_keys=True) + '\n', mode=0o600)
    return {'state': 'prepared', 'providers': selected['providers'], 'targets': selected['targets'], 'requires_vault_unlock': True, 'claude_history': history}


def permitted(config, target):
    if target in config['targets']:
        return True
    kind, sep, _name = target.partition(':')
    return bool(sep and kind + ':*' in config['targets'])


def selected_profile(profile, config):
    if set(config['providers']) - set(profile['providers']):
        raise SetupError('selected provider settings are missing; prepare the AI profile again')
    return {'providers': {k: v for k, v in profile['providers'].items() if k in config['providers']}, 'mcp': profile['mcp']}


def delivery(profile, *, account=None):
    import ai_runtime
    source = Path(ai_runtime.__file__).read_text()
    request = {'profile': validate_profile(profile), 'source': source, 'account': account}
    return ['python3', '-c', source + '\nreceive()\n'], json.dumps(request).encode()


def runtime_profile(config, *, lookup=vault.lookup):
    value = lookup(config['profile'])
    if not value:
        raise SetupError('unlock the USER_ADMIN vault before activating AI setup')
    try:
        profile = validate_profile(json.loads(value))
    except (ValueError, TypeError):
        raise SetupError('AI profile is unavailable or invalid') from None
    missing = set(config['providers']) - set(profile['providers'])
    if missing:
        raise SetupError('prepare the selected provider configurations before delivery')
    return selected_profile(profile, config)


def with_mcp(profile):
    """Custom MCP entries are complete native documents, not a pretend universal schema."""
    paths = {'codex': '.codex/config.toml', 'claude-code': '.claude.json', 'claude-desktop': '.config/Claude/claude_desktop_config.json',
             'gemini': '.gemini/settings.json', 'antigravity': '.gemini/antigravity/mcp_config.json', 'opencode': '.config/opencode/opencode.json'}
    result = json.loads(json.dumps(profile))
    for ident, document in profile['mcp'].items():
        if ident not in paths or ident not in result['providers']:
            raise SetupError('select a supported client for native MCP configuration')
        if ident == 'codex':
            import tomllib
            if not isinstance(document, str):
                raise SetupError('Codex MCP configuration is a complete native TOML document')
            try:
                tomllib.loads(document)
            except ValueError:
                raise SetupError('invalid native Codex TOML configuration') from None
            data = document.encode()
        else:
            if not isinstance(document, dict):
                raise SetupError('native MCP configuration must be a JSON object')
            data = json.dumps(document).encode()
        result['providers'][ident]['files'][paths[ident]] = base64.b64encode(data).decode()
    return validate_profile(result)


def client_environment(provider, *, runtime="/run/baseline-ai", current=None):
    """Host clients consume only an already unlocked profile, without live API calls."""
    import ai_runtime
    base_env = dict(os.environ if current is None else current)
    path = Path(runtime) / str(os.getuid()) / "profile.json"
    if not path.is_file() or path.is_symlink():
        return base_env
    try:
        profile = validate_profile(json.loads(path.read_text()))
        if provider not in profile['providers']:
            return base_env
        root = Path(runtime) / str(os.getuid())
        # No cross-provider environment merge: each client has its own HOME.
        return {**base_env, **ai_runtime.environment(profile, provider, root), "BASELINE_AI_PROFILE": provider}
    except (OSError, ValueError):
        raise SetupError('unlocked AI provider configuration is unavailable') from None


def configured(var_names, *, runtime='/run/baseline-ai'):
    """Presence-only host status; never promotes a stored credential to live access."""
    path = Path(runtime) / str(os.getuid()) / 'profile.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        return False
    try:
        profile = validate_profile(json.loads(path.read_text()))
    except (OSError, ValueError):
        raise SetupError('active AI profile is unreadable or invalid') from None
    if any(row['env'].get(name) for row in profile['providers'].values() for name in var_names):
        return True
    return (('OPENAI_API_KEY' in var_names and '.codex/auth.json' in profile['providers'].get('codex', {}).get('files', {}))
            or ('CLAUDE_CODE_OAUTH_TOKEN' in var_names and '.claude/.credentials.json' in profile['providers'].get('claude-code', {}).get('files', {})))
