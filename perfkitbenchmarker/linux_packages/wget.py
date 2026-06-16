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


"""Module containing wget installation and cleanup functions."""

from absl import flags

FLAGS = flags.FLAGS


def Install(vm):
  """Installs the wget package on the VM."""
  vm.InstallPackages('wget')
  # Write ~/.wgetrc so wget picks up the proxy even under SSH ControlMaster
  # (ControlMaster multiplexed sessions don't re-read /etc/environment).
  wgetrc_lines = []
  if FLAGS.http_proxy:
    wgetrc_lines.append('http_proxy = %s' % FLAGS.http_proxy)
  if FLAGS.https_proxy:
    wgetrc_lines.append('https_proxy = %s' % FLAGS.https_proxy)
  if wgetrc_lines:
    vm.RemoteCommand(
        'printf "%s\n" >> ~/.wgetrc' % '\n'.join(wgetrc_lines)
    )
