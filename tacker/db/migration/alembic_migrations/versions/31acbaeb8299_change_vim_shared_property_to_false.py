# Copyright 2017 OpenStack Foundation
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#

"""change_vim_shared_property_to_false

Revision ID: 31acbaeb8299
Revises: e7993093baf1
Create Date: 2017-05-30 23:46:20.034085

"""

# flake8: noqa: E402

# revision identifiers, used by Alembic.
revision = '31acbaeb8299'
down_revision = 'e7993093baf1'

from alembic import op
import sqlalchemy as sa


def upgrade(active_plugins=None, options=None):
    op.alter_column('vims', 'shared',
                    existing_type=sa.Boolean(),
                    server_default=sa.text('false'),
                    nullable=False)
