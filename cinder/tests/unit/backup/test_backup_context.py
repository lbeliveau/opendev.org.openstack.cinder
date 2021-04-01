#
# Copyright (c) 2021-2023 Wind River Systems, Inc.
#
# The right to copy, distribute, modify, or otherwise make use
# of this software may be licensed only pursuant to the terms
# of an applicable Wind River license agreement.
#

"""Tests for the backup_context module."""

from unittest import mock


from cinder.backup import backup_context
from cinder.tests.unit import test


class BackupContextTestCase(test.TestCase):

    @mock.patch("cinder.backup.backup_context.utils.parse_backup_location")
    def test_backup_context(self, parse_mock):
        backup_mock = mock.Mock()
        backup_mock.location = "fake://location"
        parse_mock.return_value = ("fake", "location")
        backup_context.BackupContext.from_backup(backup_mock)
        parse_mock.assert_called_once_with("fake://location")

    def test_backup_context_without_location(self):
        backup_mock = mock.Mock()
        backup_mock.location = None
        bkp_ctx = backup_context.BackupContext.from_backup(backup_mock)
        self.assertTrue(bkp_ctx.is_empty())
