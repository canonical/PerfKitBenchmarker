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

"""Virtual-machine class for the LXD MicroCloud provider.

The provider drives the local `lxc` CLI against an already-initialized
MicroCloud cluster (see `microcloud init` / `microcloud join`). It supports
both system containers (`--lxd_instance_type=container`, the default) and full
virtual machines (`--lxd_instance_type=virtual-machine`).

Preconditions on the PKB host:
  * The `lxc` binary is on $PATH (or pointed at via --lxd_cli_path).
  * `lxc cluster list` succeeds, i.e. the user has bootstrapped MicroCloud.
  * The PKB host can route to the OVN-managed instance IPs (typically true
    when PKB runs on a MicroCloud cluster member).
"""

import logging
import os
import subprocess
import tempfile
import time
from typing import Any

from absl import flags

from perfkitbenchmarker import (
    errors,
    linux_virtual_machine,
    provider_info,
    virtual_machine,
    vm_util,
)
from perfkitbenchmarker.providers.lxdmicrocloud import flags as lxd_flags
from perfkitbenchmarker.providers.lxdmicrocloud import (
    lxdmicrocloud_disk,
    lxdmicrocloud_network,
    util as lxd_util,
)

FLAGS = flags.FLAGS

_CONTAINER = 'container'
_VIRTUAL_MACHINE = 'virtual-machine'


