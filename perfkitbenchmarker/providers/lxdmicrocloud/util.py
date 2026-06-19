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

"""Utilities for driving the `lxc` CLI against an LXD MicroCloud cluster."""

import json
from collections import OrderedDict
from typing import Any, Iterable

from absl import flags

from perfkitbenchmarker import errors, vm_util
from perfkitbenchmarker.providers.lxdmicrocloud import flags as lxd_flags

FLAGS = flags.FLAGS


class LxcCommand:
  """Builder for an `lxc` CLI invocation.

  Mirrors the shape of providers.openstack.utils.OpenStackCLICommand: positional
  arguments form the subcommand (e.g. ['launch', 'ubuntu:24.04', 'my-vm']) and
  `flags` / `additional_flags` form the named options. Flags whose value is
  `True` are emitted bare (e.g. `--vm`); list-valued flags are emitted once per
  element (e.g. multiple `-c key=value` pairs).
  """

  def __init__(self, *args: str) -> None:
    self.args: list[str] = list(args)
    self.flags: OrderedDict[str, Any] = OrderedDict()
    self.additional_flags: list[str] = []
    if lxd_flags.LXD_PROJECT.value:
      self.flags['project'] = lxd_flags.LXD_PROJECT.value

  def __repr__(self) -> str:
    return f'LxcCommand({" ".join(self._GetCommand())})'

  def _GetCommand(self) -> list[str]:
    cmd: list[str] = [lxd_flags.LXD_CLI_PATH.value]
    cmd.extend(self.args)
    for flag_name, value in self.flags.items():
      flag_token = (
          f'-{flag_name}' if len(flag_name) == 1 else f'--{flag_name}'
      )
      if value is True:
        cmd.append(flag_token)
      else:
        values = value if isinstance(value, list) else [value]
        for v in values:
          cmd.append(flag_token)
          cmd.append(str(v))
    cmd.extend(self.additional_flags)
    return cmd

  def Issue(self, **kwargs) -> tuple[str, str, int]:
    """Runs the command once, returning (stdout, stderr, retcode)."""
    kwargs.setdefault('raise_on_failure', False)
    return vm_util.IssueCommand(self._GetCommand(), **kwargs)

  def IssueRetryable(self, **kwargs) -> tuple[str, str]:
    """Runs the command with retry on transient failures."""
    return vm_util.IssueRetryableCommand(self._GetCommand(), **kwargs)


def IssueLxc(args: Iterable[str], **kwargs) -> tuple[str, str, int]:
  """Convenience: run a one-shot lxc command without flags/state."""
  cmd: list[str] = [lxd_flags.LXD_CLI_PATH.value, *args]
  kwargs.setdefault('raise_on_failure', False)
  return vm_util.IssueCommand(cmd, **kwargs)


def InstanceExists(name: str) -> bool:
  """Returns True iff `lxc info <name>` succeeds (instance exists)."""
  _, _, retcode = IssueLxc(['info', name], suppress_logging=True)
  return retcode == 0


def GetInstanceInfo(name: str) -> dict[str, Any] | None:
  """Returns the parsed JSON record for one instance, or None if missing.

  Uses `lxc list <name> --format json`, which returns a JSON array (possibly
  empty) of instance records. We match by exact name because `lxc list` treats
  the positional argument as a regex/prefix.
  """
  cmd = LxcCommand('list', name, '--format', 'json')
  stdout, _, retcode = cmd.Issue(suppress_logging=True)
  if retcode != 0 or not stdout.strip():
    return None
  try:
    records = json.loads(stdout)
  except json.JSONDecodeError as e:
    raise errors.Error(
        f'Could not parse `lxc list {name} --format json` output: {e}\n{stdout}'
    ) from e
  for record in records:
    if record.get('name') == name:
      return record
  return None


def GetInstanceIPv4(record: dict[str, Any]) -> str | None:
  """Extracts the first global IPv4 address from an `lxc list` JSON record.

  The MicroCloud OVN default network surfaces global-scope IPv4 addresses on
  `eth0`. Link-local (169.254.x.x) and loopback addresses are skipped so we
  return the address that is routable from the host.
  """
  state = record.get('state') or {}
  network = state.get('network') or {}
  for iface_name, iface_data in network.items():
    if iface_name == 'lo':
      continue
    for addr in (iface_data or {}).get('addresses', []) or []:
      if addr.get('family') != 'inet':
        continue
      if addr.get('scope') != 'global':
        continue
      address = addr.get('address')
      if address:
        return address
  return None


def BuildCloudInitUserData(
    username: str, ssh_public_key: str
) -> str:
  """Renders a cloud-init #cloud-config that provisions an SSH-able user.

  We hand-render YAML rather than depending on PyYAML to keep the provider
  dependency-free (matches the Docker provider's posture).
  """
  key = ssh_public_key.strip().replace('\\', '\\\\').replace('"', '\\"')
  return (
      '#cloud-config\n'
      'users:\n'
      f'  - name: {username}\n'
      '    sudo: ALL=(ALL) NOPASSWD:ALL\n'
      '    shell: /bin/bash\n'
      '    lock_passwd: false\n'
      '    ssh_authorized_keys:\n'
      f'      - "{key}"\n'
      'ssh_pwauth: false\n'
      'disable_root: false\n'
  )


def ReadSshPublicKey(path: str) -> str:
  """Reads an SSH public key file from disk, stripping trailing whitespace."""
  with open(path) as f:
    return f.read().strip()
