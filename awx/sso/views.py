# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Python
import urllib.parse
import logging

# Django
from django.core.exceptions import BadRequest
from django.urls import reverse
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_deny
from django.views.generic import View
from django.views.generic.base import RedirectView
from django.utils.encoding import smart_str
from django.conf import settings

logger = logging.getLogger('awx.sso.views')


class BaseRedirectView(RedirectView):
    permanent = True

    def get_redirect_url(self, *args, **kwargs):
        last_path = self.request.COOKIES.get('lastPath', '')
        last_path = urllib.parse.quote(urllib.parse.unquote(last_path).strip('"'))
        url = reverse('ui:index')
        if last_path:
            return '%s#%s' % (url, last_path)
        else:
            return url


sso_error = BaseRedirectView.as_view()
sso_inactive = BaseRedirectView.as_view()


class CompleteView(BaseRedirectView):
    def dispatch(self, request, *args, **kwargs):
        response = super(CompleteView, self).dispatch(request, *args, **kwargs)
        if self.request.user and self.request.user.is_authenticated:
            logger.info(smart_str(u"User {} logged in".format(self.request.user.username)))
            response.set_cookie(
                'userLoggedIn', 'true', secure=getattr(settings, 'SESSION_COOKIE_SECURE', False), samesite=getattr(settings, 'USER_COOKIE_SAMESITE', 'Lax')
            )
            response.setdefault('X-API-Session-Cookie-Name', getattr(settings, 'SESSION_COOKIE_NAME', 'awx_sessionid'))
        return response


sso_complete = CompleteView.as_view()


class MetadataView(View):
    def get(self, request, *args, **kwargs):
        from social_django.utils import load_backend, load_strategy

        complete_url = reverse('social:complete', args=('saml',))
        try:
            saml_backend = load_backend(load_strategy(request), 'saml', redirect_uri=complete_url)
            metadata, errors = saml_backend.generate_metadata_xml()
        except Exception as e:
            logger.exception('unable to generate SAML metadata')
            errors = e
        if not errors:
            return HttpResponse(content=metadata, content_type='text/xml')
        else:
            return HttpResponse(content=str(errors), content_type='text/plain')


saml_metadata = MetadataView.as_view()


@never_cache
@xframe_options_deny
def sso_launch(request, backend):
    """
    Start a social login from a plain link, as the UI renders them.

    social-auth-app-django >= 6 only accepts POST with a CSRF token on social:begin
    (login CSRF protection). Render a form with the token that submits itself, after
    checking that the link was followed from this site.
    """
    from social_django.utils import apply_framing_protection, check_fetch_metadata, validate_app_launch_origin

    is_valid_origin, origin_error = validate_app_launch_origin(request)
    if not is_valid_origin:
        logger.warning('sso_launch for %s rejected: %s', backend, origin_error)
        raise BadRequest(origin_error)
    auto_submit, _ = check_fetch_metadata(request, 'sso_launch')
    params = {key: request.GET[key] for key in ('idp', 'next') if key in request.GET}
    response = render(
        request,
        'social_django/launch.html',
        {'action_url': reverse('social:begin', args=(backend,)), 'params': params, 'auto_submit': auto_submit},
    )
    return apply_framing_protection(response)
