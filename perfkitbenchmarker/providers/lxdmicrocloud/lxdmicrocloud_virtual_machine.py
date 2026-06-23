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

Commands and file transfers are driven through the LXD API via `lxc exec`
and `lxc file` (not SSH), so the PKB host does not need IP reachability to the
OVN-managed instances -- only a working `lxc` client pointed at the cluster.

Preconditions on the PKB host:
  * The `lxc` binary is on $PATH (or pointed at via --lxd_cli_path).
  * `lxc cluster list` succeeds, i.e. the user has bootstrapped MicroCloud and
    the default `lxc` remote targets the cluster.
"""

import logging
import os
import shlex
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

_VIRTUAL_MACHINE = 'virtual-machine'
_EGRESS_PROXY_DEVICE = 'pkb-egress-proxy'


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

  def _CreateDependencies(self) -> None:
    self.firewall = lxdmicrocloud_network.LxdMicrocloudFirewall.GetFirewall()

  def _Create(self) -> None:
    cmd = lxd_util.LxcCommand('launch', self._ResolveImageRef(), self.name)
    if self.instance_type == _VIRTUAL_MACHINE:
      cmd.flags['vm'] = True
    if self.storage_pool:
      cmd.flags['s'] = self.storage_pool
    if self.network_name:
      cmd.flags['n'] = self.network_name
    if self.target_member:
      cmd.flags['target'] = self.target_member

    config: list[str] = []
    cpu_count = self._GetRequestedCpuCount()
    if cpu_count:
      config.append(f'limits.cpu={cpu_count}')
    memory_gib = self._GetRequestedMemoryGiB()
    if memory_gib:
      config.append(f'limits.memory={memory_gib}GiB')
    config.extend(lxd_flags.LXD_EXTRA_CONFIG.value)
    if config:
      cmd.flags['c'] = config

    if self.boot_disk_size:
      cmd.flags['d'] = f'root,size={self.boot_disk_size}GiB'

    _, stderr, retcode = cmd.Issue(timeout=lxd_flags.LXD_LAUNCH_TIMEOUT.value)
    if retcode != 0:
      raise errors.Resource.CreationError(
          f'`lxc launch` failed for {self.name}: {stderr}'
      )
    self.id = self.name

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
    self._SetupEgressProxy()

  def _SetupEgressProxy(self) -> None:
    """Routes instance HTTP(S) egress through the site proxy, if configured.

    Many MicroCloud OVN networks isolate instances from external networks. To
    give instances HTTP(S) egress we point their http(s)_proxy at the site
    proxy two ways: LXD `environment.*` keys (injected into every `lxc exec`,
    so wget/curl/pip pick them up) and an apt proxy drop-in (PKB installs
    packages with `sudo apt-get`, and sudo strips the inherited environment).

    How the instance reaches the proxy depends on its type:
      * Containers share the host network namespace, so we add an LXD `proxy`
        device that listens on a loopback port inside the container and
        forwards to the proxy from the host side (sourced from the host
        management IP). The guest proxy URL is that loopback listener.
      * Virtual machines are fully isolated; the LXD proxy device only supports
        forwarding into a VM, not out of it. We therefore point the guest at
        the proxy address directly, which works when the VM has native network
        egress to the proxy. On fully air-gapped OVN networks a VM cannot reach
        the proxy without network-level egress (outside this provider's scope).
    """
    if not lxd_flags.LXD_HTTP_PROXY.value:
      return
    host, port = self._ParseProxyHostPort(lxd_flags.LXD_HTTP_PROXY.value)

    if self.instance_type == _VIRTUAL_MACHINE:
      guest_proxy_url = f'http://{host}:{port}'
      logging.info(
          'Instance %s (VM) egress proxy set to %s (direct; requires native '
          'VM network egress to the proxy)',
          self.name,
          guest_proxy_url,
      )
    else:
      guest_proxy_url = f'http://127.0.0.1:{port}'
      device = lxd_util.LxcCommand(
          'config', 'device', 'add', self.name, _EGRESS_PROXY_DEVICE, 'proxy'
      )
      device.additional_flags = [
          f'listen=tcp:127.0.0.1:{port}',
          f'connect=tcp:{host}:{port}',
          'bind=instance',
      ]
      _, stderr, retcode = device.Issue()
      if retcode != 0:
        raise errors.Resource.CreationError(
            f'Failed to add egress proxy device to {self.name}: {stderr}'
        )
      logging.info(
          'Instance %s (container) egress proxied via %s -> %s:%s',
          self.name,
          guest_proxy_url,
          host,
          port,
      )

    for key in ('environment.http_proxy', 'environment.https_proxy'):
      cmd = lxd_util.LxcCommand('config', 'set', self.name, key, guest_proxy_url)
      _, stderr, retcode = cmd.Issue()
      if retcode != 0:
        raise errors.Resource.CreationError(
            f'Failed to set {key} on {self.name}: {stderr}'
        )

    self._WriteAptProxyConfig(guest_proxy_url)

  def _WriteAptProxyConfig(self, guest_proxy_url: str) -> None:
    """Writes an apt proxy drop-in so `sudo apt-get` uses the egress proxy.

    Written via RemoteCommand (the provider's `lxc exec` transport) rather than
    a raw file copy, matching how the Docker/Kubernetes providers configure
    proxies, and because `sudo apt-get` ignores the inherited http_proxy env.
    """
    apt_conf = (
        f'Acquire::http::Proxy "{guest_proxy_url}";\n'
        f'Acquire::https::Proxy "{guest_proxy_url}";\n'
    )
    self.RemoteCommand(
        f'printf %s {shlex.quote(apt_conf)} | '
        'sudo tee /etc/apt/apt.conf.d/00pkb-proxy > /dev/null'
    )

  @staticmethod
  def _ParseProxyHostPort(proxy: str) -> tuple[str, int]:
    """Parses `[scheme://]host:port` into (host, port); port defaults to 3128."""
    value = proxy.split('://', 1)[-1].strip('/')
    if ':' in value:
      host, port_str = value.rsplit(':', 1)
      return host, int(port_str)
    return value, 3128

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

  # --- Command/file transport ---------------------------------------------
  # MicroCloud instances sit on an OVN network whose IPs are not routable from
  # the PKB host, so SSH is unusable. We drive the instance through the LXD API
  # via `lxc exec` / `lxc file` instead, mirroring how the Kubernetes provider
  # uses `kubectl exec`. Commands run as root inside the instance.

  def RemoteHostCommandWithReturnCode(
      self,
      command: str,
      retries: int | None = None,
      ignore_failure: bool = False,
      login_shell: bool = False,
      disable_tty_lock: bool = False,
      timeout: float | None = None,
      ip_address: str | None = None,
      should_pre_log: bool = True,
      stack_level: int = 1,
      suppress_logging: bool = False,
  ) -> tuple[str, str, int]:
    """Runs a command in the instance via `lxc exec` (no SSH)."""
    del retries, disable_tty_lock, ip_address  # No SSH connection to retry/aim.
    stack_level += 1
    if should_pre_log:
      logging.info(
          'Running on %s via lxc exec: %s',
          self.name,
          command,
          stacklevel=stack_level,
      )
    stdout, stderr, retcode = lxd_util.ExecInInstance(
        self.name,
        command,
        login_shell=login_shell,
        timeout=timeout,
        suppress_logging=suppress_logging,
    )
    if retcode and not ignore_failure:
      raise errors.VirtualMachine.RemoteCommandError(
          f'Got non-zero return code ({retcode}) executing {command}\n'
          f'STDOUT: {stdout}STDERR: {stderr}'
      )
    return stdout, stderr, retcode

  def RemoteHostCopy(
      self, file_path: str, remote_path: str = '', copy_to: bool = True
  ) -> None:
    """Copies a file to/from the instance via `lxc file push`/`pull`."""
    if copy_to:
      dest = remote_path or '/root/'
      _, stderr, retcode = lxd_util.PushFile(
          self.name, file_path, dest, recursive=os.path.isdir(file_path)
      )
      description = f'push {file_path} -> {self.name}{dest}'
    else:
      _, stderr, retcode = lxd_util.PullFile(self.name, remote_path, file_path)
      description = f'pull {self.name}{remote_path} -> {file_path}'
    if retcode:
      raise errors.VirtualMachine.RemoteCommandError(
          f'`lxc file` {description} failed: {stderr}'
      )

  def WaitForBootCompletion(self) -> None:
    """Waits until the instance is ready to accept `lxc exec` commands."""
    self._WaitForExecReady()
    if self.bootable_time is None:
      self.bootable_time = time.time()

  @vm_util.Retry(
      poll_interval=2,
      max_retries=-1,
      timeout=600,
      log_errors=False,
      retryable_exceptions=(errors.VirtualMachine.RemoteCommandError,),
  )
  def _WaitForExecReady(self) -> None:
    """Blocks until `lxc exec` works and first-boot config has settled."""
    stdout, _ = self.RemoteHostCommand('hostname', should_pre_log=False)
    if self.hostname is None:
      self.hostname = stdout.strip()
    # Let cloud-init finish so package installs during Prepare don't race it.
    self.RemoteHostCommand(
        'command -v cloud-init >/dev/null 2>&1 && '
        'cloud-init status --wait >/dev/null 2>&1 || true',
        should_pre_log=False,
        ignore_failure=True,
        timeout=300,
    )

  def AuthenticateVm(self) -> None:
    """No-op: the exec transport needs no SSH key sharing between hosts."""
    self.has_private_key = True

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
