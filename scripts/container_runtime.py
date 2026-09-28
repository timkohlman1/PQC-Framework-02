#!/usr/bin/env python3
"""Container-private identity setup, then irreversible drop to the host UID/GID.

The development image runs this installed file with Python's -I flag, never a
workspace import, before executing repository code. Only the container account
files, a new private home and two verified empty overlay mount roots are changed
while root. Host bind trees are never recursively chowned or chmodded.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Mapping

OVERLAYS = (Path('/workspace/build'), Path('/workspace/.pqc-generated-state'))


class RuntimeSetupError(RuntimeError):
    """Unsafe or incomplete runtime setup; no workload may be started."""


def _number(value: str, label: str, *, allow_zero: bool = False) -> int:
    if not re.fullmatch(r'[0-9]{1,10}', value):
        raise RuntimeSetupError(f'{label} must be a numeric Linux identity')
    number = int(value)
    if not (0 if allow_zero else 1) <= number < 4294967295:
        raise RuntimeSetupError(f'{label} must be a valid non-root identity')
    return number


def read_identity(env: Mapping[str, str]) -> tuple[int, int, list[int], int]:
    uid = _number(env.get('PQC_RUNTIME_UID', ''), 'PQC_RUNTIME_UID')
    gid = _number(env.get('PQC_RUNTIME_GID', ''), 'PQC_RUNTIME_GID')
    groups = sorted({gid, *(_number(v, 'PQC_RUNTIME_GROUPS', allow_zero=True)
                           for v in env.get('PQC_RUNTIME_GROUPS', str(gid)).split())})
    mask = env.get('PQC_RUNTIME_UMASK', '0022')
    if not re.fullmatch(r'0?[0-7]{3}', mask):
        raise RuntimeSetupError('PQC_RUNTIME_UMASK must be an octal permission mask')
    return uid, gid, groups, int(mask, 8)


def prepare_account(uid: int, gid: int, home: Path, *, etc: Path = Path('/etc')) -> str:
    """Supply a passwd home for OpenSSH/tilde lookup, including UID collisions.

    Only the temporary container's account files are edited. No host account
    databases are mounted and no host login name or password is imported.
    """
    passwd = etc / 'passwd'
    rows = [line.split(':') for line in passwd.read_text().splitlines()]
    matching = [row for row in rows if len(row) == 7 and row[2] == str(uid)]
    if len(matching) > 1:
        raise RuntimeSetupError('container passwd contains duplicate target UIDs')
    if matching:
        row = matching[0]
        name = row[0]
        row[3], row[5], row[6] = str(gid), str(home), '/bin/sh'
    else:
        name = f'pqc-{uid}'
        if any(row[0] == name for row in rows):
            raise RuntimeSetupError('container runtime account name collision')
        rows.append([name, 'x', str(uid), str(gid), 'PQC runtime', str(home), '/bin/sh'])
    group = etc / 'group'
    group_rows = [line.split(':') for line in group.read_text().splitlines()]
    if not any(len(row) == 4 and row[2] == str(gid) for row in group_rows):
        group_name = f'pqc-{gid}'
        if any(row[0] == group_name for row in group_rows):
            raise RuntimeSetupError('container runtime group name collision')
        group_rows.append([group_name, 'x', str(gid), ''])
    passwd.write_text(''.join(':'.join(row) + '\n' for row in rows))
    group.write_text(''.join(':'.join(row) + '\n' for row in group_rows))
    return name


def _mountpoints(mountinfo: Path) -> set[Path]:
    # mountinfo escapes whitespace/backslashes as octal sequences.
    result = set()
    for line in mountinfo.read_text().splitlines():
        fields = line.split()
        if len(fields) >= 6:
            value = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[4])
            result.add(Path(value))
    return result


def prepare_overlays(uid: int, gid: int, *, paths: tuple[Path, ...] = OVERLAYS,
                     mountinfo: Path = Path('/proc/self/mountinfo')) -> None:
    """Only chown empty, real, separately mounted roots, never their contents."""
    mounts = _mountpoints(mountinfo)
    handles = []
    try:
        # Validate both before changing either; a missing overlay must not turn
        # into a chown of the corresponding host bind directory.
        for path in paths:
            if path not in mounts or path.resolve() != path:
                raise RuntimeSetupError(f'isolated output is not a real mount: {path}')
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            handles.append(fd)
            if os.listdir(fd):
                raise RuntimeSetupError(f'isolated output mount must start empty: {path}')
        for fd in handles:
            os.fchown(fd, uid, gid)
    finally:
        for fd in handles:
            os.close(fd)


def copy_ssh(source: Path, home: Path) -> None:
    """Copy runtime SSH state after dropping root; never chmod symlink targets."""
    destination = home / '.ssh'
    shutil.copytree(source, destination, symlinks=True)
    destination.chmod(0o700)
    for directory, dirs, files in os.walk(destination, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                continue
            if stat.S_ISDIR(mode):
                path.chmod(0o700)
            elif stat.S_ISREG(mode):
                path.chmod(0o600)
            else:
                raise RuntimeSetupError('unsupported special file in runtime SSH copy')


def main(argv: list[str] | None = None) -> int:
    command = list(sys.argv[1:] if argv is None else argv)
    try:
        uid, gid, groups, mask = read_identity(os.environ)
        if not command:
            raise RuntimeSetupError('no container workload was supplied')
        if os.geteuid() != 0:
            raise RuntimeSetupError('identity bootstrap must start as container root')
        for flag in ('PQC_RUNTIME_ISOLATED', 'PQC_CONTAINER_ENABLE_GATEWAY'):
            if os.environ.get(flag, '0') not in {'0', '1'}:
                raise RuntimeSetupError(f'{flag} must be 0 or 1')
        home = Path(tempfile.mkdtemp(prefix='pqc-home-', dir='/tmp'))
        name = prepare_account(uid, gid, home)
        os.chown(home, uid, gid)
        if os.environ.get('PQC_RUNTIME_ISOLATED') == '1':
            prepare_overlays(uid, gid)
        os.setgroups(groups)
        os.setresgid(gid, gid, gid)
        os.setresuid(uid, uid, uid)
        if os.getresuid() != (uid, uid, uid) or os.getresgid() != (gid, gid, gid):
            raise RuntimeSetupError('container privilege drop did not take effect')
        os.environ.update(HOME=str(home), USER=name, LOGNAME=name,
                          XDG_CACHE_HOME=str(home / '.cache'))
        os.umask(mask)
        if os.environ.get('PQC_CONTAINER_ENABLE_GATEWAY') == '1':
            copy_ssh(Path('/host-ssh'), home)
        # No root fallback. Command argument boundaries and exit status survive
        # exec; any permission failure is handled as the invoking user.
        os.execvp(command[0], command)
    except (OSError, RuntimeSetupError) as exc:
        print(f'PQC container startup failed: {exc}. Use ./scripts/dev.sh as a '
              'non-root user; rebuild with ./scripts/dev.sh build-image after '
              'runtime changes. Repair old root-owned output explicitly; do not '
              'run the workload with sudo.', file=sys.stderr)
        return 126
    return 126


if __name__ == '__main__':
    raise SystemExit(main())
