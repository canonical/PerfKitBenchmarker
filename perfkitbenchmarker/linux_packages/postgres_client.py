# Copyright 2021 PerfKitBenchmarker Authors. All rights reserved.
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


"""Module containing postgres_client installation and cleanup functions."""


def _Install(vm):
  """Installs the postgres client package on the VM."""
  # Install directly from Ubuntu's default repos to avoid fetching the
  # pgdg signing key (postgresql.org may be blocked by corporate proxies).
  # Ubuntu 24.04 ships postgresql-client-16 which includes pgbench.
  vm.InstallPackages('postgresql-client')


def AptInstall(vm):
  """Installs the postgres client package on the VM."""
  _Install(vm)


def _Uninstall(vm):
  """Uninstalls the postgres client package on the VM."""
  vm.RemoteCommand('sudo apt-get purge -y postgresql-client')
