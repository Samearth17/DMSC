from html.parser import HTMLParser
import time
from urllib.parse import urlencode,urlsplit
from urllib.robotparser import RobotFileParser
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from app.connectors.base import Batch,ConnectorError,SourceConnector
from app.connectors.news.connector import NoRedirect
from app.connectors.web.http import PublicHTTP,FetchError
from app.normalization.models import WatchtowerEvent


class ReadableText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts=[]
        self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','noscript','svg'}:
            self.hidden+=1
    def handle_endtag(self,tag):
        if tag in {'script','style','noscript','svg'}:
            self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


class WebConnector(SourceConnector):
    platform="web"
    version="1-bing-rss-public-html"
    domains=()

    def search(self,query,policy):
        term=query.text
        if self.domains:
            term+=' site:'+self.domains[0]
        url='https://www.bing.com/search?'+urlencode({'format':'rss','q':term,'count':policy.items_per_query})
        try:
            with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url,
                    headers={'User-Agent':'Watchtower/0.3 public search monitor'}),timeout=min(15,policy.timeout_seconds)) as r:
                body=r.read(4*1024*1024+1)
            if len(body)>4*1024*1024 or b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
                raise ValueError()
            root=ET.fromstring(body)
            if root.tag!='rss' or root.find('channel') is None:
                raise ValueError()
        except urllib.error.HTTPError as exc:
            raise ConnectorError(f'{self.platform}_discovery_http_{exc.code}',requests=1,rate_limited=exc.code==429) from None
        except (OSError,urllib.error.URLError):
            raise ConnectorError(f'{self.platform}_discovery_network_error',requests=1,retryable=True) from None
        except (ValueError,ET.ParseError):
            raise ConnectorError(f'{self.platform}_discovery_invalid_feed',requests=1) from None
        records,warnings=[],[]
        client=PublicHTTP(timeout=min(10,policy.timeout_seconds))
        started=time.monotonic()
        robots={}
        fetches=0
        for item in root.findall('./channel/item')[:policy.items_per_query]:
            link=item.findtext('link') or ''
            target=urlsplit(link)
            if target.scheme not in {'http','https'} or not target.hostname:
                continue
            if self.domains and not any(target.hostname==d or target.hostname.endswith('.'+d) for d in self.domains):
                continue
            raw={'url':link,'title':item.findtext('title') or '', 'snippet':item.findtext('description') or '',
                 'raw_xml':ET.tostring(item,encoding='unicode'),'provider':'bing_rss',
                 'collection_status':'search_snippet_only','body_text':'','raw_html':None}
            if fetches<policy.pages_per_query and time.monotonic()-started<policy.timeout_seconds:
                fetches+=1
                origin=target.scheme+'://'+target.netloc
                try:
                    if origin not in robots:
                        try:
                            robot_body,_,_=client.get(origin+'/robots.txt')
                            rp=RobotFileParser()
                            rp.parse(robot_body.decode('utf-8',errors='replace').splitlines())
                            robots[origin]=rp
                        except FetchError as exc:
                            if exc.status==404:
                                robots[origin]=None
                            else:
                                raise FetchError('web_http_429' if exc.status==429 else 'robots_unavailable',exc.status)
                    rp=robots[origin]
                    if rp is not None and not rp.can_fetch('Watchtower',link):
                        raise FetchError('robots_disallowed')
                    page,headers,final_url=client.get(link)
                    if self.domains and not any(urlsplit(final_url).hostname==d or (urlsplit(final_url).hostname or '').endswith('.'+d) for d in self.domains):
                        raise FetchError('unexpected_platform_redirect')
                    if 'text/html' not in headers.get('content-type','') and 'text/plain' not in headers.get('content-type',''):
                        raise FetchError('unsupported_content_type')
                    html=page.decode('utf-8',errors='replace')
                    if any(marker in html.lower() for marker in ('checkpoint/?','id="login_form"','captcha-container','consent-required')):
                        raise FetchError('login_or_challenge_required')
                    parser=ReadableText()
                    parser.feed(html)
                    text='\n'.join(parser.parts)
                    if len(text.strip())<80:
                        raise FetchError('insufficient_public_text')
                    raw.update(raw_html=html,body_text=text[:100000],collection_status='public_page_text',final_url=final_url)
                except FetchError as exc:
                    raw['collection_error']=exc.code
                    warnings.append(exc.code)
            records.append(raw)
            if client.limited:
                break
        # The HTML client's network/redirect accounting is not complete for connection failures.
        # Report opaque HTTP totals rather than manufacture an exact count.
        return Batch(records,requests=None if fetches else 1,warnings=sorted(set(warnings)),
                     raw_response=body.decode('utf-8',errors='replace'),rate_limited=bool(client.limited))

    def normalize(self,raw):
        return WatchtowerEvent(platform=self.platform,source_type='public_page',source_id=urlsplit(raw['url']).hostname,
            item_id=raw['url'],url=raw['url'],content=raw['title']+'\n'+(raw.get('body_text') or raw['snippet']),
            metadata={'title':raw['title'],'collection_scope':raw['collection_status'],
                      'discovery_provider':raw['provider'],'collection_error':raw.get('collection_error'),
                      'final_url':raw.get('final_url'),'source_authorship':'not_verified'}).validate()
