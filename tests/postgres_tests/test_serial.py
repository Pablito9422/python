from django.core.checks import Error
from django.core.management.color import no_style
from django.db import connection, models
from django.test.utils import CaptureQueriesContext, isolate_apps, tag

from . import PostgreSQLTestCase
from .fields import BigSerialField, SerialField, SmallSerialField
from .models import SerialModel


def get_sequence_reset_sql():
    return connection.ops.sequence_reset_sql(no_style(), [SerialModel])


def reset_sequences():
    with connection.cursor() as cursor:
        for statement in get_sequence_reset_sql():
            cursor.execute(statement)


@isolate_apps("postgres_tests")
@tag("serial")
class SerialFieldModelTests(PostgreSQLTestCase):
    def test_null_check(self):
        class Model(models.Model):
            serial = SerialField(null=True)

        field = Model._meta.get_field("serial")
        errors = field.check()
        expected = [
            Error(
                "SerialFields do not accept null values.",
                obj=field,
                id="fields.E910",
            ),
        ]
        self.assertEqual(errors, expected)

    def test_default_check(self):
        class Model(models.Model):
            serial = SerialField(default=1)

        field = Model._meta.get_field("serial")
        errors = field.check()
        expected = [
            Error(
                "SerialFields do not accept default values.",
                obj=field,
                id="fields.E911",
            )
        ]
        self.assertEqual(errors, expected)

    def test_db_types(self):
        class Model(models.Model):
            small_serial = SmallSerialField()
            serial = SerialField()
            big_serial = BigSerialField()

        small_serial = Model._meta.get_field("small_serial")
        serial = Model._meta.get_field("serial")
        big_serial = Model._meta.get_field("big_serial")

        self.assertEqual(small_serial.db_type(connection), "smallserial")
        self.assertEqual(serial.db_type(connection), "serial")
        self.assertEqual(big_serial.db_type(connection), "bigserial")


