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
