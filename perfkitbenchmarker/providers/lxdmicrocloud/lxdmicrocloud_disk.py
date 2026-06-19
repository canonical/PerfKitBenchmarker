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

"""Disk primitives for the LXD MicroCloud provider.

Scratch disks are LXD custom storage volumes attached to the instance at a
caller-chosen mount path. By default they live on the `remote` MicroCeph pool
so they are replicated across the cluster, but `--lxd_storage_pool` can be
used to switch to `local` (per-node ZFS) for raw-performance tests.
"""

import logging

from absl import flags

from perfkitbenchmarker import disk, errors, provider_info
from perfkitbenchmarker.configs import option_decoders
from perfkitbenchmarker.providers.lxdmicrocloud import flags as lxd_flags
from perfkitbenchmarker.providers.lxdmicrocloud import util as lxd_util

FLAGS = flags.FLAGS

DEFAULT_STORAGE_POOL = 'remote'


class LxdMicrocloudDiskSpec(disk.BaseDiskSpec):
  """Disk spec exposing the LXD-specific `storage_pool` knob."""

  CLOUD = provider_info.LXDMICROCLOUD

  @classmethod
  def _ApplyFlags(cls, config_values, flag_values):
    super()._ApplyFlags(config_values, flag_values)
    if flag_values['lxd_storage_pool'].present:
      config_values['storage_pool'] = flag_values.lxd_storage_pool

  @classmethod
  def _GetOptionDecoderConstructions(cls):
    decoders = super()._GetOptionDecoderConstructions()
    decoders.update({
        'storage_pool': (
            option_decoders.StringDecoder,
            {'default': None, 'none_ok': True},
        ),
    })
    return decoders


class LxdMicrocloudDisk(disk.BaseDisk):
  """An LXD custom storage volume attached to a single instance.

  `_Create` creates the volume in the chosen pool; `Attach` mounts it inside
  the instance at `disk_spec.mount_point` via `lxc storage volume attach`,
  which works for both system containers and full VMs.
  """

  def __init__(
      self,
      disk_spec: LxdMicrocloudDiskSpec,
      name: str,
  ) -> None:
    super().__init__(disk_spec)
    self.name = name
    self.attached_vm_name: str | None = None
    self.storage_pool = (
        getattr(disk_spec, 'storage_pool', None)
        or lxd_flags.LXD_STORAGE_POOL.value
        or DEFAULT_STORAGE_POOL
    )
    self.metadata.update({'storage_pool': self.storage_pool})

  def _Create(self) -> None:
    cmd = lxd_util.LxcCommand(
        'storage', 'volume', 'create', self.storage_pool, self.name
    )
    if self.disk_size:
      cmd.flags['config'] = f'size={self.disk_size}GiB'
    _, stderr, retcode = cmd.Issue()
    if retcode != 0:
      raise errors.Resource.CreationError(
          f'Failed to create LXD storage volume {self.storage_pool}/{self.name}: '
          f'{stderr}'
      )

  def _Delete(self) -> None:
    cmd = lxd_util.LxcCommand(
        'storage', 'volume', 'delete', self.storage_pool, self.name
    )
    _, stderr, retcode = cmd.Issue()
    if retcode != 0:
      logging.warning(
          'Failed to delete LXD storage volume %s/%s: %s',
          self.storage_pool,
          self.name,
          stderr,
      )

  def _Exists(self) -> bool:
    cmd = lxd_util.LxcCommand(
        'storage', 'volume', 'show', self.storage_pool, self.name
    )
    _, _, retcode = cmd.Issue(suppress_logging=True)
    return retcode == 0

  def Attach(self, vm) -> None:
    if not self.mount_point:
      raise errors.Error(
          f'LxdMicrocloudDisk {self.name} requires a mount_point for attach.'
      )
    cmd = lxd_util.LxcCommand(
        'storage',
        'volume',
        'attach',
        self.storage_pool,
        self.name,
        vm.name,
        self.mount_point,
    )
    _, stderr, retcode = cmd.Issue()
    if retcode != 0:
      raise errors.Error(
          f'Failed to attach LXD volume {self.storage_pool}/{self.name} to '
          f'{vm.name} at {self.mount_point}: {stderr}'
      )
    self.attached_vm_name = vm.name
    self.vm = vm

  def Detach(self) -> None:
    if self.attached_vm_name is None:
      return
    cmd = lxd_util.LxcCommand(
        'storage',
        'volume',
        'detach',
        self.storage_pool,
        self.name,
        self.attached_vm_name,
    )
    _, stderr, retcode = cmd.Issue()
    if retcode != 0:
      logging.warning(
          'Failed to detach LXD volume %s/%s from %s: %s',
          self.storage_pool,
          self.name,
          self.attached_vm_name,
          stderr,
      )
    self.attached_vm_name = None

  def GetDevicePath(self) -> str:
    raise errors.Error(
        'LxdMicrocloudDisk volumes are mounted directly at mount_point by '
        '`lxc storage volume attach`; there is no host device path. Use '
        'self.mount_point instead.'
    )

  def IsNvme(self) -> bool:
    return False
