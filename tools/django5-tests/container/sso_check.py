"""SSO smoke checks against the running uwsgi (:8013): social-auth OAuth2 and SAML.

Configures GitHub OAuth2 and a SAML SP/IdP through the settings API, then checks the
login redirects, the backend listing and the SAML SP metadata (lxml/xmlsec/python3-saml).
"""
import base64
import datetime
import sys
from urllib.parse import parse_qs, urlparse

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

API = 'http://127.0.0.1:8013'
AUTH = {'Authorization': 'Basic ' + base64.b64encode(b'admin:smoke-pass').decode()}
results = []


def check(name, cond, detail=''):
    results.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name + (f'  [{detail}]' if detail else ''))


def start_login(session, url, headers=None):
    """Follow a login_url like the UI does; submit the launch form if one is returned."""
    import html
    import re

    headers = headers or {'Sec-Fetch-Site': 'same-origin', 'Referer': f'{API}/'}
    r = session.get(f'{API}{url}', headers=headers, allow_redirects=False)
    if r.status_code != 200 or '<form' not in r.text:
        return r
    action = html.unescape(re.search(r'<form[^>]*action="([^"]+)"', r.text).group(1))
    fields = {html.unescape(k): html.unescape(v) for k, v in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', r.text)}
    return session.post(f'{API}{action}', data=fields, headers={'Referer': f'{API}{url}'}, allow_redirects=False)


def self_signed():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'awx-smoke')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    pem_key = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()).decode()
    pem_cert = cert.public_bytes(serialization.Encoding.PEM).decode()
    return pem_cert, pem_key


r = requests.patch(f'{API}/api/v2/settings/github/', headers=AUTH, json={'SOCIAL_AUTH_GITHUB_KEY': 'smoke-key', 'SOCIAL_AUTH_GITHUB_SECRET': 'smoke-secret'})
check('configure GitHub OAuth2', r.status_code == 200, r.status_code)

cert, key = self_signed()
idp_cert = cert.split('-----BEGIN CERTIFICATE-----')[1].split('-----END CERTIFICATE-----')[0].replace('\n', '')
r = requests.patch(
    f'{API}/api/v2/settings/saml/',
    headers=AUTH,
    json={
        'SOCIAL_AUTH_SAML_SP_ENTITY_ID': 'awx-smoke',
        'SOCIAL_AUTH_SAML_SP_PUBLIC_CERT': cert,
        'SOCIAL_AUTH_SAML_SP_PRIVATE_KEY': key,
        'SOCIAL_AUTH_SAML_ORG_INFO': {'en-US': {'name': 'smoke', 'displayname': 'Smoke', 'url': 'https://example.com'}},
        'SOCIAL_AUTH_SAML_TECHNICAL_CONTACT': {'givenName': 'Tech', 'emailAddress': 'tech@example.com'},
        'SOCIAL_AUTH_SAML_SUPPORT_CONTACT': {'givenName': 'Support', 'emailAddress': 'support@example.com'},
        'SOCIAL_AUTH_SAML_ENABLED_IDPS': {
            'smokeidp': {
                'entity_id': 'https://idp.example.com/saml',
                'url': 'https://idp.example.com/sso',
                'x509cert': idp_cert,
                'attr_user_permanent_id': 'name_id',
                'attr_username': 'uid',
                'attr_email': 'mail',
            }
        },
        'SOCIAL_AUTH_SAML_SECURITY_CONFIG': {'requestedAuthnContext': False, 'signMetadata': True, 'authnRequestsSigned': True},
    },
)
check('configure SAML', r.status_code == 200, r.status_code if r.status_code == 200 else r.text[:300])

r = requests.get(f'{API}/api/v2/auth/')
backends = r.json() if r.status_code == 200 else {}
check('GET /api/v2/auth/ lists github and saml:smokeidp', {'github', 'saml:smokeidp'} <= set(backends), sorted(backends))

r = start_login(requests.Session(), backends.get('github', {}).get('login_url', '/sso/login/github/'))
location = r.headers.get('Location', '')
check('GitHub login_url leads to GitHub', r.status_code == 302 and location.startswith('https://github.com/login/oauth/authorize'), location[:80] or f'{r.status_code} {r.text[:300]}')
check('GitHub redirect carries client_id and state', parse_qs(urlparse(location).query).get('client_id') == ['smoke-key'] and 'state' in location)

r = requests.get(f'{API}/sso/metadata/saml/')
check('GET /sso/metadata/saml/ returns signed SP metadata',
      r.status_code == 200 and 'EntityDescriptor' in r.text and 'awx-smoke' in r.text and 'SignatureValue' in r.text, r.text[:120])

r = start_login(requests.Session(), backends.get('saml:smokeidp', {}).get('login_url', '/sso/login/saml/?idp=smokeidp'))
location = r.headers.get('Location', '')
query = parse_qs(urlparse(location).query)
check('SAML login_url leads to IdP with signed SAMLRequest',
      r.status_code == 302 and location.startswith('https://idp.example.com/sso') and 'SAMLRequest' in query and 'Signature' in query, location[:80] or f'{r.status_code} {r.text[:300]}')

