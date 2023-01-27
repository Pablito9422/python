import threading
import time
from contextlib import contextmanager
from unittest import mock

from multiple_database.routers import TestRouter

from django.core.exceptions import FieldError
from django.db import DatabaseError, NotSupportedError, connection, router, transaction
from django.db.backends.utils import split_identifier
from django.test import (
    TransactionTestCase,
    override_settings,
    skipIfDBFeature,
    skipUnlessDBFeature,
)
from django.test.utils import CaptureQueriesContext

from .models import (
    City,
    CityCountryProxy,
    Country,
    EUCity,
    EUCountry,
    Person,
    PersonProfile,
)


class SelectForUpdateSQLTests(TransactionTestCase):
    available_apps = ["select_for"]

    def assert_has_for_update_sql(self, queries, **kwargs):
        # To keep test cases simple and consistent, always pass in the expected
        # `of` values in `"table"."column"` form and let the column be stripped
        # off here if not required for the backend. Also ensure correct quotes.
        if of := kwargs.get("of"):
            if not connection.features.select_for_update_of_column:
                of = [split_identifier(column)[0] for column in of]
            kwargs["of"] = [connection.ops.quote_name(value) for value in of]

        # Examine the SQL that was executed to determine whether it contains
        # the "SELECT ... FOR UPDATE" stanza.
        for_update_sql = connection.ops.for_update_sql(**kwargs)
        self.assertIs(any(for_update_sql in query["sql"] for query in queries), True)

    @skipUnlessDBFeature("has_select_for_update")
    def test_for_update_sql_generated(self):
        """
        The backend's FOR UPDATE variant appears in generated SQL when
        select_for_update() is invoked.
        """
        with transaction.atomic(), CaptureQueriesContext(connection) as ctx:
            list(Person.objects.select_for_update())
        self.assert_has_for_update_sql(ctx.captured_queries)

    @skipUnlessDBFeature("has_select_for_update_nowait")
    def test_for_update_sql_generated_nowait(self):
        """
        The backend's FOR UPDATE NOWAIT variant appears in generated SQL when
        select_for_update() is invoked.
        """
        with transaction.atomic(), CaptureQueriesContext(connection) as ctx:
            list(Person.objects.select_for_update(nowait=True))
        self.assert_has_for_update_sql(ctx.captured_queries, nowait=True)

    @skipUnlessDBFeature("has_select_for_update_skip_locked")
    def test_for_update_sql_generated_skip_locked(self):
        """
        The backend's FOR UPDATE SKIP LOCKED variant appears in generated SQL
        when select_for_update() is invoked.
        """
        with transaction.atomic(), CaptureQueriesContext(connection) as ctx:
            list(Person.objects.select_for_update(skip_locked=True))
        self.assert_has_for_update_sql(ctx.captured_queries, skip_locked=True)

    @skipUnlessDBFeature("has_select_for_no_key_update")
    def test_for_update_sql_generated_no_key(self):
        """
        The backend's FOR NO KEY UPDATE variant appears in generated SQL when
        select_for_update() is invoked.
        """
        with transaction.atomic(), CaptureQueriesContext(connection) as ctx:
            list(Person.objects.select_for_update(no_key=True))
        self.assert_has_for_update_sql(ctx.captured_queries, no_key=True)

    @skipUnlessDBFeature("has_select_for_update_of")
    def test_for_update_sql_generated_of(self):
        """
        The backend's FOR UPDATE OF variant appears in the generated SQL when
        select_for_update() is invoked.
        """
        with transaction.atomic(), CaptureQueriesContext(connection) as ctx:
            list(
                Person.objects.select_related("born__country")
                .select_for_update(of=("born__country",))
                .select_for_update(of=("self", "born__country"))
            )
        expected = ['"select_for_person"."id"', '"select_for_country"."entity_ptr_id"']
        self.assert_has_for_update_sql(ctx.captured_queries, of=expected)

    @skipUnlessDBFeature("has_select_for_update_of")
    def test_for_update_sql_model_inheritance_generated_of(self):
        with transaction.atomic(), CaptureQueriesContext(connection) as ctx:
            list(EUCountry.objects.select_for_update(of=("self",)))
        expected = ['"select_for_eucountry"."country_ptr_id"']
        self.assert_has_for_update_sql(ctx.captured_queries, of=expected)

    @skipUnlessDBFeature("has_select_for_update_of")
    def test_for_update_sql_model_inheritance_ptr_generated_of(self):
        with transaction.atomic(), CaptureQueriesContext(connection) as ctx:
            list(EUCountry.objects.select_for_update(of=("self", "country_ptr")))
        expected = [
            '"select_for_eucountry"."country_ptr_id"',
            '"select_for_country"."entity_ptr_id"',
        ]
        self.assert_has_for_update_sql(ctx.captured_queries, of=expected)

    @skipUnlessDBFeature("has_select_for_update_of")
    def test_for_update_sql_related_model_inheritance_generated_of(self):
        with transaction.atomic(), CaptureQueriesContext(connection) as ctx:
            list(
                EUCity.objects.select_related("country").select_for_update(
                    of=("self", "country")
                )
            )
        expected = [
            '"select_for_eucity"."id"',
            '"select_for_eucountry"."country_ptr_id"',
        ]
        self.assert_has_for_update_sql(ctx.captured_queries, of=expected)

    @skipUnlessDBFeature("has_select_for_update_of")
    def test_for_update_sql_model_inheritance_nested_ptr_generated_of(self):
        with transaction.atomic(), CaptureQueriesContext(connection) as ctx:
            list(
                EUCity.objects.select_related("country").select_for_update(
                    of=("self", "country__country_ptr")
                )
            )
        expected = ['"select_for_eucity"."id"', '"select_for_country"."entity_ptr_id"']
        self.assert_has_for_update_sql(ctx.captured_queries, of=expected)

    @skipUnlessDBFeature("has_select_for_update_of")
    def test_for_update_sql_multilevel_model_inheritance_ptr_generated_of(self):
        with transaction.atomic(), CaptureQueriesContext(connection) as ctx:
            list(
                EUCountry.objects.select_for_update(
                    of=("country_ptr", "country_ptr__entity_ptr")
                )
            )
        expected = ['"select_for_country"."entity_ptr_id"', '"select_for_entity"."id"']
        self.assert_has_for_update_sql(ctx.captured_queries, of=expected)

    @skipUnlessDBFeature("has_select_for_update_of")
    def test_for_update_sql_model_proxy_generated_of(self):
        with transaction.atomic(), CaptureQueriesContext(connection) as ctx:
            list(
                CityCountryProxy.objects.select_related("country").select_for_update(
                    of=("country",)
                )
            )
        expected = ['"select_for_country"."entity_ptr_id"']
        self.assert_has_for_update_sql(ctx.captured_queries, of=expected)


