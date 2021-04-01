#
# Copyright (c) 2021-2023 Wind River Systems, Inc.
#
# The right to copy, distribute, modify, or otherwise make use
# of this software may be licensed only pursuant to the terms
# of an applicable Wind River license agreement.
#

"""
Implements validation of backup location parameter on request body.

"""

import re

from oslo_config import types


def validate_backup_driver(driver):
    if not driver:
        return
    driver_regex = r'^[A-z]{2,}$'
    match = re.match(driver_regex, driver)
    if not match:
        raise ValueError("Invalid driver: %s." % driver)


def validate_backup_hostpath(location):
    if not location:
        return
    try:
        host, path = location.rsplit(":", maxsplit=1)
    except ValueError:
        raise ValueError("Invalid backup location: %s." % location)
    try:
        _validate_host(host)
        _validate_path(path)
    except ValueError:
        raise


def _validate_host(host):
    maybe_domain = None
    maybe_ipv4 = None
    maybe_ipv6 = None
    maybe_port = None
    host_regex = re.compile(r"""^
        (   (?P<maybe_domain>[a-z0-9.-]+) |
            (?P<maybe_ipv4>[0-9.]+) |
            \[(?P<maybe_ipv6>[0-9a-f:]+)\]
        )
        (   :(?P<maybe_port>\d+)    )?
        $""", re.VERBOSE)
    match = host_regex.match(host)
    if match:
        maybe_domain = match.group("maybe_domain")
        maybe_ipv4 = match.group("maybe_ipv4")
        maybe_ipv6 = match.group("maybe_ipv6")
        maybe_port = match.group("maybe_port")
        try:
            _validate_host_address(maybe_domain or maybe_ipv4 or maybe_ipv6)
            _validate_port(maybe_port)
        except ValueError:
            raise
    else:
        raise ValueError("Invalid host domain, IP address or port: %s." % host)


def _validate_path(path):
    path_regex = r"^/([A-z0-9._-]+/)*[A-z0-9._-]*$"
    match = re.match(path_regex, path)
    if not match:
        raise ValueError("Invalid path: %s." % path)


def _validate_host_address(host_address):
    host_address_type = types.HostAddress()
    try:
        host_address_type(host_address)
    except ValueError:
        raise ValueError("Invalid domain or IP address: %s.", host_address)


def _validate_port(port):
    if not port:
        return
    port_type = types.Port()
    try:
        port_type(port)
    except ValueError:
        raise ValueError("Invalid host port: %s.", port)
