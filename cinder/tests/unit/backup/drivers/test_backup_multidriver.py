#
# Copyright (c) 2021-2023 Wind River Systems, Inc.
#
# The right to copy, distribute, modify, or otherwise make use
# of this software may be licensed only pursuant to the terms
# of an applicable Wind River license agreement.
#

"""Tests for MultiBackupDriver driver."""

from unittest import mock

from cinder.backup import backup_context
from cinder.backup.drivers import multidriver as md
from cinder import context
from cinder import exception
from cinder.tests.unit import test


class BackupNFSShareTestCase(test.TestCase):

    def setUp(self):
        super(BackupNFSShareTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.mock_object(md, 'LOG')
        # Note(yikun): It mocks out the backup notifier to avoid to leak
        # notifications into other test.
        notify_patcher = mock.patch(
            'cinder.volume.volume_utils.notify_about_backup_usage')
        notify_patcher.start()
        self.addCleanup(notify_patcher.stop)

    def test_check_for_setup_error_without_backup_context(self):
        with mock.patch.object(
                md.MultiBackupDriver,
                "_check_for_setup_errors_on_supported_drivers") as _check_mock:
            multidriver = md.MultiBackupDriver(context=self.ctxt,
                                               backup_context=None)
            multidriver.check_for_setup_error()
            _check_mock.assert_called_once_with()

    def test_check_for_backup_context_error_no_driver_raises(self):
        context = backup_context.BackupContext(driver=None,
                                               location='fake_location')
        try:
            md.MultiBackupDriver(context=self.ctxt, backup_context=context)
        except exception.BackupDriverException:
            pass

    def test_check_for_backup_context_error_unknown_driver_raises(self):
        context = backup_context.BackupContext(driver='unknown',
                                               location='None')
        try:
            md.MultiBackupDriver(context=self.ctxt, backup_context=context)
        except exception.BackupDriverException:
            pass

    def test_check_for_backup_context_error_ceph_with_location_raises(self):
        context = backup_context.BackupContext(driver='ceph',
                                               location='fake_location')
        try:
            md.MultiBackupDriver(context=self.ctxt, backup_context=context)
        except exception.BackupDriverException:
            pass

    def test_check_for_backup_context_error_nfs_without_location_raises(self):
        context = backup_context.BackupContext(driver='nfs', location=None)
        try:
            md.MultiBackupDriver(context=self.ctxt, backup_context=context)
        except exception.BackupDriverException:
            pass

    def test_get_driver_without_backup_context(self):
        multidriver = md.MultiBackupDriver(context=self.ctxt,
                                           backup_context=None)
        driver = multidriver.get_driver()
        self.assertEqual(driver, type(multidriver))

    def test_get_driver_with_ceph_in_backup_context(self):
        context = backup_context.BackupContext(driver="ceph", location=None)
        multidriver = md.MultiBackupDriver(context=self.ctxt,
                                           backup_context=context)
        driver = multidriver.get_driver()
        self.assertEqual(driver, md.CephBackupDriver)

    def test_get_driver_with_nfs_in_backup_context(self):
        context = backup_context.BackupContext(driver='nfs',
                                               location='fake_location')
        multidriver = md.MultiBackupDriver(context=self.ctxt,
                                           backup_context=context)
        driver = multidriver.get_driver()
        self.assertEqual(driver, md.MultiTenantNFSBackupDriver)

    def test__check_check_for_setup_errors_on_supported_drivers(self):
        with mock.patch.object(md, "CephBackupDriver") as CephBackupDriverMock:
            ceph_service_mock = CephBackupDriverMock.return_value
            ceph_service_mock.check_for_setup_error \
                .side_effect = exception.BackupDriverException
            multidriver = md.MultiBackupDriver(context=self.ctxt,
                                               backup_context=None)
            self.assertRaises(
                exception.BackupDriverException,
                multidriver._check_for_setup_errors_on_supported_drivers)
