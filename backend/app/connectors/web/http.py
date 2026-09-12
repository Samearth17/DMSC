"""Small public-web client with DNS pinning, redirect checks, and byte limits."""
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urlsplit, urljoin


class FetchError(Exception):
    def __init__(self,code,status=None):
        super().__init__(code)
        self.code,self.status=code,status


def public_addresses(host,port):
    addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    ips=list(dict.fromkeys(row[4][0] for row in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise FetchError("non_public_address_blocked")
    return ips


class PublicHTTP:
    def __init__(self,timeout=10,max_bytes=2*1024*1024):
        self.timeout,self.max_bytes=timeout,max_bytes
        self.requests=self.failed=self.limited=0

    def get(self,url):
        deadline=time.monotonic()+self.timeout
        original=urlsplit(url)
        for _ in range(4):
            target=urlsplit(url)
            if target.hostname != original.hostname:
                raise FetchError("cross_host_redirect_not_followed")
            if target.scheme not in {"http","https"} or not target.hostname or target.username or target.password:
                raise FetchError("invalid_public_url")
            port=target.port or (443 if target.scheme=="https" else 80)
            if port not in {80,443}:
                raise FetchError("non_standard_port_blocked")
            try:
                ips=public_addresses(target.hostname,port)
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    raise FetchError("web_timeout")
                # Connect to the validated numeric address, not a second DNS lookup.
                sock=socket.create_connection((ips[0],port),timeout=remaining)
                if target.scheme=="https":
                    sock=ssl.create_default_context().wrap_socket(sock,server_hostname=target.hostname)
                conn=http.client.HTTPConnection(target.hostname,port,timeout=remaining)
                conn.sock=sock
                self.requests+=1
                try:
                    path=target.path or "/"
                    if target.query:
                        path+="?"+target.query
                    conn.request("GET",path,headers={"Host":target.netloc,"User-Agent":"Watchtower/0.3 public-information audit",
                                                     "Accept":"text/html,text/plain,application/rss+xml,application/xml"})
                    response=conn.getresponse()
                    status=response.status
                    headers={k.lower():v for k,v in response.getheaders()}
                    if status in {301,302,303,307,308}:
                        destination=headers.get("location")
                        if not destination:
                            raise FetchError("invalid_redirect",status)
                        url=urljoin(url,destination)
                        continue
                    if status>=400:
                        self.failed+=1
                        self.limited+=int(status==429)
                        raise FetchError(f"web_http_{status}",status)
                    body=response.read(self.max_bytes+1)
                    if len(body)>self.max_bytes:
                        raise FetchError("web_response_too_large")
                    return body,headers,url
                finally:
                    conn.close()
            except FetchError:
                raise
            except (OSError,http.client.HTTPException,ValueError):
                raise FetchError("web_network_error") from None
        raise FetchError("redirect_limit")
