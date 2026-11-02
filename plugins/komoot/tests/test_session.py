"""Reproduce refresh-cookie-only Safari login using urllib's real cookie handler."""
import io
import sys
import unittest
import urllib.error
import urllib.request
from email.message import Message
from http.cookiejar import CookieJar
from pathlib import Path
from unittest.mock import patch
from urllib.response import addinfourl
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import komoot_service as service

class Transport(urllib.request.HTTPSHandler):
    def __init__(self, fail_home=False, fail_api=False):
        super().__init__(); self.requests=[]; self.fail_home=fail_home; self.fail_api=fail_api
    def https_open(self, request):
        self.requests.append(request)
        if request.full_url==service.WEB_ROOT+'/':
            if self.fail_home: raise urllib.error.HTTPError(request.full_url,403,'denied',Message(),io.BytesIO(b''))
            headers=Message(); headers.add_header('Set-Cookie','koa_at=test-fresh; Path=/; Secure; HttpOnly')
            response=addinfourl(io.BytesIO(b'home'),headers,request.full_url,200); response.msg='OK'; return response
        if self.fail_api or 'koa_at=test-fresh' not in request.get_header('Cookie',''):
            raise urllib.error.HTTPError(request.full_url,403,'not authenticated',Message(),io.BytesIO(b''))
        response=addinfourl(io.BytesIO(b'{"ok":true}'),Message(),request.full_url,200); response.msg='OK'; return response

class SessionTests(unittest.TestCase):
    def run_request(self, transport, **kwargs):
        real_build=urllib.request.build_opener
        def build(*handlers): return real_build(transport,*handlers)
        with patch.object(service,'_cookie_jar',return_value=CookieJar()), patch.object(service.urllib.request,'build_opener',side_effect=build):
            return service._request_bytes(service.API_ROOT+'/tours/123',**kwargs)
    def test_api_receives_homepage_session_cookie(self):
        t=Transport(); self.assertEqual(self.run_request(t),b'{"ok":true}')
        self.assertEqual(len(t.requests),2)
        self.assertIsNone(t.requests[0].get_header('Cookie'))
        self.assertEqual(t.requests[1].get_header('Cookie'),'koa_at=test-fresh')
    def test_failed_patch_is_never_retried(self):
        t=Transport(fail_api=True)
        with self.assertRaises(service.KomootError): self.run_request(t,method='PATCH',body=b'{}')
        self.assertEqual([r.get_method() for r in t.requests],['GET','PATCH'])
    def test_no_api_write_when_session_initialization_fails(self):
        t=Transport(fail_home=True)
        with self.assertRaises(service.KomootError): self.run_request(t,method='PATCH',body=b'{}')
        self.assertEqual(len(t.requests),1)

if __name__=='__main__': unittest.main()
