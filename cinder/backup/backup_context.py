# Copyright (c) 2021-2023 Wind River Systems, Inc.
#
# The right to copy, distribute, modify, or otherwise make use
# of this software may be licensed only pursuant to the terms
# of an applicable Wind River license agreement.
#

from oslo_log import log as logging

from cinder import utils


LOG = logging.getLogger(__name__)


class BackupContext:

    def __init__(self, *, driver=None, location=None):
        self.driver = driver.lower() if driver else None
        self.location = location

    def is_empty(self):
        return self.location is None and self.driver is None

    @classmethod
    def from_backup(cls, backup):
        driver = None
        location = None
        backup_location = backup.location
        if backup_location:
            driver, location = utils.parse_backup_location(backup_location)
        LOG.info("Backup Context: driver: %s, location: %s",
                 driver, location)
        return cls(driver=driver, location=location)
