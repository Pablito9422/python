from __future__ import absolute_import

import sys

from django.db import connection, transaction, IntegrityError
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import six
from django.utils.unittest import skipUnless

from .models import Reporter


@skipUnless(connection.features.uses_savepoints,
        "'atomic' requires transactions and savepoints.")
class AtomicTests(TransactionTestCase):
    """
    Tests for the atomic decorator and context manager.

    The tests make assertions on internal attributes because there isn't a
    robust way to ask the database for its current transaction state.

    Since the decorator syntax is converted into a context manager (see the
    implementation), there are only a few basic tests with the decorator
    syntax and the bulk of the tests use the context manager syntax.
    """

    def test_decorator_syntax_commit(self):
        @transaction.atomic
        def make_reporter():
            Reporter.objects.create(first_name="Tintin")
        make_reporter()
        self.assertQuerysetEqual(Reporter.objects.all(), ['<Reporter: Tintin>'])

    def test_decorator_syntax_rollback(self):
        @transaction.atomic
        def make_reporter():
            Reporter.objects.create(first_name="Haddock")
            raise Exception("Oops, that's his last name")
        with six.assertRaisesRegex(self, Exception, "Oops"):
            make_reporter()
        self.assertQuerysetEqual(Reporter.objects.all(), [])

    def test_alternate_decorator_syntax_commit(self):
        @transaction.atomic()
        def make_reporter():
            Reporter.objects.create(first_name="Tintin")
        make_reporter()
        self.assertQuerysetEqual(Reporter.objects.all(), ['<Reporter: Tintin>'])

    def test_alternate_decorator_syntax_rollback(self):
        @transaction.atomic()
        def make_reporter():
            Reporter.objects.create(first_name="Haddock")
            raise Exception("Oops, that's his last name")
        with six.assertRaisesRegex(self, Exception, "Oops"):
            make_reporter()
        self.assertQuerysetEqual(Reporter.objects.all(), [])

    def test_commit(self):
        with transaction.atomic():
            Reporter.objects.create(first_name="Tintin")
        self.assertQuerysetEqual(Reporter.objects.all(), ['<Reporter: Tintin>'])

    def test_rollback(self):
        with six.assertRaisesRegex(self, Exception, "Oops"):
            with transaction.atomic():
                Reporter.objects.create(first_name="Haddock")
                raise Exception("Oops, that's his last name")
        self.assertQuerysetEqual(Reporter.objects.all(), [])

    def test_nested_commit_commit(self):
        with transaction.atomic():
            Reporter.objects.create(first_name="Tintin")
            with transaction.atomic():
                Reporter.objects.create(first_name="Archibald", last_name="Haddock")
        self.assertQuerysetEqual(Reporter.objects.all(),
                ['<Reporter: Archibald Haddock>', '<Reporter: Tintin>'])

    def test_nested_commit_rollback(self):
        with transaction.atomic():
            Reporter.objects.create(first_name="Tintin")
            with six.assertRaisesRegex(self, Exception, "Oops"):
                with transaction.atomic():
                    Reporter.objects.create(first_name="Haddock")
                    raise Exception("Oops, that's his last name")
        self.assertQuerysetEqual(Reporter.objects.all(), ['<Reporter: Tintin>'])

    def test_nested_rollback_commit(self):
        with six.assertRaisesRegex(self, Exception, "Oops"):
            with transaction.atomic():
                Reporter.objects.create(last_name="Tintin")
                with transaction.atomic():
                    Reporter.objects.create(last_name="Haddock")
                raise Exception("Oops, that's his first name")
        self.assertQuerysetEqual(Reporter.objects.all(), [])

    def test_nested_rollback_rollback(self):
        with six.assertRaisesRegex(self, Exception, "Oops"):
            with transaction.atomic():
                Reporter.objects.create(last_name="Tintin")
                with six.assertRaisesRegex(self, Exception, "Oops"):
                    with transaction.atomic():
                        Reporter.objects.create(first_name="Haddock")
                    raise Exception("Oops, that's his last name")
                raise Exception("Oops, that's his first name")
        self.assertQuerysetEqual(Reporter.objects.all(), [])

    def test_reuse_commit_commit(self):
        atomic = transaction.atomic()
        with atomic:
            Reporter.objects.create(first_name="Tintin")
            with atomic:
                Reporter.objects.create(first_name="Archibald", last_name="Haddock")
        self.assertQuerysetEqual(Reporter.objects.all(),
                ['<Reporter: Archibald Haddock>', '<Reporter: Tintin>'])

    def test_reuse_commit_rollback(self):
        atomic = transaction.atomic()
        with atomic:
            Reporter.objects.create(first_name="Tintin")
            with six.assertRaisesRegex(self, Exception, "Oops"):
                with atomic:
                    Reporter.objects.create(first_name="Haddock")
                    raise Exception("Oops, that's his last name")
        self.assertQuerysetEqual(Reporter.objects.all(), ['<Reporter: Tintin>'])

    def test_reuse_rollback_commit(self):
        atomic = transaction.atomic()
        with six.assertRaisesRegex(self, Exception, "Oops"):
            with atomic:
                Reporter.objects.create(last_name="Tintin")
                with atomic:
                    Reporter.objects.create(last_name="Haddock")
                raise Exception("Oops, that's his first name")
        self.assertQuerysetEqual(Reporter.objects.all(), [])

    def test_reuse_rollback_rollback(self):
        atomic = transaction.atomic()
        with six.assertRaisesRegex(self, Exception, "Oops"):
            with atomic:
                Reporter.objects.create(last_name="Tintin")
                with six.assertRaisesRegex(self, Exception, "Oops"):
                    with atomic:
                        Reporter.objects.create(first_name="Haddock")
                    raise Exception("Oops, that's his last name")
                raise Exception("Oops, that's his first name")
        self.assertQuerysetEqual(Reporter.objects.all(), [])


