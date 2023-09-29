# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Add location to backups

Revision ID: afa036af7b06
Revises: daa98075b90d
Create Date: 2023-09-29 17:02:12.959681
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'afa036af7b06'
down_revision = 'daa98075b90d'
branch_labels = None
depends_on = None


def upgrade():
    """Add column to the backups table.

    Add location column to the backups table to allow user provided
    backup locations.
    """
    connection = op.get_bind()
    backups = sa.Table("backups", sa.MetaData(), autoload_with=connection)
    if not hasattr(backups.c, "location"):
        op.add_column(
            "backups", sa.Column("location", sa.String(255), nullable=True)
        )
