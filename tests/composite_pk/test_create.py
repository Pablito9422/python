import unittest

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext, tag

from .models import Tenant, User


@tag("composite")
class CompositePKCreateTests(TestCase):
    """
    Test the .create(), .save(), .bulk_create(), .get_or_create(), .update_or_create()
    methods of composite_pk models.
    """

    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create()

    @unittest.skipUnless(connection.vendor == "sqlite", "SQLite specific test")
    def test_create_user_in_sqlite(self):
        test_cases = [
            {"tenant": self.tenant, "id": 2412, "email": "user2412@example.com"},
            {"tenant_id": self.tenant.id, "id": 5316, "email": "user5316@example.com"},
            {"pk": (self.tenant.id, 7424), "email": "user7424@example.com"},
        ]

        for fields in test_cases:
            user = User(**fields)
            self.assertIsNotNone(user.id)
            self.assertIsNotNone(user.email)

            with self.subTest(fields=fields):
                with CaptureQueriesContext(connection) as context:
                    obj = User.objects.create(**fields)

                self.assertEqual(obj.tenant_id, self.tenant.id)
                self.assertEqual(obj.id, user.id)
                self.assertEqual(obj.pk, (self.tenant.id, user.id))
                self.assertEqual(obj.email, user.email)
                self.assertEqual(len(context.captured_queries), 1)
                u = User._meta.db_table
                self.assertEqual(
                    context.captured_queries[0]["sql"],
                    f'INSERT INTO "{u}" ("tenant_id", "id", "email") '
                    f"VALUES ({self.tenant.id}, {user.id}, '{user.email}')",
                )

    @unittest.skipUnless(connection.vendor == "postgresql", "PostgreSQL specific test")
    def test_create_user_in_postgresql(self):
        test_cases = [
            {"tenant": self.tenant, "id": 5231, "email": "user5231@example.com"},
            {"tenant_id": self.tenant.id, "id": 6123, "email": "user6123@example.com"},
            {"pk": (self.tenant.id, 3513), "email": "user3513@example.com"},
        ]

        for fields in test_cases:
            user = User(**fields)
            self.assertIsNotNone(user.id)
            self.assertIsNotNone(user.email)

            with self.subTest(fields=fields):
                with CaptureQueriesContext(connection) as context:
                    obj = User.objects.create(**fields)

                self.assertEqual(obj.tenant_id, self.tenant.id)
                self.assertEqual(obj.id, user.id)
                self.assertEqual(obj.pk, (self.tenant.id, user.id))
                self.assertEqual(obj.email, user.email)
                self.assertEqual(len(context.captured_queries), 1)
                u = User._meta.db_table
                self.assertEqual(
                    context.captured_queries[0]["sql"],
                    f'INSERT INTO "{u}" ("tenant_id", "id", "email") '
                    f"VALUES ({self.tenant.id}, {user.id}, '{user.email}') "
                    f'RETURNING "{u}"."id"',
                )

    @unittest.skipUnless(connection.vendor == "postgresql", "PostgreSQL specific test")
    def test_create_user_with_autofield_in_postgresql(self):
        test_cases = [
            {"tenant": self.tenant, "email": "user1111@example.com"},
            {"tenant_id": self.tenant.id, "email": "user2222@example.com"},
        ]

        for fields in test_cases:
            user = User(**fields)
            self.assertIsNotNone(user.email)

            with CaptureQueriesContext(connection) as context:
                obj = User.objects.create(**fields)

            self.assertEqual(obj.tenant_id, self.tenant.id)
            self.assertIsInstance(obj.id, int)
            self.assertGreater(obj.id, 0)
            self.assertEqual(obj.pk, (self.tenant.id, obj.id))
            self.assertEqual(obj.email, user.email)
            self.assertEqual(len(context.captured_queries), 1)
            u = User._meta.db_table
            self.assertEqual(
                context.captured_queries[0]["sql"],
                f'INSERT INTO "{u}" ("tenant_id", "email") '
                f"VALUES ({self.tenant.id}, '{user.email}') "
                f'RETURNING "{u}"."id"',
            )

    def test_save_user(self):
        user = User(tenant=self.tenant, id=9241, email="user9241@example.com")
        user.save()
        self.assertEqual(user.tenant_id, self.tenant.id)
        self.assertEqual(user.tenant, self.tenant)
        self.assertEqual(user.id, 9241)
        self.assertEqual(user.pk, (self.tenant.id, 9241))
        self.assertEqual(user.email, "user9241@example.com")

    @unittest.skipUnless(connection.vendor == "sqlite", "SQLite specific test")
    def test_bulk_create_users_in_sqlite(self):
        objs = [
            User(tenant=self.tenant, id=8291, email="user8291@example.com"),
            User(tenant_id=self.tenant.id, id=4021, email="user4021@example.com"),
            User(pk=(self.tenant.id, 8214), email="user8214@example.com"),
        ]

        with CaptureQueriesContext(connection) as context:
            result = User.objects.bulk_create(objs)

        obj_1, obj_2, obj_3 = result
        self.assertEqual(obj_1.tenant_id, self.tenant.id)
        self.assertEqual(obj_1.id, 8291)
        self.assertEqual(obj_1.pk, (obj_1.tenant_id, obj_1.id))
        self.assertEqual(obj_2.tenant_id, self.tenant.id)
        self.assertEqual(obj_2.id, 4021)
        self.assertEqual(obj_2.pk, (obj_2.tenant_id, obj_2.id))
        self.assertEqual(obj_3.tenant_id, self.tenant.id)
        self.assertEqual(obj_3.id, 8214)
        self.assertEqual(obj_3.pk, (obj_3.tenant_id, obj_3.id))
        self.assertEqual(len(context.captured_queries), 1)
        u = User._meta.db_table
        self.assertEqual(
            context.captured_queries[0]["sql"],
            f'INSERT INTO "{u}" ("tenant_id", "id", "email") '
            f"VALUES ({self.tenant.id}, 8291, 'user8291@example.com'), "
            f"({self.tenant.id}, 4021, 'user4021@example.com'), "
            f"({self.tenant.id}, 8214, 'user8214@example.com')",
        )

    @unittest.skipUnless(connection.vendor == "postgresql", "PostgreSQL specific test")
    def test_bulk_create_users_in_postgresql(self):
        objs = [
            User(tenant=self.tenant, id=8361, email="user8361@example.com"),
            User(tenant_id=self.tenant.id, id=2819, email="user2819@example.com"),
            User(pk=(self.tenant.id, 9136), email="user9136@example.com"),
            User(tenant=self.tenant, email="user1111@example.com"),
            User(tenant_id=self.tenant.id, email="user2222@example.com"),
        ]

        with CaptureQueriesContext(connection) as context:
            result = User.objects.bulk_create(objs)

        obj_1, obj_2, obj_3, obj_4, obj_5 = result
        self.assertEqual(obj_1.tenant_id, self.tenant.id)
        self.assertEqual(obj_1.id, 8361)
        self.assertEqual(obj_1.pk, (obj_1.tenant_id, obj_1.id))
        self.assertEqual(obj_2.tenant_id, self.tenant.id)
        self.assertEqual(obj_2.id, 2819)
        self.assertEqual(obj_2.pk, (obj_2.tenant_id, obj_2.id))
        self.assertEqual(obj_3.tenant_id, self.tenant.id)
        self.assertEqual(obj_3.id, 9136)
        self.assertEqual(obj_3.pk, (obj_3.tenant_id, obj_3.id))
        self.assertEqual(obj_4.tenant_id, self.tenant.id)
        self.assertIsInstance(obj_4.id, int)
        self.assertGreater(obj_4.id, 0)
        self.assertEqual(obj_4.pk, (obj_4.tenant_id, obj_4.id))
        self.assertEqual(obj_5.tenant_id, self.tenant.id)
        self.assertIsInstance(obj_5.id, int)
        self.assertGreater(obj_5.id, obj_4.id)
        self.assertEqual(obj_5.pk, (obj_5.tenant_id, obj_5.id))
        self.assertEqual(len(context.captured_queries), 2)
        u = User._meta.db_table
        self.assertEqual(
            context.captured_queries[0]["sql"],
            f'INSERT INTO "{u}" ("tenant_id", "id", "email") '
            f"VALUES ({self.tenant.id}, 8361, 'user8361@example.com'), "
            f"({self.tenant.id}, 2819, 'user2819@example.com'), "
            f"({self.tenant.id}, 9136, 'user9136@example.com') "
            f'RETURNING "{u}"."id"',
        )
        self.assertEqual(
            context.captured_queries[1]["sql"],
            f'INSERT INTO "{u}" ("tenant_id", "email") '
            f"VALUES ({self.tenant.id}, 'user1111@example.com'), "
            f"({self.tenant.id}, 'user2222@example.com') "
            f'RETURNING "{u}"."id"',
        )

    def test_get_or_create_user_by_pk(self):
        user, created = User.objects.get_or_create(pk=(self.tenant.id, 8314))

        self.assertTrue(created)
        self.assertEqual(1, User.objects.all().count())
        self.assertEqual(user.pk, (self.tenant.id, 8314))
        self.assertEqual(user.tenant_id, self.tenant.id)
        self.assertEqual(user.id, 8314)

    def test_update_or_create_user_by_pk(self):
        user, created = User.objects.update_or_create(pk=(self.tenant.id, 2931))

        self.assertTrue(created)
        self.assertEqual(1, User.objects.all().count())
        self.assertEqual(user.pk, (self.tenant.id, 2931))
        self.assertEqual(user.tenant_id, self.tenant.id)
        self.assertEqual(user.id, 2931)