class AtomicInsideTransactionTests(AtomicTests):
    """All basic tests for atomic should also pass within an existing transaction."""

    def setUp(self):
        self.atomic = transaction.atomic()
        self.atomic.__enter__()

    def tearDown(self):
        self.atomic.__exit__(*sys.exc_info())


class AtomicInsideLegacyTransactionManagementTests(AtomicTests):

    def setUp(self):
        transaction.enter_transaction_management()

    def tearDown(self):
        # The tests access the database after exercising 'atomic', making the
        # connection dirty; a rollback is required to make it clean.
        transaction.rollback()
        transaction.leave_transaction_management()


@skipUnless(connection.features.uses_savepoints,
        "'atomic' requires transactions and savepoints.")
class AtomicErrorsTests(TransactionTestCase):

    def test_atomic_requires_autocommit(self):
        transaction.set_autocommit(autocommit=False)
        try:
            with self.assertRaises(transaction.TransactionManagementError):
                with transaction.atomic():
                    pass
        finally:
            transaction.set_autocommit(autocommit=True)

    def test_atomic_prevents_disabling_autocommit(self):
        autocommit = transaction.get_autocommit()
        with transaction.atomic():
            with self.assertRaises(transaction.TransactionManagementError):
                transaction.set_autocommit(autocommit=not autocommit)
        # Make sure autocommit wasn't changed.
        self.assertEqual(connection.autocommit, autocommit)

    def test_atomic_prevents_calling_transaction_methods(self):
        with transaction.atomic():
            with self.assertRaises(transaction.TransactionManagementError):
                transaction.commit()
            with self.assertRaises(transaction.TransactionManagementError):
                transaction.rollback()

    def test_atomic_prevents_calling_transaction_management_methods(self):
        with transaction.atomic():
            with self.assertRaises(transaction.TransactionManagementError):
                transaction.enter_transaction_management()
            with self.assertRaises(transaction.TransactionManagementError):
                transaction.leave_transaction_management()

