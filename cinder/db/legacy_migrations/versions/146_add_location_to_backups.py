# Copyright (c) 2021-2023 Wind River Systems, Inc.
#
# The right to copy, distribute, modify, or otherwise make use
# of this software may be licensed only pursuant to the terms
# of an applicable Wind River license agreement.

from sqlalchemy import MetaData, Table, Column, String


def upgrade(migrate_engine):
    """Add column to the backups table.

    Add location column to the backups table to allow user provided
    backup locations.
    """
    meta = MetaData(bind=migrate_engine)
    backups = Table('backups', meta, autoload=True)

    if not hasattr(backups.c, 'location'):
        backups.create_column(Column('location', String(255), nullable=True))

