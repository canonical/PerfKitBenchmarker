# Copyright 2015 PerfKitBenchmarker Authors. All rights reserved.
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
"""Utilities for working with OpenStack Cloud resources."""


import json
import logging
import socket
import time
from collections import OrderedDict

import requests
import six
from absl import flags

from perfkitbenchmarker import vm_util

FLAGS = flags.FLAGS


class OpenStackCLICommand:
  """An openstack cli command.

  Attributes:
    args: list of strings. Positional args to pass to openstack, typically
      specifying an operation to perform (e.g. ['image', 'list'] to list
      available images).
    flags: OrderedDict mapping flag name string to flag value. Flags to pass to
      openstack cli (e.g. {'os-compute-api-version': '2'}). If a provided value
      is True, the flag is passed to openstack cli without a value. If a
      provided value is a list, the flag is passed to openstack cli multiple
      times, once with each value in the list.
    additional_flags: list of strings. Additional flags to append unmodified to
      the end of the openstack cli command.
  """

  def __init__(self, resource, *args):
    """Initializes an OpenStackCLICommand with the provided args and common

    flags.

    Args:
      resource: An OpenStack resource of type BaseResource.
      *args: sequence of strings. Positional args to pass to openstack cli,
        typically specifying an operation to perform (e.g. ['image', 'list'] to
        list available images).
    """
    self.args = list(args)
    self.flags = OrderedDict()
    self.additional_flags = []
    self._AddCommonFlags(resource)

  def __repr__(self):
    return '{}({})'.format(type(self).__name__, ' '.join(self._GetCommand()))

  def _GetCommand(self):
    """Generates the openstack cli command.

    Returns:
      list of strings. When joined by spaces, forms the openstack cli command.
    """
    cmd = [FLAGS.openstack_cli_path]
    cmd.extend(self.args)
    for flag_name, values in self.flags.items():
      flag_name_str = '--%s' % flag_name
      if values is True:
        cmd.append(flag_name_str)
      else:
        values_iterable = values if isinstance(values, list) else [values]
        for value in values_iterable:
          cmd.append(flag_name_str)
          cmd.append(str(value))
    cmd.extend(self.additional_flags)
    return cmd

  def Issue(self, **kwargs):
    """Tries running the openstack cli command once.

    Args:
      **kwargs: Keyword arguments to forward to vm_util.IssueCommand when
        issuing the openstack cli command.

    Returns:
      A tuple of stdout, stderr, and retcode from running the openstack command.
    """
    if 'raise_on_failure' not in kwargs:
      kwargs['raise_on_failure'] = False
    return vm_util.IssueCommand(self._GetCommand(), **kwargs)

  def IssueRetryable(self, **kwargs):
    """Tries running the openstack cli command until it succeeds or times out.

    Args:
      **kwargs: Keyword arguments to forward to vm_util.IssueRetryableCommand
        when issuing the openstack cli command.

    Returns:
      (stdout, stderr) pair of strings from running the openstack command.
    """
    return vm_util.IssueRetryableCommand(self._GetCommand(), **kwargs)

  def _AddCommonFlags(self, resource):
    """Adds common flags to the command.

    Adds common openstack  flags derived from the PKB flags and provided
    resource.

    Args:
      resource: An OpenStack resource of type BaseResource.
    """
    self.flags['format'] = 'json'
    self.additional_flags.extend(FLAGS.openstack_additional_flags or ())

def update_sync_manager(url, status):
  """Queries canonical-pkb-wrapper sync manager and gets a required action


  Args:
    url: canonical-pkb-wrapper sync manager's url, e.g.: http://192.168.1.53:6547/
    status: the current process status to provide to as an update
  """  
  

  tid=FLAGS.pkbw_thread_id
  logging.info(f'this hostname is {tid}')
  r=requests.put(url, json={'hostname':str(tid), 'status': status})
  res=json.loads(r.text)
  return res


def wait_for_sync_manager_green_light(url, status, sleep_time=50):
  """Repeatidly queries canonical-pkb-wrapper sync manager and waits for a 'start' action


  Args:
    url: canonical-pkb-wrapper sync manager's url, e.g.: http://192.168.1.53:6547/
    status: the current process status to provide to as an update
  """    
  res=update_sync_manager(url, status)
  while res.get('action','') != 'start':
    logging.info(f"Waiting for sync_manager\'s greenlight (currently {res.get('action','unset')})")
    time.sleep(sleep_time)
    res=update_sync_manager(url, status)
  logging.info(f"Sync_manager\'s greenlit start in {int(res['timedelta'])} secs")
  time.sleep(int(res['timedelta']))
  return True

