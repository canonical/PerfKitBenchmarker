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
import logging
import subprocess
from collections import OrderedDict
from typing import Any, Iterable

from absl import flags

from perfkitbenchmarker import errors, vm_util
from perfkitbenchmarker.providers.lxdmicrocloud import flags as lxd_flags

FLAGS = flags.FLAGS


def _RunLxc(
    cmd: list[str],
    timeout: int | None = None,
    suppress_logging: bool = False,
    **_kwargs,
) -> tuple[str, str, int]:
  """Runs an `lxc` command, capturing stdout/stderr via pipes.

  We deliberately do NOT use vm_util.IssueCommand here. That helper redirects
  the child's stdout/stderr to on-disk temp files, and the snap-confined `lxc`
  binary fails to write to those inherited file descriptors: `lxc list
  --format json` returns a non-zero exit code with empty output. Capturing
  through pipes (as subprocess does here) works under snap confinement.

  Args:
    cmd: The full argv list, e.g. ['lxc', 'list', '--format', 'json'].
    timeout: Optional timeout in seconds.
    suppress_logging: If True, do not log stdout/stderr (sensitive output).
    **_kwargs: Accepted and ignored for signature compatibility with callers
      that pass e.g. raise_on_failure; this runner never raises on non-zero
      exit and lets callers inspect the returned retcode.

  Returns:
    A tuple of (stdout, stderr, retcode).
  """
  full_cmd = ' '.join(cmd)
  logging.info('Running: %s', full_cmd)
  try:
    proc = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
  except subprocess.TimeoutExpired as e:
    logging.warning('Timeout after %ss running: %s', timeout, full_cmd)
    stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or '')
    stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or '')
    return stdout, stderr, -1
  if not suppress_logging:
    if proc.stdout:
      logging.info('STDOUT: %s', proc.stdout)
    if proc.stderr:
      logging.info('STDERR: %s', proc.stderr)
  return proc.stdout, proc.stderr, proc.returncode


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
    return _RunLxc(self._GetCommand(), **kwargs)

  def IssueRetryable(self, **kwargs) -> tuple[str, str]:
    """Runs the command with retry on transient failures."""

    @vm_util.Retry()
    def _Run() -> tuple[str, str]:
      stdout, stderr, retcode = _RunLxc(self._GetCommand(), **kwargs)
      if retcode != 0:
        raise errors.VmUtil.CalledProcessException(
            f'Command returned a non-zero exit code:\n{stderr}'
        )
      return stdout, stderr

    return _Run()


def IssueLxc(args: Iterable[str], **kwargs) -> tuple[str, str, int]:
  """Convenience: run a one-shot lxc command without flags/state."""
  cmd: list[str] = [lxd_flags.LXD_CLI_PATH.value, *args]
  return _RunLxc(cmd, **kwargs)


def InstanceExists(name: str) -> bool:
  """Returns True iff `lxc info <name>` succeeds (instance exists)."""
  _, _, retcode = IssueLxc(['info', name], suppress_logging=True)
  return retcode == 0


def ExecInInstance(
    name: str,
    command: str,
    login_shell: bool = False,
    timeout: float | None = None,
    suppress_logging: bool = False,
) -> tuple[str, str, int]:
  """Runs a shell command inside an instance via `lxc exec`.

  This is the provider's command channel. It travels over the LXD API (through
  the configured `lxc` remote), so it works even when the instance's
  OVN-assigned IP is not routable from the PKB host -- which is the normal case
  for MicroCloud's isolated OVN networks. The command runs as root.

  Args:
    name: The instance name.
    command: A bash command string.
    login_shell: If True, run via `bash -l -c` so profile/proxy environment is
      sourced.
    timeout: Optional timeout in seconds.
    suppress_logging: If True, do not log stdout/stderr.

  Returns:
    A tuple of (stdout, stderr, retcode).
  """
  cmd = LxcCommand('exec', name)
  shell = ['bash', '-l', '-c'] if login_shell else ['bash', '-c']
  cmd.additional_flags = ['--', *shell, command]
  return cmd.Issue(timeout=timeout, suppress_logging=suppress_logging)


def PushFile(
    name: str,
    local_path: str,
    remote_path: str,
    recursive: bool = False,
) -> tuple[str, str, int]:
  """Copies a local file/dir into an instance via `lxc file push`.

  Args:
    name: The instance name.
    local_path: Source path on the PKB host.
    remote_path: Destination path inside the instance. A trailing '/' denotes a
      directory and the source basename is preserved.
    recursive: If True, copy directories recursively.

  Returns:
    A tuple of (stdout, stderr, retcode).
  """
  cmd = LxcCommand('file', 'push', local_path, f'{name}{remote_path}')
  cmd.flags['create-dirs'] = True
  if recursive:
    cmd.flags['recursive'] = True
  return cmd.Issue()


def PullFile(
    name: str,
    remote_path: str,
    local_path: str,
    recursive: bool = False,
) -> tuple[str, str, int]:
  """Copies a file/dir out of an instance via `lxc file pull`.

  Args:
    name: The instance name.
    remote_path: Source path inside the instance.
    local_path: Destination path on the PKB host.
    recursive: If True, copy directories recursively.

  Returns:
    A tuple of (stdout, stderr, retcode).
  """
  cmd = LxcCommand('file', 'pull', f'{name}{remote_path}', local_path)
  if recursive:
    cmd.flags['recursive'] = True
  return cmd.Issue()


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