class TransactionTests(TransactionTestCase):
    def create_a_reporter_then_fail(self, first, last):
        a = Reporter(first_name=first, last_name=last)
        a.save()
        raise Exception("I meant to do that")

    def remove_a_reporter(self, first_name):
        r = Reporter.objects.get(first_name="Alice")
        r.delete()

    def manually_managed(self):
        r = Reporter(first_name="Dirk", last_name="Gently")
        r.save()
        transaction.commit()

    def manually_managed_mistake(self):
        r = Reporter(first_name="Edward", last_name="Woodward")
        r.save()
        # Oops, I forgot to commit/rollback!

    @skipUnlessDBFeature('supports_transactions')
    def test_autocommit(self):
        """
        The default behavior is to autocommit after each save() action.
        """
        self.assertRaises(Exception,
            self.create_a_reporter_then_fail,
            "Alice", "Smith"
        )

        # The object created before the exception still exists
        self.assertEqual(Reporter.objects.count(), 1)

    @skipUnlessDBFeature('supports_transactions')
    def test_autocommit_decorator(self):
        """
        The autocommit decorator works exactly the same as the default behavior.
        """
        autocomitted_create_then_fail = transaction.autocommit(
            self.create_a_reporter_then_fail
        )
        self.assertRaises(Exception,
            autocomitted_create_then_fail,
            "Alice", "Smith"
        )
        # Again, the object created before the exception still exists
        self.assertEqual(Reporter.objects.count(), 1)

    @skipUnlessDBFeature('supports_transactions')
    def test_autocommit_decorator_with_using(self):
        """
        The autocommit decorator also works with a using argument.
        """
        autocomitted_create_then_fail = transaction.autocommit(using='default')(
            self.create_a_reporter_then_fail
        )
        self.assertRaises(Exception,
            autocomitted_create_then_fail,
            "Alice", "Smith"
        )
        # Again, the object created before the exception still exists
        self.assertEqual(Reporter.objects.count(), 1)

    @skipUnlessDBFeature('supports_transactions')
    def test_commit_on_success(self):
        """
        With the commit_on_success decorator, the transaction is only committed
        if the function doesn't throw an exception.
        """
        committed_on_success = transaction.commit_on_success(
            self.create_a_reporter_then_fail)
        self.assertRaises(Exception, committed_on_success, "Dirk", "Gently")
        # This time the object never got saved
        self.assertEqual(Reporter.objects.count(), 0)

    @skipUnlessDBFeature('supports_transactions')
    def test_commit_on_success_with_using(self):
        """
        The commit_on_success decorator also works with a using argument.
        """
        using_committed_on_success = transaction.commit_on_success(using='default')(
            self.create_a_reporter_then_fail
        )
        self.assertRaises(Exception,
            using_committed_on_success,
            "Dirk", "Gently"
        )
        # This time the object never got saved
        self.assertEqual(Reporter.objects.count(), 0)

    @skipUnlessDBFeature('supports_transactions')
    def test_commit_on_success_succeed(self):
        """
        If there aren't any exceptions, the data will get saved.
        """
        Reporter.objects.create(first_name="Alice", last_name="Smith")
        remove_comitted_on_success = transaction.commit_on_success(
            self.remove_a_reporter
        )
        remove_comitted_on_success("Alice")
        self.assertEqual(list(Reporter.objects.all()), [])

    @skipUnlessDBFeature('supports_transactions')
    def test_commit_on_success_exit(self):
        @transaction.autocommit()
        def gen_reporter():
            @transaction.commit_on_success
            def create_reporter():
                Reporter.objects.create(first_name="Bobby", last_name="Tables")

            create_reporter()
            # Much more formal
            r = Reporter.objects.get()
            r.first_name = "Robert"
            r.save()

        gen_reporter()
        r = Reporter.objects.get()
        self.assertEqual(r.first_name, "Robert")


    @skipUnlessDBFeature('supports_transactions')
    def test_manually_managed(self):
        """
        You can manually manage transactions if you really want to, but you
        have to remember to commit/rollback.
        """
        manually_managed = transaction.commit_manually(self.manually_managed)
        manually_managed()
        self.assertEqual(Reporter.objects.count(), 1)

    @skipUnlessDBFeature('supports_transactions')
    def test_manually_managed_mistake(self):
        """
        If you forget, you'll get bad errors.
        """
        manually_managed_mistake = transaction.commit_manually(
            self.manually_managed_mistake
        )
        self.assertRaises(transaction.TransactionManagementError,
            manually_managed_mistake)

    @skipUnlessDBFeature('supports_transactions')
    def test_manually_managed_with_using(self):
        """
        The commit_manually function also works with a using argument.
        """
        using_manually_managed_mistake = transaction.commit_manually(using='default')(
            self.manually_managed_mistake
        )
        self.assertRaises(transaction.TransactionManagementError,
            using_manually_managed_mistake
        )


class TransactionRollbackTests(TransactionTestCase):
    def execute_bad_sql(self):
        cursor = connection.cursor()
        cursor.execute("INSERT INTO transactions_reporter (first_name, last_name) VALUES ('Douglas', 'Adams');")

    @skipUnlessDBFeature('requires_rollback_on_dirty_transaction')
    def test_bad_sql(self):
        """
        Regression for #11900: If a function wrapped by commit_on_success
        writes a transaction that can't be committed, that transaction should
        be rolled back. The bug is only visible using the psycopg2 backend,
        though the fix is generally a good idea.
        """
        execute_bad_sql = transaction.commit_on_success(self.execute_bad_sql)
        self.assertRaises(IntegrityError, execute_bad_sql)
        transaction.rollback()

