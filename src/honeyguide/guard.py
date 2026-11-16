"""A guard against citing or previewing secrets: credential-looking files, and lines that look like a key.

Conservative by design: a false refusal costs an agent one rephrased citation; a false pass puts a credential on
the map page and in an export.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path, PurePosixPath

# Matched against the file name (lowercased).
SECRET_NAMES = (
    ".env", ".env.*", "*.env", ".envrc", ".netrc", "_netrc", ".npmrc", ".pypirc", ".pgpass", ".git-credentials",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx", "*.ppk", "*.asc", "*.gpg",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "credentials", "credentials.*", "*credentials*.json",
    "secrets", "secrets.*", "*.secret", "*.secrets", "service-account*.json", "*serviceaccount*.json",
    "htpasswd", ".htpasswd", "token.json", "*.token",
)
# Any directory with one of these names makes every file under it secret.
SECRET_DIRS = (".ssh", ".aws", ".gnupg", ".docker", ".kube", "secrets")
# Allowed despite the patterns above: templates that hold no values.
SAFE_NAMES = (".env.example", ".env.sample", ".env.template", ".env.dist")

SECRET_LINE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{30,}"
    r"|\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"
    r"|\bAIza[0-9A-Za-z_-]{35}\b"
)


def secret_path(path: str) -> str | None:
    """Why ``path`` (repo-relative) looks like a credential file, or None."""
    parts = PurePosixPath(path).parts
    name = parts[-1].lower() if parts else ""
    if name in SAFE_NAMES:
        return None
    for d in parts[:-1]:
        if d.lower() in SECRET_DIRS:
            return f"{path}: inside {d}/, which holds credentials"
    for pattern in SECRET_NAMES:
        if fnmatch.fnmatchcase(name, pattern):
            return f"{path}: looks like a credential file ({pattern})"
    return None


def secret_lines(lines: list[str], first: int = 1) -> list[int]:
    """1-based numbers (offset by ``first``) of lines that look like a key or token."""
    return [first + i for i, line in enumerate(lines) if SECRET_LINE.search(line)]


def check_secret(path: str, lines: list[str] | None = None, first: int = 1) -> str | None:
    """Why citing ``lines`` of ``path`` is refused, or None when it is fine."""
    why = secret_path(path)
    if why:
        return why
    if lines:
        hits = secret_lines(lines, first)
        if hits:
            return f"{path}: line {hits[0]} looks like a key or token"
    return None


def draft_dir_problem(path: str | Path, drafts_root: str | Path) -> str | None:
    """Why ``path`` may not be read as a map draft (T7.13), or None. Drafts live only under the memory store's
    ``drafts/`` directory, the one place the Cartographer may write; anything else (the target repo, a symlink
    out of the store, another repo's drafts) is refused, so ingesting can't pick up files it didn't write."""
    root = Path(drafts_root).resolve()
    try:
        real = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return f"{path}: no such directory"
    if not real.is_dir():
        return f"{path}: not a directory"
    if real != root and root not in real.parents:
        return f"{path}: drafts are read only from {root} (`honeyguide map draft-dir` prints it)"
    for f in sorted(real.iterdir()):
        target = f.resolve()
        if f.is_symlink() or (target != root and root not in target.parents):
            return f"{f}: a link out of the drafts directory; write the file itself there"
    return None
