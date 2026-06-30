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

"""Tests for the LXD MicroCloud virtual machine class."""

import unittest

import mock
from absl import flags

from perfkitbenchmarker import errors
from perfkitbenchmarker.providers.lxdmicrocloud import (
    lxdmicrocloud_virtual_machine,
)
from perfkitbenchmarker.providers.lxdmicrocloud import util as lxd_util
from tests import pkb_common_test_case

FLAGS = flags.FLAGS


class LxdMicrocloudBootDiskTest(pkb_common_test_case.PkbCommonTestCase):
  """Verifies the root-disk size wiring at `lxc launch` time."""

  def _CreateVm(self, boot_disk_size, instance_type='container'):
    FLAGS.lxd_instance_type = instance_type
    spec = pkb_common_test_case.CreateTestVmSpec()
    spec.boot_disk_size = boot_disk_size
    return lxdmicrocloud_virtual_machine.Ubuntu2404BasedLxdMicrocloudVirtualMachine(
        spec
    )

  def _LaunchCommandFor(self, boot_disk_size, instance_type='container'):
    """Returns the argv list emitted by `lxc launch` for the given size."""
    vm = self._CreateVm(boot_disk_size, instance_type)
    captured = []

    def _capture(cmd, **kwargs):
      del kwargs
      captured.append(list(cmd._GetCommand()))
      return ('', '', 0)

    with mock.patch.object(
        lxd_util.LxcCommand, 'Issue', autospec=True, side_effect=_capture
    ):
      vm._Create()
    self.assertLen(captured, 1)
    return captured[0]

  def testBootDiskSizeContainerEmitsRootSizeFlag(self):
    argv = self._LaunchCommandFor(20, instance_type='container')
    self.assertIn('-d', argv)
    self.assertIn('root,size=20GiB', argv)

  def testBootDiskSizeVirtualMachineEmitsRootSizeFlag(self):
    argv = self._LaunchCommandFor(30, instance_type='virtual-machine')
    self.assertIn('-d', argv)
    self.assertIn('root,size=30GiB', argv)

  def testNoBootDiskSizeOmitsRootSizeFlag(self):
    argv = self._LaunchCommandFor(None)
    self.assertNotIn('-d', argv)
    self.assertFalse(any('root,size=' in token for token in argv))

  def testNonPositiveBootDiskSizeRaises(self):
    for bad_size in (0, -5):
      vm = self._CreateVm(bad_size)
      with self.assertRaises(errors.Config.InvalidValue):
        vm._ResolveRootDiskSizeGiB()

  def testNonIntegerBootDiskSizeRaises(self):
    vm = self._CreateVm('big')
    with self.assertRaises(errors.Config.InvalidValue):
      vm._ResolveRootDiskSizeGiB()


if __name__ == '__main__':
  unittest.main()
