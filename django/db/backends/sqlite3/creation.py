import os
import shutil
import sys
import sqlite3
from pathlib import Path

from django.db.backends.base.creation import BaseDatabaseCreation


class DatabaseCreation(BaseDatabaseCreation):
    DEFAULT_TEST_DB_FILENAME = 'test.db'

    @staticmethod
    def is_in_memory_db(database_name):
        return not isinstance(database_name, Path) and (
            database_name == ':memory:' or 'mode=memory' in database_name
        )

    def _get_test_db_name(self):
        test_database_name = self.connection.settings_dict['TEST']['NAME'] or self.DEFAULT_TEST_DB_FILENAME
        # Force to use file based database for parallel testing when default settings is in-memory DB
        if self.is_in_memory_db(test_database_name):
            return DEFAULT_TEST_DB_FILENAME
        return test_database_name

    def _get_test_db_clone_name(self, suffix):
        test_database_name = self._get_test_db_name()
        root, ext = os.path.splitext(test_database_name)
        return '{}_{}.{}'.format(root, suffix, ext)

    def _create_test_db(self, verbosity, autoclobber, keepdb=False):
        test_database_name = self._get_test_db_name()

        if keepdb:
            return test_database_name
        if not self.is_in_memory_db(test_database_name):
            # Erase the old test database
            if verbosity >= 1:
                self.log('Destroying old test database for alias %s...' % (
                    self._get_database_display_str(verbosity, test_database_name),
                ))
            if os.access(test_database_name, os.F_OK):
                if not autoclobber:
                    confirm = input(
                        "Type 'yes' if you would like to try deleting the test "
                        "database '%s', or 'no' to cancel: " % test_database_name
                    )
                if autoclobber or confirm == 'yes':
                    try:
                        os.remove(test_database_name)
                    except Exception as e:
                        self.log('Got an error deleting the old test database: %s' % e)
                        sys.exit(2)
                else:
                    self.log('Tests cancelled.')
                    sys.exit(1)
        return test_database_name

    def get_test_db_clone_settings(self, suffix):
        orig_settings_dict = self.connection.settings_dict
        return {**orig_settings_dict, 'NAME': self._get_test_db_clone_name(suffix)}

    def _clone_test_db(self, suffix, verbosity, keepdb=False):
        source_database_name = self.connection.settings_dict['NAME']
        target_database_name = self.get_test_db_clone_settings(suffix)['NAME']
        if not self.is_in_memory_db(source_database_name):
            # Erase the old test database
            if os.access(target_database_name, os.F_OK):
                if keepdb:
                    return
                if verbosity >= 1:
                    self.log('Destroying old test database for alias %s...' % (
                        self._get_database_display_str(verbosity, target_database_name),
                    ))
                try:
                    os.remove(target_database_name)
                except Exception as e:
                    self.log('Got an error deleting the old test database: %s' % e)
                    sys.exit(2)
            try:
                shutil.copy(source_database_name, target_database_name)
            except Exception as e:
                self.log('Got an error cloning the test database: %s' % e)
                sys.exit(2)

    def _destroy_test_db(self, test_database_name, verbosity):
        if test_database_name and not self.is_in_memory_db(test_database_name):
            # Remove the SQLite database file
            os.remove(test_database_name)

    def test_db_signature(self):
        """
        Return a tuple that uniquely identifies a test database.

        This takes into account the special cases of ":memory:" and "" for
        SQLite since the databases will be distinct despite having the same
        TEST NAME. See https://www.sqlite.org/inmemorydb.html
        """
        test_database_name = self._get_test_db_name()
        sig = [self.connection.settings_dict['NAME']]
        if self.is_in_memory_db(test_database_name):
            sig.append(self.connection.alias)
        else:
            sig.append(test_database_name)
        return tuple(sig)
