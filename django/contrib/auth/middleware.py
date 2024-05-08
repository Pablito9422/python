from functools import partial
from urllib.parse import urlparse

from django.conf import settings
from django.contrib import auth
from django.contrib.auth import REDIRECT_FIELD_NAME, load_backend
from django.contrib.auth.backends import RemoteUserBackend
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.shortcuts import resolve_url
from django.utils.deprecation import MiddlewareMixin
from django.utils.functional import SimpleLazyObject


def get_user(request):
    if not hasattr(request, "_cached_user"):
        request._cached_user = auth.get_user(request)
    return request._cached_user


async def auser(request):
    if not hasattr(request, "_acached_user"):
        request._acached_user = await auth.aget_user(request)
    return request._acached_user


class AuthenticationMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if not hasattr(request, "session"):
            raise ImproperlyConfigured(
                "The Django authentication middleware requires session "
                "middleware to be installed. Edit your MIDDLEWARE setting to "
                "insert "
                "'django.contrib.sessions.middleware.SessionMiddleware' before "
                "'django.contrib.auth.middleware.AuthenticationMiddleware'."
            )
        request.user = SimpleLazyObject(lambda: get_user(request))
        request.auser = partial(auser, request)


class LoginRequiredMiddleware(MiddlewareMixin):
    """
    Middleware that forces all views to require login by default.

    Views that have login_not_required decorator or LoginNotRequiredMixin mixin
    will be able to pass through without this validation. Otherwise, it will
    redirect user to login page or a custom login page if the view has
    `login_url` or `redirect_field_name` attributes defined.
    """

    login_url = None
    permission_denied_message = ""
    raise_exception = False
    redirect_field_name = REDIRECT_FIELD_NAME

    def process_request(self, request):
        if not hasattr(request, "user"):
            raise ImproperlyConfigured(
                "The Django login required middleware requires authentication "
                "middleware to be installed. Edit your MIDDLEWARE setting to "
                "insert "
                "'django.contrib.auth.middleware.AuthenticationMiddleware' "
                "before "
                "'django.contrib.auth.middleware.LoginRequiredMiddleware'."
            )

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.user.is_authenticated:
            return None

        view_class = getattr(view_func, "view_class", None)
        if view_class and not getattr(view_class, "login_required", True):
            return None

        if not getattr(view_func, "login_required", True):
            return None

        return self.handle_no_permission(request, view_func)

    def get_login_url(self, view_func):
        """
        Override this method to override the login_url attribute.
        """
        login_url = self.login_url or getattr(view_func, "login_url", None)
        view_class = getattr(view_func, "view_class", None)
        if view_class:
            login_url = getattr(view_class, "login_url", None)
        login_url = login_url or settings.LOGIN_URL
        if not login_url:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} is missing the login_url attribute. Define "
                f"{self.__class__.__name__}.login_url, settings.LOGIN_URL, or override "
                f"{self.__class__.__name__}.get_login_url()."
            )
        return str(login_url)

    def get_permission_denied_message(self):
        """
        Override this method to override the permission_denied_message attribute.
        """
        return self.permission_denied_message

    def get_redirect_field_name(self, view_func):
        """
        Override this method to override the redirect_field_name attribute.
        """
        redirect_field_name = getattr(view_func, "redirect_field_name", None)
        view_class = getattr(view_func, "view_class", None)
        if view_class:
            redirect_field_name = getattr(view_class, "redirect_field_name", None)
        return redirect_field_name or self.redirect_field_name

    def handle_no_permission(self, request, view_func):
        if self.raise_exception or request.user.is_authenticated:
            raise PermissionDenied(self.get_permission_denied_message())

        path = request.build_absolute_uri()
        resolved_login_url = resolve_url(self.get_login_url(view_func))
        # If the login url is the same scheme and net location then use the
        # path as the "next" url.
        login_scheme, login_netloc = urlparse(resolved_login_url)[:2]
        current_scheme, current_netloc = urlparse(path)[:2]
        if (not login_scheme or login_scheme == current_scheme) and (
            not login_netloc or login_netloc == current_netloc
        ):
            path = request.get_full_path()

        return redirect_to_login(
            path,
            resolved_login_url,
            self.get_redirect_field_name(view_func),
        )


class RemoteUserMiddleware(MiddlewareMixin):
    """
    Middleware for utilizing web-server-provided authentication.

    If request.user is not authenticated, then this middleware attempts to
    authenticate the username passed in the ``REMOTE_USER`` request header.
    If authentication is successful, the user is automatically logged in to
    persist the user in the session.

    The header used is configurable and defaults to ``REMOTE_USER``.  Subclass
    this class and change the ``header`` attribute if you need to use a
    different header.
    """

    # Name of request header to grab username from.  This will be the key as
    # used in the request.META dictionary, i.e. the normalization of headers to
    # all uppercase and the addition of "HTTP_" prefix apply.
    header = "REMOTE_USER"
    force_logout_if_no_header = True

    def process_request(self, request):
        # AuthenticationMiddleware is required so that request.user exists.
        if not hasattr(request, "user"):
            raise ImproperlyConfigured(
                "The Django remote user auth middleware requires the"
                " authentication middleware to be installed.  Edit your"
                " MIDDLEWARE setting to insert"
                " 'django.contrib.auth.middleware.AuthenticationMiddleware'"
                " before the RemoteUserMiddleware class."
            )
        try:
            username = request.META[self.header]
        except KeyError:
            # If specified header doesn't exist then remove any existing
            # authenticated remote-user, or return (leaving request.user set to
            # AnonymousUser by the AuthenticationMiddleware).
            if self.force_logout_if_no_header and request.user.is_authenticated:
                self._remove_invalid_user(request)
            return
        # If the user is already authenticated and that user is the user we are
        # getting passed in the headers, then the correct user is already
        # persisted in the session and we don't need to continue.
        if request.user.is_authenticated:
            if request.user.get_username() == self.clean_username(username, request):
                return
            else:
                # An authenticated user is associated with the request, but
                # it does not match the authorized user in the header.
                self._remove_invalid_user(request)

        # We are seeing this user for the first time in this session, attempt
        # to authenticate the user.
        user = auth.authenticate(request, remote_user=username)
        if user:
            # User is valid.  Set request.user and persist user in the session
            # by logging the user in.
            request.user = user
            auth.login(request, user)

    def clean_username(self, username, request):
        """
        Allow the backend to clean the username, if the backend defines a
        clean_username method.
        """
        backend_str = request.session[auth.BACKEND_SESSION_KEY]
        backend = auth.load_backend(backend_str)
        try:
            username = backend.clean_username(username)
        except AttributeError:  # Backend has no clean_username method.
            pass
        return username

    def _remove_invalid_user(self, request):
        """
        Remove the current authenticated user in the request which is invalid
        but only if the user is authenticated via the RemoteUserBackend.
        """
        try:
            stored_backend = load_backend(
                request.session.get(auth.BACKEND_SESSION_KEY, "")
            )
        except ImportError:
            # backend failed to load
            auth.logout(request)
        else:
            if isinstance(stored_backend, RemoteUserBackend):
                auth.logout(request)


class PersistentRemoteUserMiddleware(RemoteUserMiddleware):
    """
    Middleware for web-server provided authentication on logon pages.

    Like RemoteUserMiddleware but keeps the user authenticated even if
    the header (``REMOTE_USER``) is not found in the request. Useful
    for setups when the external authentication via ``REMOTE_USER``
    is only expected to happen on some "logon" URL and the rest of
    the application wants to use Django's authentication mechanism.
    """

    force_logout_if_no_header = False
