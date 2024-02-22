from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.backends.ddl_references import IndexColumns
from django.db.backends.postgresql.psycopg_any import sql
from django.db.backends.utils import strip_quotes


class DatabaseSchemaEditor(BaseDatabaseSchemaEditor):
    # Setting all constraints to IMMEDIATE to allow changing data in the same
    # transaction.
    sql_update_with_default = (
        "UPDATE %(table)s SET %(column)s = %(default)s WHERE %(column)s IS NULL"
        "; SET CONSTRAINTS ALL IMMEDIATE"
    )
    sql_alter_sequence_type = "ALTER SEQUENCE IF EXISTS %(sequence)s AS %(type)s"
    sql_delete_sequence = "DROP SEQUENCE IF EXISTS %(sequence)s CASCADE"

    sql_create_index = (
        "CREATE INDEX %(name)s ON %(table)s%(using)s "
        "(%(columns)s)%(include)s%(extra)s%(condition)s"
    )
    sql_create_index_concurrently = (
        "CREATE INDEX CONCURRENTLY %(name)s ON %(table)s%(using)s "
        "(%(columns)s)%(include)s%(extra)s%(condition)s"
    )
    sql_delete_index = "DROP INDEX IF EXISTS %(name)s"
    sql_delete_index_concurrently = "DROP INDEX CONCURRENTLY IF EXISTS %(name)s"

    # Setting the constraint to IMMEDIATE to allow changing data in the same
    # transaction.
    sql_create_column_inline_fk = (
        "CONSTRAINT %(name)s REFERENCES %(to_table)s(%(to_column)s)%(deferrable)s"
        "; SET CONSTRAINTS %(namespace)s%(name)s IMMEDIATE"
    )
    # Setting the constraint to IMMEDIATE runs any deferred checks to allow
    # dropping it in the same transaction.
    sql_delete_fk = (
        "SET CONSTRAINTS %(name)s IMMEDIATE; "
        "ALTER TABLE %(table)s DROP CONSTRAINT %(name)s"
    )
    sql_delete_procedure = "DROP FUNCTION %(procedure)s(%(param_types)s)"

    def execute(self, sql, params=()):
        # Merge the query client-side, as PostgreSQL won't do it server-side.
        if params is None:
            return super().execute(sql, params)
        sql = self.connection.ops.compose_sql(str(sql), params)
        # Don't let the superclass touch anything.
        return super().execute(sql, None)

    sql_add_identity = (
        "ALTER TABLE %(table)s ALTER COLUMN %(column)s ADD "
        "GENERATED BY DEFAULT AS IDENTITY"
    )
    sql_drop_indentity = (
        "ALTER TABLE %(table)s ALTER COLUMN %(column)s DROP IDENTITY IF EXISTS"
    )

    def quote_value(self, value):
        return sql.quote(value, self.connection.connection)

    def _field_indexes_sql(self, model, field):
        output = super()._field_indexes_sql(model, field)
        like_index_statement = self._create_like_index_sql(model, field)
        if like_index_statement is not None:
            output.append(like_index_statement)
        return output

    def _field_data_type(self, field):
        if field.is_relation:
            return field.rel_db_type(self.connection)
        return self.connection.data_types.get(
            field.get_internal_type(),
            field.db_type(self.connection),
        )

    def _field_base_data_types(self, field):
        # Yield base data types for array fields.
        if field.base_field.get_internal_type() == "ArrayField":
            yield from self._field_base_data_types(field.base_field)
        else:
            yield self._field_data_type(field.base_field)

    def _create_like_index_sql(self, model, field):
        """
        Return the statement to create an index with varchar operator pattern
        when the column type is 'varchar' or 'text', otherwise return None.
        """
        db_type = field.db_type(connection=self.connection)
        if db_type is not None and (field.db_index or field.unique):
            # Fields with database column types of `varchar` and `text` need
            # a second index that specifies their operator class, which is
            # needed when performing correct LIKE queries outside the
            # C locale. See #12234.
            #
            # The same doesn't apply to array fields such as varchar[size]
            # and text[size], so skip them.
            if "[" in db_type:
                return None
            # Non-deterministic collations on Postgresql don't support indexes
            # for operator classes varchar_pattern_ops/text_pattern_ops.
            collation_name = getattr(field, "db_collation", None)
            if not collation_name and field.is_relation:
                collation_name = getattr(field.target_field, "db_collation", None)
            if collation_name and not self._is_collation_deterministic(collation_name):
                return None
            if db_type.startswith("varchar"):
                return self._create_index_sql(
                    model,
                    fields=[field],
                    suffix="_like",
                    opclasses=["varchar_pattern_ops"],
                )
            elif db_type.startswith("text"):
                return self._create_index_sql(
                    model,
                    fields=[field],
                    suffix="_like",
                    opclasses=["text_pattern_ops"],
                )
        return None

    def _using_sql(self, new_field, old_field):
        using_sql = " USING %(column)s::%(type)s"
        new_internal_type = new_field.get_internal_type()
        old_internal_type = old_field.get_internal_type()
        if new_internal_type == "ArrayField" and new_internal_type == old_internal_type:
            # Compare base data types for array fields.
            if list(self._field_base_data_types(old_field)) != list(
                self._field_base_data_types(new_field)
            ):
                return using_sql
        elif self._field_data_type(old_field) != self._field_data_type(new_field):
            return using_sql
        return ""

    def _get_sequence_name(self, table, column):
        with self.connection.cursor() as cursor:
            for sequence in self.connection.introspection.get_sequences(cursor, table):
                if sequence["column"] == column:
                    return sequence["name"]
        return None

    def _alter_column_type_sql(
        self, model, old_field, new_field, new_type, old_collation, new_collation
    ):
        # Drop indexes on varchar/text/citext columns that are changing to a
        # different type.
        old_db_params = old_field.db_parameters(connection=self.connection)
        old_type = old_db_params["type"]
        if (old_field.db_index or old_field.unique) and (
            (old_type.startswith("varchar") and not new_type.startswith("varchar"))
            or (old_type.startswith("text") and not new_type.startswith("text"))
            or (old_type.startswith("citext") and not new_type.startswith("citext"))
        ):
            index_name = self._create_index_name(
                model._meta.db_table, [old_field.column], suffix="_like"
            )
            self.execute(self._delete_index_sql(model, index_name))

        self.sql_alter_column_type = (
            "ALTER COLUMN %(column)s TYPE %(type)s%(collation)s"
        )
        # Cast when data type changed.
        if using_sql := self._using_sql(new_field, old_field):
            self.sql_alter_column_type += using_sql
        new_internal_type = new_field.get_internal_type()
        old_internal_type = old_field.get_internal_type()
        # Make ALTER TYPE with IDENTITY make sense.
        table = strip_quotes(model._meta.db_table)
        auto_field_types = {
            "AutoField",
            "BigAutoField",
            "SmallAutoField",
        }
        old_is_auto = old_internal_type in auto_field_types
        new_is_auto = new_internal_type in auto_field_types
        if new_is_auto and not old_is_auto:
            column = strip_quotes(new_field.column)
            return (
                (
                    self.sql_alter_column_type
                    % {
                        "column": self.quote_name(column),
                        "type": new_type,
                        "collation": "",
                    },
                    [],
                ),
                [
                    (
                        self.sql_add_identity
                        % {
                            "table": self.quote_name(table),
                            "column": self.quote_name(column),
                        },
                        [],
                    ),
                ],
            )
        elif old_is_auto and not new_is_auto:
            # Drop IDENTITY if exists (pre-Django 4.1 serial columns don't have
            # it).
            self.execute(
                self.sql_drop_indentity
                % {
                    "table": self.quote_name(table),
                    "column": self.quote_name(strip_quotes(new_field.column)),
                }
            )
            column = strip_quotes(new_field.column)
            fragment, _ = super()._alter_column_type_sql(
                model, old_field, new_field, new_type, old_collation, new_collation
            )
            # Drop the sequence if exists (Django 4.1+ identity columns don't
            # have it).
            other_actions = []
            if sequence_name := self._get_sequence_name(table, column):
                other_actions = [
                    (
                        self.sql_delete_sequence
                        % {
                            "sequence": self.quote_name(sequence_name),
                        },
                        [],
                    )
                ]
            return fragment, other_actions
        elif new_is_auto and old_is_auto and old_internal_type != new_internal_type:
            fragment, _ = super()._alter_column_type_sql(
                model, old_field, new_field, new_type, old_collation, new_collation
            )
            column = strip_quotes(new_field.column)
            db_types = {
                "AutoField": "integer",
                "BigAutoField": "bigint",
                "SmallAutoField": "smallint",
            }
            # Alter the sequence type if exists (Django 4.1+ identity columns
            # don't have it).
            other_actions = []
            if sequence_name := self._get_sequence_name(table, column):
                other_actions = [
                    (
                        self.sql_alter_sequence_type
                        % {
                            "sequence": self.quote_name(sequence_name),
                            "type": db_types[new_internal_type],
                        },
                        [],
                    ),
                ]
            return fragment, other_actions
        else:
            return super()._alter_column_type_sql(
                model, old_field, new_field, new_type, old_collation, new_collation
            )

    def _alter_column_collation_sql(
        self, model, new_field, new_type, new_collation, old_field
    ):
        sql = self.sql_alter_column_collate
        # Cast when data type changed.
        if using_sql := self._using_sql(new_field, old_field):
            sql += using_sql
        return (
            sql
            % {
                "column": self.quote_name(new_field.column),
                "type": new_type,
                "collation": " " + self._collate_sql(new_collation)
                if new_collation
                else "",
            },
            [],
        )

    def _alter_field(
        self,
        model,
        old_field,
        new_field,
        old_type,
        new_type,
        old_db_params,
        new_db_params,
        strict=False,
    ):
        super()._alter_field(
            model,
            old_field,
            new_field,
            old_type,
            new_type,
            old_db_params,
            new_db_params,
            strict,
        )
        # Added an index? Create any PostgreSQL-specific indexes.
        if (not (old_field.db_index or old_field.unique) and new_field.db_index) or (
            not old_field.unique and new_field.unique
        ):
            like_index_statement = self._create_like_index_sql(model, new_field)
            if like_index_statement is not None:
                self.execute(like_index_statement)

        # Removed an index? Drop any PostgreSQL-specific indexes.
        if old_field.unique and not (new_field.db_index or new_field.unique):
            index_to_remove = self._create_index_name(
                model._meta.db_table, [old_field.column], suffix="_like"
            )
            self.execute(self._delete_index_sql(model, index_to_remove))

    def _index_columns(self, table, columns, col_suffixes, opclasses):
        if opclasses:
            return IndexColumns(
                table,
                columns,
                self.quote_name,
                col_suffixes=col_suffixes,
                opclasses=opclasses,
            )
        return super()._index_columns(table, columns, col_suffixes, opclasses)

    def add_index(self, model, index, concurrently=False):
        self.execute(
            index.create_sql(model, self, concurrently=concurrently), params=None
        )

    def remove_index(self, model, index, concurrently=False):
        self.execute(index.remove_sql(model, self, concurrently=concurrently))

    def _delete_index_sql(self, model, name, sql=None, concurrently=False):
        sql = (
            self.sql_delete_index_concurrently
            if concurrently
            else self.sql_delete_index
        )
        return super()._delete_index_sql(model, name, sql)

    def _create_index_sql(
        self,
        model,
        *,
        fields=None,
        name=None,
        suffix="",
        using="",
        db_tablespace=None,
        col_suffixes=(),
        sql=None,
        opclasses=(),
        condition=None,
        concurrently=False,
        include=None,
        expressions=None,
    ):
        sql = sql or (
            self.sql_create_index
            if not concurrently
            else self.sql_create_index_concurrently
        )
        return super()._create_index_sql(
            model,
            fields=fields,
            name=name,
            suffix=suffix,
            using=using,
            db_tablespace=db_tablespace,
            col_suffixes=col_suffixes,
            sql=sql,
            opclasses=opclasses,
            condition=condition,
            include=include,
            expressions=expressions,
        )

    def _is_collation_deterministic(self, collation_name):
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT collisdeterministic
                FROM pg_collation
                WHERE collname = %s
                """,
                [collation_name],
            )
            row = cursor.fetchone()
            return row[0] if row else None
