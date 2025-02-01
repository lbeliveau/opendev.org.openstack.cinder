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

"""merge 9c74c1c6971f and afa036af7b06

Revision ID: b5a7e35ae37c
Revises: 9c74c1c6971f, afa036af7b06
Create Date: 2025-01-31 13:40:48.128844
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5a7e35ae37c'
down_revision = ('9c74c1c6971f', 'afa036af7b06')
branch_labels = None
depends_on = None


def upgrade():
    pass
