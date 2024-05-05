from django.conf import settings
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse
from django.test import TestCase, modify_settings, override_settings
from django.urls import reverse


class TestAuthenticationMiddleware(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "test_user", "test@example.com", "test_password"
        )

    def setUp(self):
        self.middleware = AuthenticationMiddleware(lambda req: HttpResponse())
        self.client.force_login(self.user)
        self.request = HttpRequest()
        self.request.session = self.client.session

    def test_no_password_change_doesnt_invalidate_session(self):
        self.request.session = self.client.session
        self.middleware(self.request)
        self.assertIsNotNone(self.request.user)
        self.assertFalse(self.request.user.is_anonymous)

    def test_changed_password_invalidates_session(self):
        # After password change, user should be anonymous
        self.user.set_password("new_password")
        self.user.save()
        self.middleware(self.request)
        self.assertIsNotNone(self.request.user)
        self.assertTrue(self.request.user.is_anonymous)
        # session should be flushed
        self.assertIsNone(self.request.session.session_key)

    def test_no_session(self):
        msg = (
            "The Django authentication middleware requires session middleware "
            "to be installed. Edit your MIDDLEWARE setting to insert "
            "'django.contrib.sessions.middleware.SessionMiddleware' before "
            "'django.contrib.auth.middleware.AuthenticationMiddleware'."
        )
        with self.assertRaisesMessage(ImproperlyConfigured, msg):
            self.middleware(HttpRequest())

    async def test_auser(self):
        self.middleware(self.request)
        auser = await self.request.auser()
        self.assertEqual(auser, self.user)
        auser_second = await self.request.auser()
        self.assertIs(auser, auser_second)


@override_settings(ROOT_URLCONF="auth_tests.urls")
@modify_settings(
    MIDDLEWARE={"append": "django.contrib.auth.middleware.LoginRequiredMiddleware"}
)
class TestLoginRequiredMiddleware(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "test_user", "test@example.com", "test_password"
        )
        cls.paths = [
            "public_view",
            "public_function_view",
            "protected_view",
            "protected_function_view",
            "login_required_mixin",
            "login_required_decorator",
        ]

    def test_access(self):
        for path in self.paths:
            with self.subTest(path=path):
                response = self.client.get(f"/{path}/")
                if "public" in path:
                    self.assertEqual(response.status_code, 200)
                elif "protected" in path:
                    self.assertRedirects(
                        response,
                        settings.LOGIN_URL + f"?next=/{path}/",
                        fetch_redirect_response=False,
                    )
                elif "login_required" in path:
                    # Tests views with login_required decorator and mixin
                    self.assertRedirects(
                        response,
                        "/custom_login/" + f"?step=/{path}/",
                        fetch_redirect_response=False,
                    )

        admin_url = reverse("admin:index")
        response = self.client.get(admin_url)
        self.assertRedirects(
            response,
            reverse("admin:login") + f"?next={admin_url}",
            fetch_redirect_response=False,
        )

        response = self.client.get("/non_existent/")
        self.assertEqual(response.status_code, 404)

        self.client.login(username="test_user", password="test_password")

        for path in self.paths:
            with self.subTest(path=path):
                response = self.client.get(f"/{path}/")
                self.assertEqual(response.status_code, 200)

    @modify_settings(
        MIDDLEWARE={"remove": "django.contrib.auth.middleware.AuthenticationMiddleware"}
    )
    def test_no_authentication_middleware(self):
        msg = (
            "The Django login required middleware requires authentication "
            "middleware to be installed. Edit your MIDDLEWARE setting to "
            "insert "
            "'django.contrib.auth.middleware.AuthenticationMiddleware' "
            "before "
            "'django.contrib.auth.middleware.LoginRequiredMiddleware'."
        )
        with self.assertRaisesMessage(ImproperlyConfigured, msg):
            self.client.get("/public_view/")
