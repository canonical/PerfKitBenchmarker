# Copyright 2026 PerfKitBenchmarker Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""LXD MicroCloud IaaS relational database resource classes.

MicroCloud has no managed-database service, so relational-db benchmarks (e.g.
pgbench) run PostgreSQL/MySQL on PKB-provisioned instances. These thin
subclasses just bind the cloud-agnostic IaaS implementations to the
LxdMicrocloud cloud so the resource registry can resolve them.
"""

from perfkitbenchmarker import mysql_iaas_relational_db
from perfkitbenchmarker import postgres_iaas_relational_db
from perfkitbenchmarker import provider_info


class LxdMicrocloudPostgresIAASRelationalDb(
    postgres_iaas_relational_db.PostgresIAASRelationalDb
):
  """An LXD MicroCloud IAAS Postgres database resource."""

  CLOUD = provider_info.LXDMICROCLOUD


class LxdMicrocloudMysqlIAASRelationalDb(
    mysql_iaas_relational_db.MysqlIAASRelationalDb
):
  """An LXD MicroCloud IAAS MySQL database resource."""

  CLOUD = provider_info.LXDMICROCLOUD
