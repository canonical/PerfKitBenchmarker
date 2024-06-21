# Copyright 2014 PerfKitBenchmarker Authors. All rights reserved.
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


"""Module containing Ant installation and cleanup functions."""

import posixpath
import re

from absl import flags

from perfkitbenchmarker import linux_packages

FLAGS = flags.FLAGS

ANT_TAR = 'apache-ant-1.9.6-bin.tar.gz'
ANT_TAR_URL = 'https://archive.apache.org/dist/ant/binaries/' + ANT_TAR

PACKAGE_NAME = 'ant'
PREPROVISIONED_DATA = {
    ANT_TAR: '90d28c0202871bd9875a5da6d982f362bb3114d346b9d8ae58860b8d3312c21c'
}
PACKAGE_DATA_URL = {ANT_TAR: ANT_TAR_URL}
ANT_HOME_DIR = posixpath.join(linux_packages.INSTALL_DIR, PACKAGE_NAME)

def SetProxy(vm):
  """Sets proxy for Ant"""
  proxy_opts=""

  if FLAGS.http_proxy:
    host,port = FLAGS.http_proxy.rsplit(':', 1)
    host=re.sub('http[s]?://', '', host, re.IGNORECASE)
    proxy_opts = f"{proxy_opts}-Dhttp.proxyHost={host} -Dhttp.proxyPort={port} "

  if FLAGS.https_proxy:
    host,port = FLAGS.https_proxy.rsplit(':', 1)
    host=re.sub('http[s]?://', '', host, re.IGNORECASE)
    proxy_opts = f"{proxy_opts}-Dhttps.proxyHost={host} -Dhttps.proxyPort={port} "

  if FLAGS.http_proxy or FLAGS.https_proxy :
    proxy_opts=f'ANT_OPTS="{proxy_opts}"'
    vm.RemoteCommand(f"echo '{proxy_opts}' | sudo tee -a /etc/profile")
    vm.RemoteCommand(f"echo '{proxy_opts}' | sudo tee -a /etc/environment")

def _Install(vm):
  """Installs the Ant package on the VM."""
  vm.Install('wget')
  vm.InstallPreprovisionedPackageData(PACKAGE_NAME, PREPROVISIONED_DATA.keys(),
                                      linux_packages.INSTALL_DIR)
  vm.RemoteCommand('cd {0}  && tar -zxf apache-ant-1.9.6-bin.tar.gz && '
                   'ln -s {0}/apache-ant-1.9.6/ {1}'.format(
                       linux_packages.INSTALL_DIR, ANT_HOME_DIR))
  SetProxy(vm)


def YumInstall(vm):
  """Installs the Ant package on the VM."""
  _Install(vm)


def AptInstall(vm):
  """Installs the Ant package on the VM."""
  _Install(vm)
