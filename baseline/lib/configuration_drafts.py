"""Durable, owner-scoped configuration drafts; saving never applies a plan."""
import json
from contextlib import contextmanager
import os
import sqlite3
import time
from pathlib import Path


class DraftError(ValueError):
    pass


class DraftConflict(DraftError):
    pass


def _validate(document):
    if not isinstance(document, dict):
        raise DraftError('Draft must be a configuration object')
    def inspect(value, depth=0):
        if depth > 32:
            raise DraftError('Draft nesting exceeds 32 levels')
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise DraftError('Draft keys must be strings')
                if key.lower() in {'password', 'passphrase', 'secret', 'token', 'private_key', 'authorization', 'cookie'}:
                    raise DraftError('Credentials cannot be stored in configuration drafts')
                inspect(item, depth+1)
        elif isinstance(value, list):
            for item in value:
                inspect(item, depth+1)
    inspect(document)
    try:
        encoded = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    except (TypeError, ValueError, RecursionError) as exc:
        raise DraftError('Draft must contain finite JSON values') from exc
    if len(encoded.encode('utf-8')) > 65536:
        raise DraftError('Draft exceeds 64 KiB')
    return encoded


@contextmanager
def _connection(path):
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


class DraftStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with _connection(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS drafts (owner TEXT NOT NULL, kind TEXT NOT NULL, revision INTEGER NOT NULL, updated REAL NOT NULL, document TEXT NOT NULL, PRIMARY KEY(owner,kind))')

    @staticmethod
    def _identity(owner, kind):
        if not isinstance(owner, str) or not owner or kind not in ('installer', 'recipe', 'installer-display'):
            raise DraftError('Invalid draft owner or kind')

    @staticmethod
    def _row(kind, row):
        return None if row is None else dict(kind=kind, revision=row[0], updated=row[1], document=json.loads(row[2]), applied=False)

    def get(self, owner, kind):
        self._identity(owner, kind)
        with _connection(self.path) as db:
            row = db.execute('SELECT revision,updated,document FROM drafts WHERE owner=? AND kind=?', (owner, kind)).fetchone()
        return self._row(kind, row)

    def list(self, owner):
        return [draft for kind in ('installer', 'recipe') if (draft := self.get(owner, kind)) is not None]

    def save(self, owner, kind, document, *, expected_revision):
        self._identity(owner, kind)
        if type(expected_revision) is not int or expected_revision < 0:
            raise DraftError('A nonnegative draft revision is required')
        encoded = _validate(document)
        if kind == "installer":
            import ai_provisioning
            try:
                ai_provisioning.choice(document)
            except (ai_provisioning.SetupError, AttributeError, TypeError) as exc:
                raise DraftError("AI installer choices must contain metadata and a vault reference only") from exc
        if kind == 'installer-display':
            import installer_desktop
            try:
                installer_desktop.validate(document)
            except ValueError as exc:
                raise DraftError(str(exc)) from exc
        if kind == 'recipe' and (set(document) != {'document', 'app_document'}
                or not isinstance(document['document'], dict)
                or (document['app_document'] is not None and not isinstance(document['app_document'], dict))):
            raise DraftError('Recipe draft requires a recipe object and an optional application recipe object')
        with _connection(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT revision FROM drafts WHERE owner=? AND kind=?', (owner, kind)).fetchone()
            revision = current[0] if current else 0
            if revision != expected_revision:
                raise DraftConflict('Draft changed in another editor. Reload before saving; your local changes have not been overwritten.')
            updated = time.time()
            db.execute('INSERT INTO drafts VALUES(?,?,?,?,?) ON CONFLICT(owner,kind) DO UPDATE SET revision=excluded.revision,updated=excluded.updated,document=excluded.document',
                       (owner, kind, revision+1, updated, encoded))
        return self._row(kind, (revision+1, updated, encoded))
