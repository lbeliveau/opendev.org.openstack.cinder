#
# Copyright (c) 2021-2023 Wind River Systems, Inc.
#
# The right to copy, distribute, modify, or otherwise make use
# of this software may be licensed only pursuant to the terms
# of an applicable Wind River license agreement.
#

"""Ceph/NFS multidriver for cinder-backup."""

from oslo_log import log as logging

from cinder.backup.driver import BackupDriverWithContext
from cinder.backup.drivers.ceph import CephBackupDriver
from cinder.backup.drivers.multitenant_nfs import MultiTenantNFSBackupDriver
from cinder.exception import BackupDriverException
from cinder.exception import InvalidConfigurationValue

LOG = logging.getLogger(__name__)

_NFS = "nfs"
_CEPH = "ceph"

_BACKUP_DRIVER_MAPPING = {
    _CEPH: CephBackupDriver,
    _NFS: MultiTenantNFSBackupDriver,
}

SUPPORTED_DRIVERS = tuple(_BACKUP_DRIVER_MAPPING.keys())


class MultiBackupDriver(BackupDriverWithContext):
    is_multidriver = True

    def __init__(self, context=None, db=None, backup_context=None):
        self.db = db
        self.context = context
        self.backup_context = backup_context
        self.check_for_backup_context_error()

    def get_driver(self):
        if self.backup_context is None:
            return self.__class__
        driver = _BACKUP_DRIVER_MAPPING.get(self.backup_context.driver)
        LOG.info("Instantiating the driver %s.",
                 driver.__name__)
        return driver

    def check_for_setup_error(self):
        if self.backup_context is None:
            LOG.info("Backup context isn't set.")
            self._check_for_setup_errors_on_supported_drivers()

    def check_for_backup_context_error(self):
        if self.backup_context:
            err_msg = None
            driver = self.backup_context.driver
            location = self.backup_context.location
            if not driver:
                err_msg = "Multidriver is set " \
                          "but a backup driver wasn't provided."
            elif driver not in SUPPORTED_DRIVERS:
                err_msg = "Multidriver doesn't support " \
                          "the provided backup driver."
            elif driver == _CEPH and location:
                err_msg = "Unexpected backup location was provided " \
                          "for Ceph driver."
            elif driver == _NFS and not location:
                err_msg = "Missing required backup location for NFS driver."
            if err_msg:
                raise BackupDriverException(reason=err_msg)

    def _check_for_setup_errors_on_supported_drivers(self):
        failed_services = {}
        for driver in _BACKUP_DRIVER_MAPPING.values():
            try:
                if driver.backup_context_required:
                    service = driver(self.context, db=self.db,
                                     backup_context=self.backup_context)
                else:
                    service = driver(self.context, db=self.db)
                service.check_for_setup_error()
            except (BackupDriverException, InvalidConfigurationValue) as error:
                failed_services[driver.__name__] = error
        if failed_services:
            err_msg = "At least one of the supported drivers failed " \
                      "during initialization: %r." % failed_services
            raise BackupDriverException(reason=err_msg)

    def __not_implemented(self):
        raise NotImplementedError

    backup = restore = delete_backup = __not_implemented
