# Copyright (c) 2021-2023 Wind River Systems, Inc.
#
# The right to copy, distribute, modify, or otherwise make use
# of this software may be licensed only pursuant to the terms
# of an applicable Wind River license agreement.

"""Tests for Backup NFS driver."""

import os
import stat
from unittest import mock

import ddt
from os_brick import exception as brick_exception
from os_brick.remotefs import remotefs as remotefs_brick
from oslo_config import cfg

from cinder.backup.backup_context import BackupContext
from cinder.backup.drivers import multitenant_nfs as mtnfs
from cinder import context
from cinder import test
from cinder.tests.unit import fake_constants as fake

CONF = cfg.CONF

FAKE_BACKUP_MOUNT_POINT_BASE = '/fake/mount-point-base'
FAKE_HOST = 'fake_host'
FAKE_EXPORT_PATH = 'fake/export/path'
FAKE_BACKUP_LOCATION = '%s:/%s' % (FAKE_HOST, FAKE_EXPORT_PATH)
FAKE_BACKUP_PATH = os.path.join(FAKE_BACKUP_MOUNT_POINT_BASE,
                                FAKE_EXPORT_PATH)
FAKE_BACKUP_ID = fake.BACKUP_ID
FAKE_BACKUP_ID_PART1 = fake.BACKUP_ID[:2]
FAKE_BACKUP_ID_PART2 = fake.BACKUP_ID[2:4]
FAKE_BACKUP_ID_REST = fake.BACKUP_ID[4:]
UPDATED_CONTAINER_NAME = os.path.join(FAKE_BACKUP_ID_PART1,
                                      FAKE_BACKUP_ID_PART2,
                                      FAKE_BACKUP_ID)
FAKE_EGID = 1234


@ddt.ddt
class BackupNFSShareTestCase(test.TestCase):

    def setUp(self):
        super(BackupNFSShareTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.mock_object(mtnfs, 'LOG')
        # Note(yikun): It mocks out the backup notifier to avoid to leak
        # notifications into other test.
        notify_patcher = mock.patch(
            'cinder.volume.volume_utils.notify_about_backup_usage')
        notify_patcher.start()
        self.addCleanup(notify_patcher.stop)

    def test_backup_location(self):
        self.mock_object(mtnfs.MultiTenantNFSBackupDriver,
                         '_init_backup_repo_path',
                         return_value=FAKE_BACKUP_PATH)
        context = BackupContext(location=FAKE_BACKUP_LOCATION)
        driver = mtnfs.MultiTenantNFSBackupDriver(self.ctxt,
                                                  backup_context=context)
        self.assertEqual(FAKE_BACKUP_LOCATION, driver.backup_location)

    def test_check_configuration(self):
        self.mock_object(mtnfs.MultiTenantNFSBackupDriver,
                         '_init_backup_repo_path',
                         return_value=FAKE_BACKUP_PATH)
        context = BackupContext(location=FAKE_BACKUP_LOCATION)
        driver = mtnfs.MultiTenantNFSBackupDriver(self.ctxt,
                                                  backup_context=context)
        driver.check_for_setup_error()
        self.assertTrue(True)

    @mock.patch('os.getegid', return_value=FAKE_EGID)
    @mock.patch('cinder.utils.get_file_gid')
    @mock.patch('cinder.utils.get_file_mode')
    @ddt.data((FAKE_EGID, 0),
              (FAKE_EGID, stat.S_IWGRP),
              (6666, 0),
              (6666, stat.S_IWGRP))
    @ddt.unpack
    def test_init_backup_repo_path(self,
                                   file_gid,
                                   file_mode,
                                   mock_get_file_mode,
                                   mock_get_file_gid,
                                   mock_getegid):
        self.override_config('backup_mount_point_base',
                             FAKE_BACKUP_MOUNT_POINT_BASE)
        mock_remotefsclient = mock.Mock()
        mock_remotefsclient.get_mount_point = mock.Mock(
            return_value=FAKE_BACKUP_PATH)
        self.mock_object(mtnfs.MultiTenantNFSBackupDriver,
                         'check_for_setup_error')
        self.mock_object(remotefs_brick, 'RemoteFsClient',
                         return_value=mock_remotefsclient)

        with mock.patch.object(mtnfs.MultiTenantNFSBackupDriver,
                               '_init_backup_repo_path'):
            context = BackupContext(location=FAKE_BACKUP_LOCATION)
            driver = mtnfs.MultiTenantNFSBackupDriver(self.ctxt,
                                                      backup_context=context)

        mock_get_file_gid.return_value = file_gid
        mock_get_file_mode.return_value = file_mode
        mock_execute = self.mock_object(driver, '_execute')

        path = driver._init_backup_repo_path()

        self.assertEqual(FAKE_BACKUP_PATH, path)
        mock_remotefsclient.mount.assert_called_once_with(FAKE_BACKUP_LOCATION)
        mock_remotefsclient.get_mount_point.assert_called_once_with(
            FAKE_BACKUP_LOCATION)

        mock_execute_calls = []
        if file_gid != FAKE_EGID:
            mock_execute_calls.append(
                mock.call('chgrp',
                          '-R',
                          FAKE_EGID,
                          path,
                          root_helper=driver._root_helper,
                          run_as_root=True))

        if not (file_mode & stat.S_IWGRP):
            mock_execute_calls.append(
                mock.call('chmod',
                          '-R',
                          'g+w',
                          path,
                          root_helper=driver._root_helper,
                          run_as_root=True))

        mock_execute.assert_has_calls(mock_execute_calls, any_order=True)
        self.assertEqual(len(mock_execute_calls), mock_execute.call_count)

    def test_init_backup_repo_path_unconfigured(self):
        """RemoteFsClient is not created if backup_location is unset"""

        mock_remotefsclient = mock.Mock()
        self.mock_object(remotefs_brick, 'RemoteFsClient')

        driver = mtnfs.MultiTenantNFSBackupDriver(self.ctxt)
        driver._init_backup_repo_path()

        self.assertEqual(0, mock_remotefsclient.call_count)

    @mock.patch('time.sleep')
    def test_init_backup_repo_path_mount_retry(self, mock_sleep):
        self.override_config('backup_mount_attempts', 2)

        mock_remotefsclient = mock.Mock()
        self.mock_object(remotefs_brick, 'RemoteFsClient',
                         return_value=mock_remotefsclient)

        mock_remotefsclient.mount.side_effect = [
            brick_exception.BrickException] * 2
        with mock.patch.object(mtnfs.MultiTenantNFSBackupDriver,
                               '_init_backup_repo_path'):
            context = BackupContext(location=FAKE_BACKUP_LOCATION)
            driver = mtnfs.MultiTenantNFSBackupDriver(self.ctxt,
                                                      backup_context=context)

        self.assertRaises(brick_exception.BrickException,
                          driver._init_backup_repo_path)
        self.assertEqual([mock.call(FAKE_BACKUP_LOCATION),
                          mock.call(FAKE_BACKUP_LOCATION)],
                         mock_remotefsclient.mount.call_args_list)
