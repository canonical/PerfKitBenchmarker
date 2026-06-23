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

"""Flags for the LXD MicroCloud provider.

These flags configure how the provider drives the local `lxc` CLI against an
already-initialized MicroCloud cluster. The user is expected to have run
`sudo microcloud init` (or `microcloud join`) on the cluster nodes before
invoking PKB.
"""

from absl import flags

from perfkitbenchmarker import errors

LXD_CLI_PATH = flags.DEFINE_string(
    'lxd_cli_path',
    'lxc',
    'Path to the `lxc` CLI binary (LXD client). Set this if `lxc` is not on '
    '$PATH or you want to point at a specific snap binary, e.g. '
    '/snap/bin/lxc.',
)

LXD_PROJECT = flags.DEFINE_string(
    'lxd_project',
    None,
    'Optional LXD project (`--project`) to scope every lxc command to. If '
    'unset, the currently selected project is used.',
)

LXD_INSTANCE_TYPE = flags.DEFINE_enum(
    'lxd_instance_type',
    'container',
    ['container', 'virtual-machine'],
    'Whether each PKB VM should be backed by a system container (faster, '
    'lower overhead) or a full virtual machine (stronger isolation, supports '
    'kernels different from the host). `virtual-machine` requires a VM-capable '
    'image (Ubuntu 22.04+).',
)

LXD_IMAGE_REMOTE = flags.DEFINE_string(
    'lxd_image_remote',
    'ubuntu',
    'LXD image remote to pull images from (e.g. `ubuntu`, `ubuntu-daily`, '
    '`images`). Combined with the image alias resolved from --image / the '
    'OS mixin DEFAULT_IMAGE as `<remote>:<alias>`.',
)

LXD_STORAGE_POOL = flags.DEFINE_string(
    'lxd_storage_pool',
    None,
    'LXD storage pool (`-s`) to place instance root and scratch volumes on. '
    'Typical MicroCloud values: `local` (per-node ZFS) or `remote` (Ceph RBD, '
    'replicated). If unset, the default profile pool is used (usually '
    '`remote` on MicroCloud).',
)

LXD_NETWORK = flags.DEFINE_string(
    'lxd_network',
    None,
    'LXD network (`-n`) to attach the instance NIC to. MicroCloud creates a '
    'managed OVN network named `default`. If unset, the default profile NIC '
    'is used.',
)

LXD_TARGET_MEMBER = flags.DEFINE_string(
    'lxd_target_member',
    None,
    'Cluster member name to pin newly-created instances to (`--target`). If '
    'unset, LXD selects a member automatically. PKB also maps the per-VM '
    '`zone` to this value when the flag is not provided.',
)

LXD_INSTANCE_USER = flags.DEFINE_string(
    'lxd_instance_user',
    'ubuntu',
    'Linux user inside the instance to receive the PKB SSH public key via '
    'cloud-init. For Ubuntu cloud images the standard user is `ubuntu`.',
)

LXD_EXTRA_CONFIG = flags.DEFINE_list(
    'lxd_extra_config',
    [],
    'Additional `-c key=value` pairs to pass to every `lxc launch`. Example: '
    '`--lxd_extra_config=security.nesting=true,limits.kernel.memlock=unlimited`.',
)

# Built-in instance flavors. LXD/MicroCloud has no server-side flavor objects
# (unlike OpenStack), so these are client-side presets that map a name to LXD
# resource limits applied at `lxc launch` time. They work identically for
# containers and virtual machines. Memory uses LXD's unit suffixes (GiB/MiB).
# Select one with --machine_type=<name>; extend or override with --lxd_flavors.
DEFAULT_FLAVORS = {
    'small': {'cpus': 1, 'memory': '2GiB'},
    'medium': {'cpus': 2, 'memory': '4GiB'},
    'large': {'cpus': 4, 'memory': '8GiB'},
    'xlarge': {'cpus': 8, 'memory': '16GiB'},
}

LXD_FLAVORS = flags.DEFINE_list(
    'lxd_flavors',
    [],
    'Add or override named instance flavors selectable via --machine_type. '
    'Each entry is `name=cpus:memory`, where memory carries an LXD unit suffix, '
    'e.g. `--lxd_flavors=huge=16:32GiB,tiny=1:512MiB`. Entries override built-in '
    'flavors of the same name. Built-ins: small (1/2GiB), medium (2/4GiB), '
    'large (4/8GiB), xlarge (8/16GiB).',
)


def GetFlavors() -> dict[str, dict[str, object]]:
  """Returns built-in flavors merged with any --lxd_flavors overrides.

  Returns:
    Mapping of flavor name to a {'cpus': int, 'memory': str} dict, where memory
    is an LXD-formatted size string (e.g. '4GiB').

  Raises:
    errors.Config.InvalidValue: if an --lxd_flavors entry is malformed.
  """
  flavors = {name: dict(spec) for name, spec in DEFAULT_FLAVORS.items()}
  for entry in LXD_FLAVORS.value:
    name, sep, body = entry.partition('=')
    name = name.strip()
    cpus_str, mem_sep, memory = body.partition(':')
    if not name or not sep or not mem_sep:
      raise errors.Config.InvalidValue(
          f'Invalid --lxd_flavors entry "{entry}". Expected `name=cpus:memory`, '
          'e.g. `huge=16:32GiB`.'
      )
    try:
      cpus = int(cpus_str)
    except ValueError as e:
      raise errors.Config.InvalidValue(
          f'Invalid cpus in --lxd_flavors entry "{entry}": "{cpus_str}" is not '
          'an integer.'
      ) from e
    flavors[name] = {'cpus': cpus, 'memory': memory.strip()}
  return flavors

LXD_LAUNCH_TIMEOUT = flags.DEFINE_integer(
    'lxd_launch_timeout',
    600,
    'Timeout (seconds) for `lxc launch` to complete and the instance to '
    'reach a usable state.',
)

LXD_WAIT_FOR_IP_TIMEOUT = flags.DEFINE_integer(
    'lxd_wait_for_ip_timeout',
    300,
    'Timeout (seconds) to wait for the instance to acquire an IPv4 address.',
)

LXD_HTTP_PROXY = flags.DEFINE_string(
    'lxd_http_proxy',
    None,
    'If set, give each instance HTTP(S) egress through this proxy. MicroCloud '
    'OVN instances are typically isolated and cannot reach external networks '
    'directly, while the LXD hosts can reach the site egress proxy. The '
    'provider adds an LXD `proxy` device that listens on a loopback port '
    'inside the instance and forwards to this address from the host side (so '
    'traffic is sourced from the host management IP), then points the '
    "instance's http(s)_proxy at that loopback listener. Provide the proxy "
    'address reachable from the LXD host as `host:port`, e.g. '
    '`10.151.41.7:3128`; an `http://` prefix is accepted and ignored. An IP '
    'is recommended because the LXD proxy device does not resolve hostnames.',
)