class TransactionContextManagerTests(TransactionTestCase):
    def create_reporter_and_fail(self):
        Reporter.objects.create(first_name="Bob", last_name="Holtzman")
        raise Exception

    @skipUnlessDBFeature('supports_transactions')
    def test_autocommit(self):
        """
        The default behavior is to autocommit after each save() action.
        """
        with self.assertRaises(Exception):
            self.create_reporter_and_fail()
        # The object created before the exception still exists
        self.assertEqual(Reporter.objects.count(), 1)

    @skipUnlessDBFeature('supports_transactions')
    def test_autocommit_context_manager(self):
        """
        The autocommit context manager works exactly the same as the default
        behavior.
        """
        with self.assertRaises(Exception):
            with transaction.autocommit():
                self.create_reporter_and_fail()

        self.assertEqual(Reporter.objects.count(), 1)

    @skipUnlessDBFeature('supports_transactions')
    def test_autocommit_context_manager_with_using(self):
        """
        The autocommit context manager also works with a using argument.
        """
        with self.assertRaises(Exception):
            with transaction.autocommit(using="default"):
                self.create_reporter_and_fail()

        self.assertEqual(Reporter.objects.count(), 1)

    @skipUnlessDBFeature('supports_transactions')
    def test_commit_on_success(self):
        """
        With the commit_on_success context manager, the transaction is only
        committed if the block doesn't throw an exception.
        """
        with self.assertRaises(Exception):
            with transaction.commit_on_success():
                self.create_reporter_and_fail()

        self.assertEqual(Reporter.objects.count(), 0)

    @skipUnlessDBFeature('supports_transactions')
    def test_commit_on_success_with_using(self):
        """
        The commit_on_success context manager also works with a using argument.
        """
        with self.assertRaises(Exception):
            with transaction.commit_on_success(using="default"):
                self.create_reporter_and_fail()

        self.assertEqual(Reporter.objects.count(), 0)

    @skipUnlessDBFeature('supports_transactions')
    def test_commit_on_success_succeed(self):
        """
        If there aren't any exceptions, the data will get saved.
        """
        Reporter.objects.create(first_name="Alice", last_name="Smith")
        with transaction.commit_on_success():
            Reporter.objects.filter(first_name="Alice").delete()

        self.assertQuerysetEqual(Reporter.objects.all(), [])

    @skipUnlessDBFeature('supports_transactions')
    def test_commit_on_success_exit(self):
        with transaction.autocommit():
            with transaction.commit_on_success():
                Reporter.objects.create(first_name="Bobby", last_name="Tables")

            # Much more formal
            r = Reporter.objects.get()
            r.first_name = "Robert"
            r.save()

        r = Reporter.objects.get()
        self.assertEqual(r.first_name, "Robert")

    @skipUnlessDBFeature('supports_transactions')
    def test_manually_managed(self):
        """
        You can manually manage transactions if you really want to, but you
        have to remember to commit/rollback.
        """
        with transaction.commit_manually():
            Reporter.objects.create(first_name="Libby", last_name="Holtzman")
            transaction.commit()
        self.assertEqual(Reporter.objects.count(), 1)

    @skipUnlessDBFeature('supports_transactions')
    def test_manually_managed_mistake(self):
        """
        If you forget, you'll get bad errors.
        """
        with self.assertRaises(transaction.TransactionManagementError):
            with transaction.commit_manually():
                Reporter.objects.create(first_name="Scott", last_name="Browning")

    @skipUnlessDBFeature('supports_transactions')
    def test_manually_managed_with_using(self):
        """
        The commit_manually function also works with a using argument.
        """
        with self.assertRaises(transaction.TransactionManagementError):
            with transaction.commit_manually(using="default"):
                Reporter.objects.create(first_name="Walter", last_name="Cronkite")

    @skipUnlessDBFeature('requires_rollback_on_dirty_transaction')
    def test_bad_sql(self):
        """
        Regression for #11900: If a block wrapped by commit_on_success
        writes a transaction that can't be committed, that transaction should
        be rolled back. The bug is only visible using the psycopg2 backend,
        though the fix is generally a good idea.
        """
        with self.assertRaises(IntegrityError):
            with transaction.commit_on_success():
                cursor = connection.cursor()
                cursor.execute("INSERT INTO transactions_reporter (first_name, last_name) VALUES ('Douglas', 'Adams');")
        transaction.rollback()
