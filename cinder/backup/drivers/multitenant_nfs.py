#
# Copyright (c) 2021-2023 Wind River Systems, Inc.
#
# The right to copy, distribute, modify, or otherwise make use
# of this software may be licensed only pursuant to the terms
# of an applicable Wind River license agreement.
#

"""
Implementation of a multi tenant backup service that uses NFS storage
as the backend.
"""

import os
import stat

from os_brick import exception as brick_exception
from os_brick.remotefs import remotefs as remotefs_brick
from oslo_concurrency import processutils as putils
from oslo_config import cfg
from oslo_log import log as logging

from cinder.backup.drivers import posix
from cinder import interface
from cinder import utils

LOG = logging.getLogger(__name__)


nfsbackup_service_opts = [
    cfg.StrOpt('backup_mount_point_base',
               default='$state_path/backup_mount',
               help='Base dir containing mount point for NFS share.'),
    cfg.StrOpt('backup_mount_options',
               default=None,
               help=('Mount options passed to the NFS client. See NFS '
                     'man page for details.')),
    cfg.IntOpt('backup_mount_attempts',
               min=1,
               default=3,
               help='The number of attempts to mount NFS shares before '
                    'raising an error.'),
]

CONF = cfg.CONF
CONF.register_opts(nfsbackup_service_opts)


@interface.backupdriver
class MultiTenantNFSBackupDriver(posix.PosixBackupDriver):
    """Provides backup, restore and delete using NFS supplied repository."""
    backup_context_required = True

    def __init__(self, context, db=None, backup_context=None):
        self.backup_mount_point_base = CONF.backup_mount_point_base
        self.mount_options = CONF.backup_mount_options
        self.backup_location = getattr(backup_context, "location", None)
        self._execute = putils.execute
        self._root_helper = utils.get_root_helper()
        backup_path = self._init_backup_repo_path()
        LOG.debug("Using NFS backup repository: %s", backup_path)
        super(MultiTenantNFSBackupDriver, self).__init__(
            context, backup_path=backup_path)

    def check_for_setup_error(self):
        return

    def _init_backup_repo_path(self):
        if self.backup_location is None:
            LOG.info("_init_backup_repo_path: "
                     "backup_location is not set in backup context.")
            return

        remotefsclient = remotefs_brick.RemoteFsClient(
            'nfs',
            self._root_helper,
            nfs_mount_point_base=self.backup_mount_point_base,
            nfs_mount_options=self.mount_options)

        @utils.retry(
            (brick_exception.BrickException, putils.ProcessExecutionError),
            retries=CONF.backup_mount_attempts)
        def mount():
            remotefsclient.mount(self.backup_location)

        mount()
        # Ensure we can write to this share
        mount_path = remotefsclient.get_mount_point(self.backup_location)

        group_id = os.getegid()
        current_group_id = utils.get_file_gid(mount_path)
        current_mode = utils.get_file_mode(mount_path)

        if group_id != current_group_id:
            cmd = ['chgrp', '-R', group_id, mount_path]
            self._execute(*cmd, root_helper=self._root_helper,
                          run_as_root=True)

        if not (current_mode & stat.S_IWGRP):
            cmd = ['chmod', '-R', 'g+w', mount_path]
            self._execute(*cmd, root_helper=self._root_helper,
                          run_as_root=True)

        return mount_path
