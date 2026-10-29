"""Pytest plugin: block outbound network while retaining loopback fixtures."""
import socket


def pytest_sessionstart(session):
    original=socket.socket.connect
    def guarded(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):
            if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1','localhost'):
                raise AssertionError('Outbound network disabled for pre-release offline acceptance')
        return original(sock,address)
    socket.socket.connect=guarded
