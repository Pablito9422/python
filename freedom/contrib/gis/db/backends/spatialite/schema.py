from freedom.db.backends.sqlite3.schema import DatabaseSchemaEditor


class SpatialiteSchemaEditor(DatabaseSchemaEditor):
    sql_add_geometry_column = "SELECT AddGeometryColumn(%(table)s, %(column)s, %(srid)s, %(geom_type)s, %(dim)s, %(null)s)"
    sql_add_spatial_index = "SELECT CreateSpatialIndex(%(table)s, %(column)s)"
    sql_drop_spatial_index = "DROP TABLE idx_%(table)s_%(column)s"
    sql_remove_geometry_metadata = "SELECT DiscardGeometryColumn(%(table)s, %(column)s)"
    sql_update_geometry_columns = "UPDATE geometry_columns SET f_table_name = %(new_table)s WHERE f_table_name = %(old_table)s"

    def __init__(self, *args, **kwargs):
        super(SpatialiteSchemaEditor, self).__init__(*args, **kwargs)
        self.geometry_sql = []

    def geo_quote_name(self, name):
        return self.connection.ops.geo_quote_name(name)

    def column_sql(self, model, field, include_default=False):
        from freedom.contrib.gis.db.models.fields import GeometryField
        if not isinstance(field, GeometryField):
            return super(SpatialiteSchemaEditor, self).column_sql(model, field, include_default)

        # Geometry columns are created by the `AddGeometryColumn` function
        self.geometry_sql.append(
            self.sql_add_geometry_column % {
                "table": self.geo_quote_name(model._meta.db_table),
                "column": self.geo_quote_name(field.column),
                "srid": field.srid,
                "geom_type": self.geo_quote_name(field.geom_type),
                "dim": field.dim,
                "null": int(not field.null),
            }
        )

        if field.spatial_index:
            self.geometry_sql.append(
                self.sql_add_spatial_index % {
                    "table": self.quote_name(model._meta.db_table),
                    "column": self.quote_name(field.column),
                }
            )
        return None, None

    def remove_geometry_metadata(self, model, field):
        self.execute(
            self.sql_remove_geometry_metadata % {
                "table": self.quote_name(model._meta.db_table),
                "column": self.quote_name(field.column),
            }
        )
        self.execute(
            self.sql_drop_spatial_index % {
                "table": model._meta.db_table,
                "column": field.column,
            }
        )

    def create_model(self, model):
        super(SpatialiteSchemaEditor, self).create_model(model)
        # Create geometry columns
        for sql in self.geometry_sql:
            self.execute(sql)
        self.geometry_sql = []

    def delete_model(self, model):
        from freedom.contrib.gis.db.models.fields import GeometryField
        # Drop spatial metadata (dropping the table does not automatically remove them)
        for field in model._meta.local_fields:
            if isinstance(field, GeometryField):
                self.remove_geometry_metadata(model, field)
        super(SpatialiteSchemaEditor, self).delete_model(model)

    def add_field(self, model, field):
        from freedom.contrib.gis.db.models.fields import GeometryField
        if isinstance(field, GeometryField):
            # Populate self.geometry_sql
            self.column_sql(model, field)
            for sql in self.geometry_sql:
                self.execute(sql)
            self.geometry_sql = []
        else:
            super(SpatialiteSchemaEditor, self).add_field(model, field)

    def remove_field(self, model, field):
        from freedom.contrib.gis.db.models.fields import GeometryField
        if isinstance(field, GeometryField):
            self.remove_geometry_metadata(model, field)
        super(SpatialiteSchemaEditor, self).remove_field(model, field)

    def alter_db_table(self, model, old_db_table, new_db_table):
        super(SpatialiteSchemaEditor, self).alter_db_table(model, old_db_table, new_db_table)
        self.execute(
            self.sql_update_geometry_columns % {
                "old_table": self.quote_name(old_db_table),
                "new_table": self.quote_name(new_db_table),
            }
        )