class SelectForUpdateFeatureTests(TransactionTestCase):
    available_apps = ["select_for"]

    @skipIfDBFeature("has_select_for_update_nowait")
    @skipUnlessDBFeature("has_select_for_update")
    def test_unsupported_nowait_raises_error(self):
        """
        NotSupportedError is raised if a SELECT ... FOR UPDATE NOWAIT is run on
        a database backend that supports FOR UPDATE but not NOWAIT.
        """
        msg = "NOWAIT is not supported on this database backend."
        with self.assertRaisesMessage(NotSupportedError, msg), transaction.atomic():
            Person.objects.select_for_update(nowait=True).get()

    @skipIfDBFeature("has_select_for_update_skip_locked")
    @skipUnlessDBFeature("has_select_for_update")
    def test_unsupported_skip_locked_raises_error(self):
        """
        NotSupportedError is raised if a SELECT ... FOR UPDATE SKIP LOCKED is
        run on a database backend that supports FOR UPDATE but not SKIP LOCKED.
        """
        msg = "SKIP LOCKED is not supported on this database backend."
        with self.assertRaisesMessage(NotSupportedError, msg), transaction.atomic():
            Person.objects.select_for_update(skip_locked=True).get()

    @skipIfDBFeature("has_select_for_update_of")
    @skipUnlessDBFeature("has_select_for_update")
    def test_unsupported_of_raises_error(self):
        """
        NotSupportedError is raised if a SELECT ... FOR UPDATE OF ... is run on
        a database backend that supports FOR UPDATE but not OF.
        """
        msg = "FOR UPDATE OF is not supported on this database backend."
        with self.assertRaisesMessage(NotSupportedError, msg), transaction.atomic():
            Person.objects.select_for_update(of=("self",)).get()

    @skipIfDBFeature("has_select_for_no_key_update")
    @skipUnlessDBFeature("has_select_for_update")
    def test_unsupported_no_key_raises_error(self):
        """
        NotSupportedError is raised if a SELECT ... FOR NO KEY UPDATE ... is
        run on a database backend that supports FOR UPDATE but not NO KEY.
        """
        msg = "FOR NO KEY UPDATE is not supported on this database backend."
        with self.assertRaisesMessage(NotSupportedError, msg), transaction.atomic():
            Person.objects.select_for_update(no_key=True).get()

    @skipIfDBFeature("supports_select_for_update_with_limit")
    def test_unsupported_select_for_update_with_limit(self):
        msg = (
            "LIMIT/OFFSET is not supported with select_for_update on this database "
            "backend."
        )
        with self.assertRaisesMessage(NotSupportedError, msg), transaction.atomic():
            list(Person.objects.order_by("pk").select_for_update()[1:2])

    @skipUnlessDBFeature("has_select_for_update")
    def test_for_update_after_from(self):
        klass = connection.features.__class__
        feature_to_patch = f"{klass.__module__}.{klass.__name__}.for_update_after_from"
        with mock.patch(feature_to_patch, return_value=True), transaction.atomic():
            self.assertIn(
                "FOR UPDATE WHERE",
                str(Person.objects.filter(name="foo").select_for_update().query),
            )


