"""Private, atomic, no-clobber POSIX artifact writes with held directory handles."""
import os
from pathlib import Path
import secrets

from .catalog import CatalogError


def _path(output):
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise CatalogError("Safe artifact output requires a POSIX filesystem.")
    try:
        path = Path(output).absolute()
        if ".." in path.parts or path.name in ("", ".", "..") or "\x00" in str(path):
            raise ValueError
        return path
    except (TypeError, ValueError):
        raise CatalogError("The output location is not supported.") from None


def _parent(path, *, create):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:-1]:
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    os.close(fd)
                    return None
                os.mkdir(part, 0o700, dir_fd=fd)
                child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def preflight_outputs(outputs):
    paths = [_path(output) for output in outputs]
    if len(set(paths)) != len(paths) or any(a != b and a.is_relative_to(b) for a in paths for b in paths):
        raise CatalogError("Output destinations must be distinct and cannot contain one another.")
    try:
        for path in paths:
            fd = _parent(path, create=False)
            if fd is None:
                continue
            try:
                try:
                    os.stat(path.name, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise CatalogError("An output destination already exists. Choose a new file.")
            finally:
                os.close(fd)
    except (OSError, ValueError):
        raise CatalogError("Output preflight failed. Choose new files without symbolic-link directories.") from None


def write_private_bytes(content: bytes, output) -> None:
    path = _path(output)
    directory = None
    temporary = None
    try:
        directory = _parent(path, create=True)
        candidate = ".maintenance-" + secrets.token_hex(12) + ".tmp"
        fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        temporary = candidate
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as target:
                fd = None
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
        finally:
            if fd is not None:
                os.close(fd)
        os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    except (OSError, ValueError, TypeError):
        raise CatalogError("Unable to create a private artifact without replacing existing content.") from None
    finally:
        if directory is not None:
            try:
                if temporary is not None:
                    os.unlink(temporary, dir_fd=directory)
            except OSError:
                raise CatalogError("Unable to finish private artifact cleanup.") from None
            finally:
                os.close(directory)
