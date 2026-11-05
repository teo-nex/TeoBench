"""Minimal public HTTP(S) proxy for a disposable internal Docker network.

No host port is published. The proxy container has no credentials or host mounts.
Resolve once, reject every non-global address, then connect to the validated IP.
"""
import ipaddress
import selectors
import socket
import socketserver
import threading
from urllib.parse import urlsplit


def public_addresses(host, port, resolver=socket.getaddrinfo):
    if port not in (80,443) or not host or len(host)>253:
        raise ValueError('public_http_https_only')
    addresses=resolver(host,port,type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError('destination_resolution_failed')
    for family,kind,proto,_,address in addresses:
        ip=ipaddress.ip_address(address[0].split('%',1)[0])
        if not ip.is_global or (getattr(ip,'ipv4_mapped',None) and not ip.ipv4_mapped.is_global):
            raise ValueError('private_or_special_destination_denied')
    return addresses


def connect_public(host,port):
    for family,kind,proto,_,address in public_addresses(host,port):
        stream=socket.socket(family,kind,proto);stream.settimeout(20)
        try:
            stream.connect(address)
            return stream
        except OSError:
            stream.close()
    raise OSError('public_destination_unreachable')


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        remote=None
        try:
            self.connection.settimeout(30)
            line=self.rfile.readline(8193)
            if len(line)>8192:raise ValueError('request_line_limit')
            method,target,version=line.decode('ascii').strip().split(' ')
            if version not in ('HTTP/1.0','HTTP/1.1'):raise ValueError('http_version')
            lines=[];size=0
            while True:
                header=self.rfile.readline(8193);size+=len(header)
                if size>65536 or not header:raise ValueError('header_limit')
                if header in (b'\r\n',b'\n'):break
                if header[:1] in (b' ',b'\t') or b':' not in header:raise ValueError('invalid_header')
                lines.append(header)
            if method=='CONNECT':
                destination=urlsplit('//'+target)
                if destination.username or destination.password:raise ValueError('url_credentials_denied')
                remote=connect_public(destination.hostname,destination.port or 443)
                self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n');self.wfile.flush()
            else:
                destination=urlsplit(target)
                if destination.scheme!='http' or destination.username or destination.password or destination.fragment:
                    raise ValueError('invalid_proxy_url')
                remote=connect_public(destination.hostname,destination.port or 80)
                path=destination.path or '/'
                if destination.query:path+='?'+destination.query
                # One destination per connection. For plain HTTP force closing;
                # a second absolute-form request cannot reach a different host.
                headers=[h for h in lines if h.split(b':',1)[0].lower() not in
                         (b'proxy-authorization',b'proxy-connection',b'connection',b'host')]
                host=destination.netloc.encode('ascii')
                remote.sendall((method+' '+path+' '+version+'\r\n').encode('ascii')+
                               b''.join(headers)+b'Host: '+host+b'\r\nConnection: close\r\n\r\n')
            # StreamRequestHandler's buffered reader can otherwise prefetch TLS
            # bytes before the selector. rbufsize=0 below prevents that.
            with selectors.DefaultSelector() as selector:
                selector.register(self.connection,selectors.EVENT_READ,remote)
                selector.register(remote,selectors.EVENT_READ,self.connection)
                while True:
                    events=selector.select(timeout=180)
                    if not events:return
                    for key,_ in events:
                        data=key.fileobj.recv(65536)
                        if not data:return
                        key.data.sendall(data)
        except (OSError,ValueError,UnicodeError):
            try:self.wfile.write(b'HTTP/1.1 403 Destination denied\r\nConnection: close\r\nContent-Length: 0\r\n\r\n');self.wfile.flush()
            except OSError:pass
        finally:
            if remote:remote.close()

    rbufsize=0


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
    request_queue_size=16

    def __init__(self,*args,**kwargs):
        self.slots=threading.BoundedSemaphore(32)
        super().__init__(*args,**kwargs)

    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:super().process_request(request,address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()


if __name__=='__main__':
    Server(('0.0.0.0',3128),Handler).serve_forever()