class SelectForUpdateBlockingTests(TransactionTestCase):
    available_apps = ["select_for"]

    def setUp(self):
        # Executed in autocommit mode so that data can be seen inside thread.
        self.country = Country.objects.create(name="United States")

    def build_raw_sql(self, connection, model, **kwargs):
        for_update_sql = connection.ops.for_update_sql(**kwargs)
        table = connection.ops.quote_name(model._meta.db_table)
        return f"SELECT * FROM {table} {for_update_sql};"

    @contextmanager
    def blocking_transaction(self, **kwargs):
        # We need another database connection in transaction to test that one
        # connection issuing a SELECT ... FOR UPDATE will block.
        new_connection = connection.copy()
        try:
            new_connection.set_autocommit(False)
            # Start a blocking transaction.
            cursor = new_connection.cursor()
            sql = self.build_raw_sql(new_connection, Country, **kwargs)
            cursor.execute(sql, ())
            cursor.fetchone()

            yield cursor

        finally:
            # Roll back the blocking transaction.
            cursor.close()
            new_connection.rollback()
            new_connection.set_autocommit(True)
            new_connection.close()

    def run_select_for_update(self, *, status, raw=False, **kwargs):
        """
        Utility method that runs a SELECT FOR UPDATE against all Country
        instances. After the select_for_update, it attempts to update the name
        of the only record, save, and commit.

        This function expects to run in a separate thread.
        """
        status.append("started")
        try:
            # We need to enter transaction management again, as this is done on
            # per-thread basis
            with transaction.atomic():
                if raw:
                    sql = self.build_raw_sql(connection, Country, **kwargs)
                    obj = Country.objects.raw(sql)[0]
                else:
                    obj = Country.objects.select_for_update(**kwargs).get()
                obj.name = "United Kingdom"
                obj.save()
        except (DatabaseError, IndexError, Country.DoesNotExist) as exc:
            status.append(exc)
        else:
            status.append(obj)
        finally:
            # This method is run in a separate thread. It uses its own database
            # connection. Close it without waiting for the GC.
            # Connection cannot be closed on Oracle because cursor is still
            # open. TODO: Check whether this is actually still the case...
            if not raw or connection.vendor != "oracle":
                connection.close()

    def run_blocking_test(self, **kwargs):
        status = []
        thread = threading.Thread(
            target=self.run_select_for_update,
            kwargs={"status": status} | kwargs,
        )
        thread_is_blocking = not kwargs.get("nowait", False) and not kwargs.get(
            "skip_locked", False
        )

        # Start a blocking transaction in the current thread.
        with self.blocking_transaction():
            # Start a separate thread that will attempt to take a lock on the
            # same records as the blocking transaction in the current thread.
            thread.start()

            # Sanity check to ensure that the thread has started.
            while not status:
                time.sleep(0.1)

            # If the query in the thread is non-blocking, the thread should be
            # able to complete before the blocking transaction in the current
            # thread is resolved.
            if not thread_is_blocking:
                thread.join(2.0)

        # Country should not have been modified at this point.
        # Since this isn't using FOR UPDATE it won't block.
        country = Country.objects.get(pk=self.country.pk)
        self.assertEqual(country.name, "United States")

        # If the query in the thread is blocking, it should be able to continue
        # once the earlier blocking transaction is ended.
        if thread_is_blocking:
            thread.join(2.0)

        # Check the thread actually finished and didn't time out to prevent
        # test execution from hanging indefinitely.
        self.assertIs(thread.is_alive(), False)

        # Commit the transaction to ensure that MySQL gets a fresh read, since
        # by default it runs in REPEATABLE READ mode.
        transaction.commit()

        return status[-1]

    @skipUnlessDBFeature("has_select_for_update", "supports_transactions")
    def test_for_update_blocks_on_other_for_update(self):
        """
        A thread running a select_for_update that accesses rows being touched
        by a similar operation on another connection blocks correctly.
        """
        for raw, expected in [(False, Country), (True, Country)]:
            with self.subTest(raw=raw):
                result = self.run_blocking_test(raw=raw)
                self.assertIsInstance(result, expected)

                # Country should have been modified.
                country = Country.objects.get(pk=self.country.pk)
                self.assertEqual(country.name, "United Kingdom")

                # Need to reset to the original value due to subTest().
                Country.objects.filter(pk=self.country.pk).update(name="United States")

    @skipUnlessDBFeature("has_select_for_update_nowait", "supports_transactions")
    def test_for_update_nowait_raises_error_on_block(self):
        """
        If nowait is specified, we expect an error to be raised rather than
        blocking. Also perform the same test for a raw query.
        """
        for raw, expected in [(False, DatabaseError), (True, DatabaseError)]:
            with self.subTest(raw=raw):
                result = self.run_blocking_test(raw=raw, nowait=True)
                self.assertIsInstance(result, expected)

                # Country should not have been modified.
                country = Country.objects.get(pk=self.country.pk)
                self.assertEqual(country.name, "United States")

    @skipUnlessDBFeature("has_select_for_update_skip_locked", "supports_transactions")
    def test_for_update_skip_locked_skips_locked_rows(self):
        """
        If skip_locked is specified, the locked row is skipped resulting in
        Country.DoesNotExist. Also perform the same test for a raw query.
        """
        for raw, expected in [(False, Country.DoesNotExist), (True, IndexError)]:
            with self.subTest(raw=raw):
                result = self.run_blocking_test(raw=raw, skip_locked=True)
                self.assertIsInstance(result, expected)

                # Country should not have been modified.
                country = Country.objects.get(pk=self.country.pk)
                self.assertEqual(country.name, "United States")


