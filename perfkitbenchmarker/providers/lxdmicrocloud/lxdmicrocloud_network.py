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

"""Networking primitives for the LXD MicroCloud provider.

MicroCloud provisions OVN networking up-front (managed `default` network +
`UPLINK`). PKB does not own those resources, so the firewall is a no-op and
the network class only carries the CLOUD attribute required by the resource
registry. PKB-to-instance traffic flows over the OVN-assigned address that
LXD reports via `lxc list --format json`.
"""

from perfkitbenchmarker import network, provider_info


class LxdMicrocloudFirewall(network.BaseFirewall):
  """No-op firewall.

  MicroCloud's OVN network is permissive between cluster members and PKB
  itself, and the LXD instance has no host-level firewall by default. We log
  nothing because the base class's `pass` implementations are intentional.
  """

  CLOUD = provider_info.LXDMICROCLOUD


class LxdMicrocloudNetwork(network.BaseNetwork):
  """Thin network wrapper for MicroCloud.

  MicroCloud manages the cluster network out-of-band, so Create/Delete are
  no-ops inherited from BaseNetwork. This class exists only so the resource
  registry can map (CLOUD=LxdMicrocloud, zone=...) to something concrete.
  """

  CLOUD = provider_info.LXDMICROCLOUD