class LxdMicrocloudVirtualMachine(virtual_machine.BaseVirtualMachine):
  """A PKB VM backed by an LXD instance on a MicroCloud cluster."""

  CLOUD = provider_info.LXDMICROCLOUD
  DEFAULT_IMAGE: str | None = None

  def __init__(self, vm_spec) -> None:
    super().__init__(vm_spec)
    self.name = self.name.replace('_', '-')
    self.user_name = lxd_flags.LXD_INSTANCE_USER.value
    self.image = self.image or self.DEFAULT_IMAGE
    self.instance_type = lxd_flags.LXD_INSTANCE_TYPE.value
    self.image_remote = lxd_flags.LXD_IMAGE_REMOTE.value
    self.storage_pool = lxd_flags.LXD_STORAGE_POOL.value
    self.network_name = lxd_flags.LXD_NETWORK.value
    self.target_member = lxd_flags.LXD_TARGET_MEMBER.value or self.zone
    self._cloud_init_path: str | None = None

  def _CreateDependencies(self) -> None:
    self.firewall = lxdmicrocloud_network.LxdMicrocloudFirewall.GetFirewall()
    self._cloud_init_path = self._WriteCloudInitFile()

  def _DeleteDependencies(self) -> None:
    if self._cloud_init_path and os.path.exists(self._cloud_init_path):
      try:
        os.unlink(self._cloud_init_path)
      except OSError as e:
        logging.warning(
            'Failed to remove cloud-init file %s: %s',
            self._cloud_init_path,
            e,
        )
      self._cloud_init_path = None

  def _Create(self) -> None:
    image_ref = self._ResolveImageRef()
    cmd = [lxd_flags.LXD_CLI_PATH.value, 'launch', image_ref, self.name]
    if self.instance_type == _VIRTUAL_MACHINE:
      cmd.append('--vm')
    if lxd_flags.LXD_PROJECT.value:
      cmd.extend(['--project', lxd_flags.LXD_PROJECT.value])
    if self.storage_pool:
      cmd.extend(['-s', self.storage_pool])
    if self.network_name:
      cmd.extend(['-n', self.network_name])
    if self.target_member:
      cmd.extend(['--target', self.target_member])

    cpu_count = self._GetRequestedCpuCount()
    if cpu_count:
      cmd.extend(['-c', f'limits.cpu={cpu_count}'])
    memory_gib = self._GetRequestedMemoryGiB()
    if memory_gib:
      cmd.extend(['-c', f'limits.memory={memory_gib}GiB'])

    for extra in lxd_flags.LXD_EXTRA_CONFIG.value:
      cmd.extend(['-c', extra])

    if self.boot_disk_size:
      cmd.extend(['-d', f'root,size={self.boot_disk_size}GiB'])

    stdin = self._BuildLaunchStdin()
    if stdin is not None:
      cmd.append('--')
    stdout, stderr, retcode = self._IssueLaunch(cmd, stdin)
    if retcode != 0:
      raise errors.Resource.CreationError(
          f'`lxc launch` failed for {self.name}: {stderr or stdout}'
      )
    self.id = self.name

  def _IssueLaunch(
      self, cmd: list[str], stdin: str | None
  ) -> tuple[str, str, int]:
    """Runs `lxc launch`, piping cloud-init YAML on stdin when present.

    vm_util.IssueCommand has no `input=` parameter, so when stdin is needed
    (for cloud-init) we shell out via subprocess directly. The no-stdin path
    still goes through vm_util.IssueCommand for consistent logging.
    """
    if stdin is None:
      return vm_util.IssueCommand(
          cmd,
          timeout=lxd_flags.LXD_LAUNCH_TIMEOUT.value,
          raise_on_failure=False,
      )
    logging.info('Running: %s (with stdin cloud-init)', ' '.join(cmd))
    proc = subprocess.run(
        cmd,
        input=stdin,
        text=True,
        capture_output=True,
        timeout=lxd_flags.LXD_LAUNCH_TIMEOUT.value,
        check=False,
    )
    if proc.stdout:
      logging.info('STDOUT: %s', proc.stdout)
    if proc.stderr:
      logging.info('STDERR: %s', proc.stderr)
    return proc.stdout, proc.stderr, proc.returncode

  def _BuildLaunchStdin(self) -> str | None:
    """Returns cloud-init YAML to pipe on stdin, or None.

    `lxc launch` reads YAML config from stdin when it is a TTY-less pipe; we
    embed a small profile-style override that sets cloud-init.user-data so the
    SSH user is created on first boot.
    """
    if not self._cloud_init_path:
      return None
    with open(self._cloud_init_path) as f:
      user_data = f.read()
    indented = '\n'.join('    ' + line for line in user_data.splitlines())
    return (
        'config:\n'
        '  cloud-init.user-data: |\n'
        f'{indented}\n'
    )

  def _WriteCloudInitFile(self) -> str:
    """Renders the cloud-init #cloud-config to a host-side temp file."""
    ssh_public_key = lxd_util.ReadSshPublicKey(self.ssh_public_key)
    user_data = lxd_util.BuildCloudInitUserData(self.user_name, ssh_public_key)
    fd, path = tempfile.mkstemp(
        prefix=f'pkb-lxd-{self.name}-', suffix='.cloud-init.yml'
    )
    with os.fdopen(fd, 'w') as f:
      f.write(user_data)
    return path

  def _ResolveImageRef(self) -> str:
    """Returns the fully-qualified `<remote>:<alias>` image reference."""
    if not self.image:
      raise errors.Config.InvalidValue(
          f'LxdMicrocloud VM {self.name} has no image. Set --image or pick an '
          'OS mixin (e.g. --os_type=ubuntu2404) so DEFAULT_IMAGE applies.'
      )
    if ':' in self.image:
      return self.image
    return f'{self.image_remote}:{self.image}'

  def _GetRequestedCpuCount(self) -> int | None:
    """Parses a CPU count from machine_type if it looks like an int."""
    if not self.machine_type:
      return None
    try:
      return int(self.machine_type)
    except (TypeError, ValueError):
      return None

  def _GetRequestedMemoryGiB(self) -> int | None:
    """LXD limits.memory is set via --lxd_extra_config; default is no limit."""
    return None

  @vm_util.Retry(max_retries=4, poll_interval=5)
  def _PostCreate(self) -> None:
    self._WaitForIp()

  def _WaitForIp(self) -> None:
    timeout = lxd_flags.LXD_WAIT_FOR_IP_TIMEOUT.value
    start = time.monotonic()
    while time.monotonic() - start < timeout:
      record = lxd_util.GetInstanceInfo(self.name)
      if record:
        address = lxd_util.GetInstanceIPv4(record)
        if address:
          self.ip_address = address
          self.internal_ip = address
          logging.info('LXD instance %s acquired IPv4 %s', self.name, address)
          return
      time.sleep(3)
    raise errors.Resource.RetryableCreationError(
        f'LXD instance {self.name} did not acquire an IPv4 address in '
        f'{timeout}s.'
    )

  def _Delete(self) -> None:
    cmd = lxd_util.LxcCommand('delete', self.name)
    cmd.flags['force'] = True
    _, stderr, retcode = cmd.Issue()
    if retcode != 0 and 'Instance not found' not in stderr:
      logging.warning('Failed to delete LXD instance %s: %s', self.name, stderr)

  def _Exists(self) -> bool:
    return lxd_util.InstanceExists(self.name)

  def _Start(self) -> None:
    cmd = lxd_util.LxcCommand('start', self.name)
    _, stderr, retcode = cmd.Issue()
    if retcode != 0:
      raise errors.Error(f'Failed to start LXD instance {self.name}: {stderr}')

  def _Stop(self) -> None:
    cmd = lxd_util.LxcCommand('stop', self.name)
    _, stderr, retcode = cmd.Issue()
    if retcode != 0:
      raise errors.Error(f'Failed to stop LXD instance {self.name}: {stderr}')

  def CreateScratchDisk(self, disk_spec_id, disk_spec) -> None:
    """Creates and attaches scratch volumes for one disk_spec.

    LXD's `lxc storage volume attach` mounts the volume directly at the
    requested path inside the instance, so we bypass the default
    PrepareScratchDiskStrategy (which formats and mounts a host device).
    """
    disks: list[lxdmicrocloud_disk.LxdMicrocloudDisk] = []
    for stripe_idx in range(disk_spec.num_striped_disks):
      vol_name = (
          f'{self.name}-data-{disk_spec_id}-{len(self.scratch_disks)}-'
          f'{stripe_idx}'
      )
      disks.append(lxdmicrocloud_disk.LxdMicrocloudDisk(disk_spec, vol_name))
    for d in disks:
      d.Create()
      d.Attach(self)
      self.scratch_disks.append(d)

  def DeleteScratchDisks(self) -> None:
    for scratch_disk in list(self.scratch_disks):
      try:
        scratch_disk.Detach()
      except errors.Error as e:
        logging.warning('Detach failed for %s: %s', scratch_disk.name, e)
      try:
        scratch_disk.Delete()
      except errors.Error as e:
        logging.warning('Delete failed for %s: %s', scratch_disk.name, e)
      self.scratch_disks.remove(scratch_disk)

  def ShouldDownloadPreprovisionedData(self, module_name, filename) -> bool:
    return False

  def InstallCli(self) -> None:
    raise NotImplementedError(
        'Installing the LXD CLI inside a MicroCloud instance is unsupported.'
    )

  def DownloadPreprovisionedData(
      self, install_path, module_name, filename, timeout=None
  ) -> None:
    raise NotImplementedError(
        'Preprovisioned data download is not supported on LxdMicrocloud. '
        'Stage files in PKB\'s data/ directory instead.'
    )

  def GetResourceMetadata(self) -> dict[str, Any]:
    result = super().GetResourceMetadata()
    result['instance_type'] = self.instance_type
    result['image_remote'] = self.image_remote
    if self.storage_pool:
      result['storage_pool'] = self.storage_pool
    if self.network_name:
      result['network'] = self.network_name
    if self.target_member:
      result['target_member'] = self.target_member
    return result


class Ubuntu2204BasedLxdMicrocloudVirtualMachine(
    LxdMicrocloudVirtualMachine, linux_virtual_machine.Ubuntu2204Mixin
):
  DEFAULT_IMAGE = '22.04'


class Ubuntu2404BasedLxdMicrocloudVirtualMachine(
    LxdMicrocloudVirtualMachine, linux_virtual_machine.Ubuntu2404Mixin
):
  DEFAULT_IMAGE = '24.04'