class SelectForUpdateTests(TransactionTestCase):
    available_apps = ["select_for"]

    def setUp(self):
        country1 = Country.objects.create(name="Belgium")
        country2 = Country.objects.create(name="France")
        self.city1 = City.objects.create(name="Liberchies", country=country1)
        self.city2 = City.objects.create(name="Samois-sur-Seine", country=country2)
        self.person = Person.objects.create(
            name="Reinhardt", born=self.city1, died=self.city2
        )
        self.person_profile = PersonProfile.objects.create(person=self.person)

    @skipUnlessDBFeature("has_select_for_update_of")
    def test_for_update_of_followed_by_values(self):
        with transaction.atomic():
            values = list(Person.objects.select_for_update(of=("self",)).values("pk"))
        self.assertEqual(values, [{"pk": self.person.pk}])

    @skipUnlessDBFeature("has_select_for_update_of")
    def test_for_update_of_followed_by_values_list(self):
        with transaction.atomic():
            values = list(
                Person.objects.select_for_update(of=("self",)).values_list("pk")
            )
        self.assertEqual(values, [(self.person.pk,)])

    @skipUnlessDBFeature("has_select_for_update_of")
    def test_for_update_of_self_when_self_is_not_selected(self):
        """
        select_for_update(of=['self']) when the only columns selected are from
        related tables.
        """
        with transaction.atomic():
            values = list(
                Person.objects.select_related("born")
                .select_for_update(of=("self",))
                .values("born__name")
            )
        self.assertEqual(values, [{"born__name": self.city1.name}])

    @skipUnlessDBFeature(
        "has_select_for_update_of",
        "supports_select_for_update_with_limit",
    )
    def test_for_update_of_with_exists(self):
        with transaction.atomic():
            qs = Person.objects.select_for_update(of=("self", "born"))
            self.assertIs(qs.exists(), True)

    @skipUnlessDBFeature("has_select_for_update", "has_select_for_update_of")
    def test_unrelated_of_argument_raises_error(self):
        """
        FieldError is raised if a non-relation field is specified in of=(...).
        """
        msg = (
            "Invalid field name(s) given in select_for_update(of=(...)): %s. "
            "Only relational fields followed in the query are allowed. "
            "Choices are: self, born, born__country, "
            "born__country__entity_ptr."
        )
        invalid_of = [
            ("nonexistent",),
            ("name",),
            ("born__nonexistent",),
            ("born__name",),
            ("born__nonexistent", "born__name"),
        ]
        for of in invalid_of:
            with self.subTest(of=of):
                with self.assertRaisesMessage(FieldError, msg % ", ".join(of)):
                    with transaction.atomic():
                        Person.objects.select_related(
                            "born__country"
                        ).select_for_update(of=of).get()

    @skipUnlessDBFeature("has_select_for_update", "has_select_for_update_of")
    def test_related_but_unselected_of_argument_raises_error(self):
        """
        FieldError is raised if a relation field that is not followed in the
        query is specified in of=(...).
        """
        msg = (
            "Invalid field name(s) given in select_for_update(of=(...)): %s. "
            "Only relational fields followed in the query are allowed. "
            "Choices are: self, born, profile."
        )
        for name in ["born__country", "died", "died__country"]:
            with self.subTest(name=name):
                with self.assertRaisesMessage(FieldError, msg % name):
                    with transaction.atomic():
                        Person.objects.select_related("born", "profile").exclude(
                            profile=None
                        ).select_for_update(of=(name,)).get()

    @skipUnlessDBFeature("has_select_for_update", "has_select_for_update_of")
    def test_model_inheritance_of_argument_raises_error_ptr_in_choices(self):
        msg = (
            "Invalid field name(s) given in select_for_update(of=(...)): "
            "name. Only relational fields followed in the query are allowed. "
            "Choices are: self, %s."
        )
        with self.assertRaisesMessage(
            FieldError,
            msg % "country, country__country_ptr, country__country_ptr__entity_ptr",
        ):
            with transaction.atomic():
                EUCity.objects.select_related(
                    "country",
                ).select_for_update(of=("name",)).get()
        with self.assertRaisesMessage(
            FieldError, msg % "country_ptr, country_ptr__entity_ptr"
        ):
            with transaction.atomic():
                EUCountry.objects.select_for_update(of=("name",)).get()

    @skipUnlessDBFeature("has_select_for_update", "has_select_for_update_of")
    def test_model_proxy_of_argument_raises_error_proxy_field_in_choices(self):
        msg = (
            "Invalid field name(s) given in select_for_update(of=(...)): "
            "name. Only relational fields followed in the query are allowed. "
            "Choices are: self, country, country__entity_ptr."
        )
        with self.assertRaisesMessage(FieldError, msg):
            with transaction.atomic():
                CityCountryProxy.objects.select_related(
                    "country",
                ).select_for_update(of=("name",)).get()

    @skipUnlessDBFeature("has_select_for_update", "has_select_for_update_of")
    def test_reverse_one_to_one_of_arguments(self):
        """
        Reverse OneToOneFields may be included in of=(...) as long as NULLs
        are excluded because LEFT JOIN isn't allowed in SELECT FOR UPDATE.
        """
        with transaction.atomic():
            person = (
                Person.objects.select_related(
                    "profile",
                )
                .exclude(profile=None)
                .select_for_update(of=("profile",))
                .get()
            )
            self.assertEqual(person.profile, self.person_profile)

    @skipUnlessDBFeature("has_select_for_update", "supports_transactions")
    def test_for_update_requires_transaction(self):
        """
        A TransactionManagementError is raised
        when a select_for_update query is executed outside of a transaction.
        """
        msg = "select_for_update cannot be used outside of a transaction."
        with self.assertRaisesMessage(transaction.TransactionManagementError, msg):
            list(Person.objects.select_for_update())

    @skipUnlessDBFeature("has_select_for_update", "supports_transactions")
    def test_for_update_requires_transaction_only_in_execution(self):
        """
        No TransactionManagementError is raised
        when select_for_update is invoked outside of a transaction -
        only when the query is executed.
        """
        people = Person.objects.select_for_update()
        msg = "select_for_update cannot be used outside of a transaction."
        with self.assertRaisesMessage(transaction.TransactionManagementError, msg):
            list(people)

    @skipUnlessDBFeature("supports_select_for_update_with_limit")
    def test_select_for_update_with_limit(self):
        other = Person.objects.create(name="Grappeli", born=self.city1, died=self.city2)
        with transaction.atomic():
            qs = list(Person.objects.order_by("pk").select_for_update()[1:2])
            self.assertEqual(qs[0], other)

    @skipUnlessDBFeature("has_select_for_update")
    @override_settings(DATABASE_ROUTERS=[TestRouter()])
    def test_select_for_update_on_multidb(self):
        query = Person.objects.select_for_update()
        self.assertEqual(router.db_for_write(Person), query.db)

    @skipUnlessDBFeature("has_select_for_update")
    def test_select_for_update_with_get(self):
        with transaction.atomic():
            person = Person.objects.select_for_update().get(name="Reinhardt")
        self.assertEqual(person.name, "Reinhardt")

    def test_nowait_and_skip_locked(self):
        with self.assertRaisesMessage(
            ValueError, "The nowait option cannot be used with skip_locked."
        ):
            Person.objects.select_for_update(nowait=True, skip_locked=True)

    def test_ordered_select_for_update(self):
        """
        Subqueries should respect ordering as an ORDER BY clause may be useful
        to specify a row locking order to prevent deadlocks (#27193).
        """
        with transaction.atomic():
            qs = Person.objects.filter(
                id__in=Person.objects.order_by("-id").select_for_update()
            )
            self.assertIn("ORDER BY", str(qs.query))
