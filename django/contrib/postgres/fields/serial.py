from django.core import checks
from django.db import models
from django.db.models import NOT_PROVIDED
from django.db.models.expressions import DatabaseDefault
from django.utils.translation import gettext_lazy as _

__all__ = ("BigSerialField", "SmallSerialField", "SerialField")


class SerialFieldMixin:
    db_returning = True

    def __init__(self, *args, **kwargs):
        kwargs["blank"] = True
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop("blank")
        return name, path, args, kwargs

    def check(self, **kwargs):
        return [
            *super().check(**kwargs),
            *self._check_not_null(),
            *self._check_default(),
        ]

    def _check_not_null(self):
        if self.null:
            return [
                checks.Error(
                    "SerialFields do not accept null values.",
                    obj=self,
                    id="fields.E910",
                ),
            ]
        else:
            return []

    def _check_default(self):
        if self.default is NOT_PROVIDED:
            return []
        return [
            checks.Error(
                "SerialFields do not accept default values.",
                obj=self,
                id="fields.E911",
            ),
        ]

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            value = DatabaseDefault()
        return value


class BigSerialField(SerialFieldMixin, models.BigIntegerField):
    description = _("Big serial")

    def get_internal_type(self):
        return "BigSerialField"

    def db_type(self, connection):
        return "bigserial"


class SmallSerialField(SerialFieldMixin, models.SmallIntegerField):
    description = _("Small serial")

    def get_internal_type(self):
        return "SmallSerialField"

    def db_type(self, connection):
        return "smallserial"


class SerialField(SerialFieldMixin, models.IntegerField):
    description = _("Serial")

    def get_internal_type(self):
        return "SerialField"

    def db_type(self, connection):
        return "serial"
