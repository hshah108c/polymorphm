# -*- mode: python; coding: utf-8 -*-
#
# Copyright 2013 Andrej Antonov <polymorphm@gmail.com>.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

assert str is not bytes

import struct
import socket
from . import monkey_patch

DEFAULT_PROXY_TIMEOUT = 60.0

class SocksProxyError(Exception):
    pass

class ArgSocksProxyError(SocksProxyError):
    pass

class FormatSocksProxyError(SocksProxyError):
    pass

class AuthSocksProxyError(SocksProxyError):
    pass

class ConnectSocksProxyError(SocksProxyError):
    pass

def recv_all_into(sock, buf):
    buf = memoryview(buf)
    recv_res = 0
    
    while recv_res < len(buf):
        if recv_res > 0:
            buf = buf[recv_res:]
        recv_res = sock.recv(buf)

_CREATE_CONNECTION_DEFAULT_VALUE = object()

def socks_proxy_create_connection(
        address,
        timeout=_CREATE_CONNECTION_DEFAULT_VALUE,
        source_address=_CREATE_CONNECTION_DEFAULT_VALUE,
        **kwargs):
    monkey_patch.assert_patched()
    
    proxy_address = kwargs['proxy_address']
    proxy_timeout = kwargs.get('proxy_timeout')
    proxy_source_address = kwargs.get('proxy_source_address')
    
    assert proxy_address is not None
    
    if not isinstance(address, (tuple, list)) or \
            len(address) != 2 or \
            not isinstance(address[0], str) or \
            not isinstance(address[1], int):
        raise ArgSocksProxyError(
                'address of connection must be tuple: hostname (str) and port (int)'
                )
    
    hostname, port = address
    proxy_kwargs = {}
    
    if proxy_timeout is not None:
        proxy_kwargs['timeout'] = proxy_timeout
    else:
        proxy_kwargs['timeout'] = DEFAULT_PROXY_TIMEOUT
    
    if proxy_source_address is not None:
        proxy_kwargs['source_address'] = proxy_source_address
    
    sock = monkey_patch.original_create_connection(proxy_address, **proxy_kwargs)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    
    # socks5: greeting phase
    
    sock.sendall(struct.pack(
            '!B!B!B',
            0x05, # SOCKS version number (must be 0x05 for this version)
            0x01, # number of authentication methods supported
            0x00, # authentication methods: no authentication
            ))
    
    recv_data = bytearray(2)
    recv_all_into(sock, recv_data)
    recv_data = struct.unpack('!B!B', recv_data)
    
    if (recv_data[0] != 0x05):
        raise FormatSocksProxyError('invalid socks-proxy format (socks5: greeting phase)')
    
    if (recv_data[1] != 0x00):
        raise AuthSocksProxyError('invalid socks-proxy authorization (socks5: greeting phase)')
    
    # socks5: command phase
    
    assert len(address) == 2
    assert isinstance(address[0], str)
    assert isinstance(address[1], int)
    
    host_bytes = address[0].encode()
    sock.sendall(
            struct.pack(
                    '!B!B!B!B!B',
                    0x05, # SOCKS version number (must be 0x05 for this version)
                    0x01, # establish a TCP/IP stream connection
                    0x00, # reserved, must be 0x00
                    0x03, # address type: Domain name
                    len(host_bytes), # Domain name length
                    )
            +
            host_bytes
            +
            struct.pack(
                    '!H',
                    address[1],
                    )
            )
    
    recv_data = bytearray(2)
    recv_all_into(sock, recv_data)
    recv_data = struct.unpack('!B!B', recv_data)
    
    if (recv_data[0] != 0x05):
        raise FormatSocksProxyError('invalid socks-proxy format (socks5: command phase)')
    
    if (recv_data[1] != 0x00):
        error_descr = recv_data[1]
        
        if recv_data[1] == 0x01:
            error_descr = 'general failure'
        elif recv_data[1] == 0x02:
            error_descr = 'connection not allowed by ruleset'
        elif recv_data[1] == 0x03:
            error_descr = 'network unreachable'
        elif recv_data[1] == 0x04:
            error_descr = 'host unreachable'
        elif recv_data[1] == 0x05:
            error_descr = 'connection refused by destination host'
        elif recv_data[1] == 0x06:
            error_descr = 'TTL expired'
        elif recv_data[1] == 0x07:
            error_descr = 'command not supported / protocol error'
        elif recv_data[1] == 0x08:
            error_descr = 'address type not supported'
        else:
            error_descr = hex(recv_data[1])
        
        raise ConnectSocksProxyError(
                'socks-proxy can not create connection: {!r} (socks5: command phase)'.format(
                        error_descr,
                        ))
    
    recv_data = bytearray(2)
    recv_all_into(sock, recv_data)
    recv_data = struct.unpack('!B!B', recv_data)
    
    if recv_data[1] == 0x01:
        host_recv_type = 'ipv4'
        host_recv_data = bytearray(4)
        recv_all_into(sock, host_recv_data)
    elif recv_data[1] == 0x03:
        host_recv_type = 'domain'
        
        host_len_recv_data = bytearray(1)
        recv_all_into(sock, host_len_recv_data)
        host_len_recv_data = struct.unpack('!B', host_len_recv_data)
        
        host_recv_data = bytearray(host_len_recv_data[0])
        recv_all_into(sock, host_recv_data)
    elif recv_data[1] == 0x04:
        host_recv_type = 'ipv6'
        host_recv_data = bytearray(16)
        recv_all_into(sock, host_recv_data)
    else:
        raise FormatSocksProxyError('invalid socks-proxy format (socks5: command phase)')
    
    port_recv_data = bytearray(2)
    recv_all_into(sock, port_recv_data)
    recv_data = struct.unpack('!H', port_recv_data)
    
    # socks5: end phase. connection is complete. tuning socket and return it
    
    if _CREATE_CONNECTION_DEFAULT_VALUE != timeout:
        socket.settimeout(timeout)
    
    return sock
