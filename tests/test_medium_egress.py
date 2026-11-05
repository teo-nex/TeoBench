import socket
import unittest
from teobench.medium_egress import public_addresses


class EgressTests(unittest.TestCase):
    def resolver(self, ips):
        return lambda *_a,**_k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443)) for ip in ips]

    def test_private_special_and_rebinding_mixtures_denied(self):
        for ip in ['127.0.0.1','10.0.0.1','192.168.0.1','172.16.0.1','169.254.169.254',
                   '100.64.0.2','0.0.0.0','::1','::ffff:127.0.0.1','fc00::1']:
            with self.assertRaises(ValueError):public_addresses('example.com',443,self.resolver([ip]))
            with self.assertRaises(ValueError):public_addresses('example.com',443,self.resolver(['1.1.1.1',ip]))

    def test_only_public_http_ports_allowed(self):
        self.assertEqual(len(public_addresses('example.com',443,self.resolver(['1.1.1.1']))),1)
        for port in [22,25,2375,20128]:
            with self.assertRaises(ValueError):public_addresses('example.com',port,self.resolver(['1.1.1.1']))

    def test_empty_dns_fails_closed(self):
        with self.assertRaises(ValueError):public_addresses('example.com',80,self.resolver([]))
