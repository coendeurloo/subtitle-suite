# -*- coding: utf-8 -*-
"""Small, Kodi-independent helpers for safe file replacement."""

import os
import uuid


class AtomicReplaceError(RuntimeError):
    """Raised when a staged replacement cannot be completed safely."""


def same_directory_temp_path(target_path, suffix='.tmp'):
    """Return a unique hidden path beside *target_path*.

    Keeping the staged file in the target directory lets the caller use an
    atomic rename operation without crossing filesystems.
    """
    directory = os.path.dirname(target_path)
    filename = os.path.basename(target_path)
    return os.path.join(directory, '.%s.%s%s' % (filename, uuid.uuid4().hex, suffix))


def copy_and_replace_atomically(
    source_path,
    target_path,
    copy_file,
    replace_file,
    get_size,
    validate_file,
    remove_file,
    temp_path_factory=same_directory_temp_path,
):
    """Stage, verify, and atomically replace a file through injected I/O.

    The supplied adapters keep this helper independent of Kodi's VFS and make
    the safety contract testable with the standard library.  If copying,
    validation, or replacement fails, this function never asks the caller to
    remove the original target.
    """
    staged_path = temp_path_factory(target_path)
    try:
        if not copy_file(source_path, staged_path):
            raise AtomicReplaceError('staging copy failed')

        if get_size(staged_path) <= 0:
            raise AtomicReplaceError('staged file is empty')

        validate_file(staged_path)

        if not replace_file(staged_path, target_path):
            raise AtomicReplaceError('atomic replace failed')

        staged_path = ''
    finally:
        if staged_path:
            try:
                remove_file(staged_path)
            except Exception:
                pass
