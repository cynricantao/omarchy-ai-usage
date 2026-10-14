"""Owner-private storage. Refuse unsafe state instead of chmoding foreign targets.

Protection is against other Unix users, not malicious code running as this user.
Source directories are read-only inputs and are deliberately not chmoded.
"""
import os
from pathlib import Path
import stat

# systemd user managers can remap root-owned ancestors inside their sandbox, so
# "/" and "/home" may report as the kernel's unmapped/overflow uid instead of 0.
# That uid is never a value this user owns; accept it only for non-leaf
# ancestors, which are additionally required to be non-writable.
OVERFLOW_UIDS = frozenset((65534, 4294967294))


def private_dir(path):
    path = Path(os.path.abspath(os.fspath(path)))
    # Inspect every component without resolving away symlinks. Missing parents
    # are created individually with 0700; existing ancestors are never changed.
    components = list(reversed(path.parents)) + [path]
    for component in components:
        try:
            info = component.lstat()
        except FileNotFoundError:
            component.mkdir(mode=0o700)
            info = component.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('storage path contains a non-directory or symlink')
        if component == path:
            # The private leaf must be owned by this user and unreadable to others.
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('storage directory must be owned by this user with mode 0700')
            continue
        # Ancestors may be root-owned, or appear as the kernel's unmapped
        # overflow uid when a user namespace or systemd sandbox remaps root.
        # Any other owner is unexpected and refused, as is any non-sticky
        # ancestor we could modify.
        if info.st_uid not in (0, os.getuid()) and info.st_uid not in OVERFLOW_UIDS:
            raise ValueError('storage ancestor has unexpected ownership')
        if info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
            raise ValueError('storage ancestor is writable by another user')
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('storage directory must be owned by this user with mode 0700')
    return path


def check_file(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise ValueError('storage file must be an owned regular file without links')
    if info.st_mode & 0o077:
        raise ValueError('storage file must have private permissions')


def private_file(path):
    path = Path(path)
    private_dir(path.parent)
    # O_NOFOLLOW rejects a symlink atomically; fstat checks the opened inode.
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError('storage file must be private and owned without links')
    except BaseException:
        os.close(fd)
        raise
    return fd
