"""Http(s) polling utility.

The utility allows a user to poll a http(s) endpoint.
The primary motivation for this utility is to wait for the endpoint to be ready.
In support for this use case, the utility accepts the maximum number of retries
and retry interval as an argument in additional to regular connection related
parameters.

This module is tightly coupled with PKB/Artemis infrastructure, but the driver
script can be used as a standalone utility.
"""

import ast
import dataclasses
import logging
from typing import Sequence
from perfkitbenchmarker import data

DRIVER_SCRIPT = 'http/poll_http_endpoint.py'


def _Install(vm):
  vm.Install('curl')
  vm.Install('pip')
  vm.Install('python_dev')
  vm.RemoteCommand('sudo pip3 install absl-py')
  vm.RemoteCopy(data.ResourcePath(DRIVER_SCRIPT))


def YumInstall(vm):
  _Install(vm)


def AptInstall(vm):
  _Install(vm)


_SUCCESS = 'succeed'
_FAILURE_INVALID_RESPONSE = 'invalid_response'


@dataclasses.dataclass(frozen=True)
class PollingResponse:
  """Response from an HTTP poll.

  Attributes:
    success: Whether the poll was successful (200 & matching expected response)
    response: The actual response string
    latency: The latency of the request
  """

  success: bool
  response: str
  latency: float


class HttpPoller:
  """Polls http endpoint."""

  def _BuildCommand(
      self,
      endpoint: str,
      headers: Sequence[str],
      retries: int,
      retry_interval: float,
      timeout: int,
      expected_response_code: str | None,
      expected_response: str | None,
  ):
    """Builds command for polling script."""
    cmd = (
        f'python3 poll_http_endpoint.py --endpoint={endpoint} '
        f'--max_retries={retries} --retry_interval={retry_interval} '
        f'--timeout={timeout}'
    )
    if expected_response:
      cmd += ' --expected_response=%s' % expected_response
    if expected_response_code:
      cmd += ' --expected_response_code=%s' % expected_response_code
    if headers:
      cmd += ' --headers=%s' % ','.join([h.replace(r'\ ', '') for h in headers])
    return cmd

  def Run(
      self,
      vm,
      endpoint: str,
      headers: Sequence[str] = (),
      retries: int = 0,
      retry_interval: float = 0.5,
      timeout: int = 600,
      expected_response_code: int | None = None,
      expected_response: str | None = None,
  ):
    """Polls HTTP endpoint.

    Args:
      vm: VirtualMachine object.
      endpoint: string. Target http endpoint.
      headers: Sequence of string. Http headers to use. By default, we set close
        connection.
      retries: Int. Number of retries.
      retry_interval: Float. Indicates interval in sec between retries.
      timeout: Int. Deadline before giving up.
      expected_response_code: string. Expected http response code. Can be either
        a string or a regex.
      expected_response: string. Expected http response. Can be either a string
        or a regex.

    Returns:
      PollingResponse object, which indicates if endpoint is reachable
        and response is expected as well as the actual response
        and latency of response.
    """
    cmd = self._BuildCommand(
        endpoint,
        headers,
        retries,
        retry_interval,
        timeout,
        expected_response_code,
        expected_response,
    )
    out, _ = vm.RemoteCommand(cmd)
    latency, ret, resp, _ = ast.literal_eval(out)
    if ret == _FAILURE_INVALID_RESPONSE:
      logging.debug(
          'Failure polling endpoint %s. Received unexpected response %s != '
          'expected %s.',
          endpoint,
          resp,
          expected_response,
      )
    elif float(latency) == -1 or ret != _SUCCESS:
      logging.debug(
          'Unexpected response or unable to reach endpoint %s, resp: %s',
          endpoint,
          resp,
      )
    return PollingResponse(
        success=ret == _SUCCESS, response=resp, latency=latency
    )