# Full SAML login: answer the AuthnRequest with a response signed by the (simulated) IdP.
# The IdP uses the same key pair as the SP here, its certificate is configured above.
SAML_RESPONSE = """<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_resp{uid}" Version="2.0" IssueInstant="{now}" Destination="{acs}" InResponseTo="{request_id}">
<saml:Issuer>https://idp.example.com/saml</saml:Issuer>
<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
<saml:Assertion ID="_assert{uid}" Version="2.0" IssueInstant="{now}">
<saml:Issuer>https://idp.example.com/saml</saml:Issuer>
<saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified">smoke-saml-user</saml:NameID>
<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer"><saml:SubjectConfirmationData NotOnOrAfter="{later}" Recipient="{acs}" InResponseTo="{request_id}"/></saml:SubjectConfirmation></saml:Subject>
<saml:Conditions NotBefore="{earlier}" NotOnOrAfter="{later}"><saml:AudienceRestriction><saml:Audience>awx-smoke</saml:Audience></saml:AudienceRestriction></saml:Conditions>
<saml:AuthnStatement AuthnInstant="{now}" SessionIndex="_session{uid}"><saml:AuthnContext><saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:Password</saml:AuthnContextClassRef></saml:AuthnContext></saml:AuthnStatement>
<saml:AttributeStatement>
<saml:Attribute Name="uid"><saml:AttributeValue>smokesaml</saml:AttributeValue></saml:Attribute>
<saml:Attribute Name="mail"><saml:AttributeValue>smokesaml@example.com</saml:AttributeValue></saml:Attribute>
<saml:Attribute Name="name_id"><saml:AttributeValue>smoke-saml-user</saml:AttributeValue></saml:Attribute>
</saml:AttributeStatement>
</saml:Assertion>
</samlp:Response>"""


def saml_login(tamper_request_id=False):
    import uuid
    import zlib

    from onelogin.saml2.constants import OneLogin_Saml2_Constants
    from onelogin.saml2.utils import OneLogin_Saml2_Utils

    s = requests.Session()
    r = start_login(s, backends.get('saml:smokeidp', {}).get('login_url', '/sso/login/saml/?idp=smokeidp'))
    query = parse_qs(urlparse(r.headers['Location']).query)
    authn_request = zlib.decompress(base64.b64decode(query['SAMLRequest'][0]), -15).decode()
    request_id = authn_request.split(' ID="', 1)[1].split('"', 1)[0]
    if tamper_request_id:
        request_id = '_forged' + request_id[7:]
    acs = f'{API}/sso/complete/saml/'
    fmt = '%Y-%m-%dT%H:%M:%SZ'
    now = datetime.datetime.now(datetime.timezone.utc)
    xml = SAML_RESPONSE.format(
        uid=uuid.uuid4().hex, acs=acs, request_id=request_id, now=now.strftime(fmt),
        earlier=(now - datetime.timedelta(minutes=5)).strftime(fmt), later=(now + datetime.timedelta(minutes=5)).strftime(fmt),
    ).replace('\n', '')
    signed = OneLogin_Saml2_Utils.add_sign(
        xml, key, cert, sign_algorithm=OneLogin_Saml2_Constants.RSA_SHA256, digest_algorithm=OneLogin_Saml2_Constants.SHA256
    )
    data = {'SAMLResponse': base64.b64encode(signed).decode(), 'RelayState': query.get('RelayState', [''])[0]}
    return s, s.post(acs, data=data, allow_redirects=False)


session, r = saml_login()
check('POST /sso/complete/saml/ with signed response logs in', r.status_code == 302 and 'error' not in r.headers.get('Location', ''), f"{r.status_code} {r.headers.get('Location', '')[:80]}")
r = session.get(f'{API}/api/v2/me/')
me = r.json()['results'][0] if r.status_code == 200 else {}
check('SAML user created with mapped attributes', me.get('username') == 'smokesaml' and me.get('email') == 'smokesaml@example.com', {k: me.get(k) for k in ('username', 'email')})

session, r = saml_login(tamper_request_id=True)
r = session.get(f'{API}/api/v2/me/')
check('SAML response for a different AuthnRequest is rejected', r.status_code == 401, r.status_code)

# Login CSRF protection (social-auth-app-django >= 6): no plain GET on social:begin,
# and the launch bridge only serves same-site navigations.
r = requests.get(f'{API}/sso/login/github/', allow_redirects=False)
check('plain GET /sso/login/github/ does not start a login', r.status_code != 302, r.status_code)
if backends.get('github', {}).get('login_url', '').startswith('/sso/launch/'):
    r = requests.get(f"{API}{backends['github']['login_url']}", headers={'Sec-Fetch-Site': 'cross-site'}, allow_redirects=False)
    check('launch bridge rejects cross-site requests', r.status_code == 400, r.status_code)

print(f'\n{sum(results)}/{len(results)} SSO checks passed')
sys.exit(0 if all(results) else 1)