@tag("serial")
class SerialModelTests(PostgreSQLTestCase):
    def assertInsertSql(self, sql):
        table = SerialModel._meta.db_table
        self.assertEqual(
            sql,
            f'INSERT INTO "{table}" ("small_serial", "serial", "big_serial") '
            f"VALUES (DEFAULT, DEFAULT, DEFAULT) "
            f'RETURNING "{table}"."id", "{table}"."small_serial", '
            f'"{table}"."serial", "{table}"."big_serial"',
        )

    def test_create(self):
        with CaptureQueriesContext(connection) as context_1:
            obj_1 = SerialModel.objects.create()

        self.assertGreater(obj_1.small_serial, 0)
        self.assertGreater(obj_1.serial, 0)
        self.assertGreater(obj_1.big_serial, 0)
        self.assertEqual(len(context_1.captured_queries), 1)
        self.assertInsertSql(context_1.captured_queries[0]["sql"])

        with CaptureQueriesContext(connection) as context_2:
            obj_2 = SerialModel.objects.create()

        self.assertEqual(obj_2.small_serial, obj_1.small_serial + 1)
        self.assertEqual(obj_2.serial, obj_1.serial + 1)
        self.assertEqual(obj_2.big_serial, obj_1.big_serial + 1)
        self.assertEqual(len(context_2.captured_queries), 1)
        self.assertInsertSql(context_2.captured_queries[0]["sql"])

        with CaptureQueriesContext(connection) as context_3:
            obj_3 = SerialModel.objects.create(
                small_serial=None, serial=None, big_serial=None
            )

        self.assertEqual(obj_3.small_serial, obj_2.small_serial + 1)
        self.assertEqual(obj_3.serial, obj_2.serial + 1)
        self.assertEqual(obj_3.big_serial, obj_2.big_serial + 1)
        self.assertEqual(len(context_3.captured_queries), 1)
        self.assertInsertSql(context_3.captured_queries[0]["sql"])

    def test_get_sequences(self):
        table = SerialModel._meta.db_table
        with connection.cursor() as cursor:
            sequences = connection.introspection.get_sequences(cursor, table)

        self.assertEqual(len(sequences), 4)
        self.assertEqual(sequences[0]["column"], "id")
        self.assertEqual(sequences[0]["name"], f"{table}_id_seq")
        self.assertEqual(sequences[0]["table"], table)
        self.assertEqual(sequences[1]["column"], "small_serial")
        self.assertEqual(sequences[1]["name"], f"{table}_small_serial_seq")
        self.assertEqual(sequences[1]["table"], table)
        self.assertEqual(sequences[2]["column"], "serial")
        self.assertEqual(sequences[2]["name"], f"{table}_serial_seq")
        self.assertEqual(sequences[2]["table"], table)
        self.assertEqual(sequences[3]["column"], "big_serial")
        self.assertEqual(sequences[3]["name"], f"{table}_big_serial_seq")
        self.assertEqual(sequences[3]["table"], table)

    def test_sequence_reset_by_name_sql(self):
        with connection.cursor() as cursor:
            sequences = connection.introspection.get_sequences(
                cursor, SerialModel._meta.db_table
            )
            statements = connection.ops.sequence_reset_by_name_sql(
                no_style(), sequences
            )

            for statement in statements:
                cursor.execute(statement)

        self.assertEqual(len(statements), 4)
        obj_1 = SerialModel.objects.create()
        self.assertEqual(obj_1.small_serial, 1)
        self.assertEqual(obj_1.serial, 1)
        self.assertEqual(obj_1.big_serial, 1)
        obj_2 = SerialModel.objects.create()
        self.assertEqual(obj_2.small_serial, 2)
        self.assertEqual(obj_2.serial, 2)
        self.assertEqual(obj_2.big_serial, 2)
        obj_3 = SerialModel.objects.create(small_serial=2, serial=3, big_serial=4)
        self.assertEqual(obj_3.small_serial, 2)
        self.assertEqual(obj_3.serial, 3)
        self.assertEqual(obj_3.big_serial, 4)
        obj_4 = SerialModel.objects.create()
        self.assertEqual(obj_4.small_serial, 3)
        self.assertEqual(obj_4.serial, 3)
        self.assertEqual(obj_4.big_serial, 3)

    def test_sequence_reset_sql_statements(self):
        def get_statement(field):
            db_table = SerialModel._meta.db_table
            return (
                f"SELECT setval("
                f"pg_get_serial_sequence('\"{db_table}\"','{field}'), "
                f'coalesce(max("{field}"), 1), '
                f'max("{field}") IS NOT null'
                f') FROM "{db_table}";'
            )

        statements = get_sequence_reset_sql()
        self.assertEqual(len(statements), 4)
        self.assertEqual(statements[0], get_statement("id"))
        self.assertEqual(statements[1], get_statement("small_serial"))
        self.assertEqual(statements[2], get_statement("serial"))
        self.assertEqual(statements[3], get_statement("big_serial"))

    def test_reset_sequences_if_record_exists(self):
        SerialModel.objects.create(small_serial=1, serial=2, big_serial=3)
        reset_sequences()
        obj = SerialModel.objects.create()
        self.assertEqual(obj.small_serial, 2)
        self.assertEqual(obj.serial, 3)
        self.assertEqual(obj.big_serial, 4)

    def test_reset_sequences_if_record_doesnt_exist(self):
        reset_sequences()
        obj = SerialModel.objects.create()
        self.assertEqual(obj.small_serial, 1)
        self.assertEqual(obj.serial, 1)
        self.assertEqual(obj.big_serial, 1)

    def test_bulk_create(self):
        reset_sequences()
        objs = [
            SerialModel(),
            SerialModel(small_serial=1, serial=1, big_serial=1),
            SerialModel(serial=5),
            SerialModel(),
        ]

        obj_1, obj_2, obj_3, obj_4 = SerialModel.objects.bulk_create(objs)
        self.assertEqual(
            (obj_1.small_serial, obj_1.serial, obj_1.big_serial), (1, 1, 1)
        )
        self.assertEqual(
            (obj_2.small_serial, obj_2.serial, obj_2.big_serial), (1, 1, 1)
        )
        self.assertEqual(
            (obj_3.small_serial, obj_3.serial, obj_3.big_serial), (2, 5, 2)
        )
        self.assertEqual(
            (obj_4.small_serial, obj_4.serial, obj_4.big_serial), (3, 2, 3)
        )
