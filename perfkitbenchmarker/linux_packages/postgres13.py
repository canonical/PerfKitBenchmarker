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


"""Module containing install postgresql server."""


def AptInstall(vm):
  """Installs the postgres package on the VM."""
  # Install from Ubuntu's default repos to avoid fetching the pgdg signing
  # key (postgresql.org may be blocked by corporate proxies).
  # Ubuntu 24.04 ships postgresql-16; the meta-package 'postgresql' selects
  # the default distro version.
  vm.InstallPackages('postgresql postgresql-contrib')
