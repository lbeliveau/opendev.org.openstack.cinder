# Copyright (c) 2021-2023 Wind River Systems, Inc.
#
# The right to copy, distribute, modify, or otherwise make use
# of this software may be licensed only pursuant to the terms
# of an applicable Wind River license agreement.


class BackupContext:

    def __init__(self, location, driver=None):
        self.location = location
        self.driver = driver
