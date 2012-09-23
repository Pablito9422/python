"""
Various data structures used in query construction.

Factored out from django.db.models.query to avoid making the main module very
large and/or so that they can be used by other modules without getting into
circular import difficulties.
"""
from __future__ import unicode_literals

from django.db.backends import util
from django.db.models.constants import LOOKUP_SEP
from django.utils import six
from django.utils import tree


class InvalidQuery(Exception):
    """
    The query passed to raw isn't a safe query to use with raw.
    """
    pass


class QueryWrapper(object):
    """
    A type that indicates the contents are an SQL fragment and the associate
    parameters. Can be used to pass opaque data to a where-clause, for example.
    """
    def __init__(self, sql, params):
        self.data = sql, params

    def as_sql(self, qn=None, connection=None):
        return self.data


class Q(tree.Node):
    """
    Encapsulates filters as objects that can then be combined logically (using
    & and |).
    """
    # Connection types
    AND = 'AND'
    OR = 'OR'
    default = AND

    def __init__(self, *args, **kwargs):
        super(Q, self).__init__(children=list(args) + list(six.iteritems(kwargs)))
        self._compiled_matcher = None

    def _combine(self, other, conn):
        if not isinstance(other, Q):
            raise TypeError(other)
        obj = type(self)()
        obj.add(self, conn)
        obj.add(other, conn)
        return obj

    def __or__(self, other):
        return self._combine(other, self.OR)

    def __and__(self, other):
        return self._combine(other, self.AND)

    def __invert__(self):
        obj = type(self)()
        obj.add(self, self.AND)
        obj.negate()
        return obj

    def _compile_matcher(self, manager):
        """
        Create a mirrored version of self, but where leaves are
        LookupExpressions that understand a call to .matches().
        """
        def descend(parent, children):
            for child in children:
                if isinstance(child, type(self)):
                    # a Q subtree
                    branch_root = LookupExpression(connector=child.connector,
                            manager=manager, negated=child.negated)

                    parent.children.append(branch_root)
                    descend(branch_root, child.children)
                else:
                    # assuming we are in a properly formed Q, could only be
                    # a tuple
                    child_le = LookupExpression(expr=child, manager=manager)
                    parent.children.append(child_le)

        root = LookupExpression(connector=self.connector, manager=manager)
        descend(root, self.children)
        root.negated = self.negated

        self._compiled_matcher = root

    def matches(self, instance, manager=None):
        """
        Returns true if the model instance matches this predicate.
        """
        if manager is None:
            manager = instance._default_manager

        if not self._compiled_matcher:
            # we are evaluating the first model, or are uncompiled
            self._compile_matcher(manager)
        if self._compiled_matcher.manager != manager:
            # the pre-compiled matcher was compiled for a different manager
            self._compile_matcher(manager)
        return_val = self._compiled_matcher.matches(instance)
        if self.negated:
            # It is extremely unlikely (impossible?) to end up with a root
            # Q object that is negated, given the implementation of __invert__
            # we should be able to return _compiled_matcher.matches() directly
            # but in case we encounter an unforseen edgecase, we check again
            return not return_val
        else:
            return return_val

    def match_compile(self, manager):
        """
        Return the precompiled evaluator tree.
        """
        self._compile_matcher(manager)
        return self._compiled_matcher


class DeferredAttribute(object):
    """
    A wrapper for a deferred-loading field. When the value is read from this
    object the first time, the query is executed.
    """
    def __init__(self, field_name, model):
        self.field_name = field_name

    def __get__(self, instance, owner):
        """
        Retrieves and caches the value from the datastore on the first lookup.
        Returns the cached value.
        """
        from django.db.models.fields import FieldDoesNotExist
        non_deferred_model = instance._meta.proxy_for_model
        opts = non_deferred_model._meta

        assert instance is not None
        data = instance.__dict__
        if data.get(self.field_name, self) is self:
            # self.field_name is the attname of the field, but only() takes the
            # actual name, so we need to translate it here.
            try:
                f = opts.get_field_by_name(self.field_name)[0]
            except FieldDoesNotExist:
                f = [f for f in opts.fields
                     if f.attname == self.field_name][0]
            name = f.name
            # Lets see if the field is part of the parent chain. If so we
            # might be able to reuse the already loaded value. Refs #18343.
            val = self._check_parent_chain(instance, name)
            if val is None:
                # We use only() instead of values() here because we want the
                # various data coersion methods (to_python(), etc.) to be
                # called here.
                val = getattr(
                    non_deferred_model._base_manager.only(name).using(
                        instance._state.db).get(pk=instance.pk),
                    self.field_name
                )
            data[self.field_name] = val
        return data[self.field_name]

    def __set__(self, instance, value):
        """
        Deferred loading attributes can be set normally (which means there will
        never be a database lookup involved.
        """
        instance.__dict__[self.field_name] = value

    def _check_parent_chain(self, instance, name):
        """
        Check if the field value can be fetched from a parent field already
        loaded in the instance. This can be done if the to-be fetched
        field is a primary key field.
        """
        opts = instance._meta
        f = opts.get_field_by_name(name)[0]
        link_field = opts.get_ancestor_link(f.model)
        if f.primary_key and f != link_field:
            return getattr(instance, link_field.attname)
        return None


class LookupExpression(tree.Node):
    """
    A thin wrapper around a filter expression tuple of (lookup-type, value) to
    provide a matches method.
    """
    # Connection types
    AND = 'AND'
    OR = 'OR'
    default = AND

    def __init__(self, expr=None, manager=None, *args, **kwargs):
        super(LookupExpression, self).__init__(**kwargs)
        self.manager = manager
        if expr:
            # if we get a expr we need to be able to evaluate,
            # otherwise we are just a root node and a simple container
            self.lookup, self.value = expr
            # attr_route is a sequence of fields following relationships
            # ending in the field to perform the match on
            self.attr_route = []
            self.lookup_type = 'exact'  # Default lookup type
            self.query = manager.get_query_set().query
            self.traverse_lookup(manager.model)
            if (len(self.attr_route) == 0 or
                    self.lookup_type not in self.query.query_terms):
                # we have no valid field or no valid lookup type
                raise ValueError("invalid lookup: {}".format(self.lookup))
            self.lookup_function = self.query.match_functions[self.lookup_type]

    def traverse_lookup(self, model):
        """
        Validates a lookup string as a traversable sequence of attributes,
        storing them for for future use
        """
        # avoiding a circular import
        from django.db.models.fields import FieldDoesNotExist

        # This function roughly re-implements the behavior of
        # db.models.sql.query.add_filter

        parts = self.lookup.split(LOOKUP_SEP)
        num_parts = len(parts)

        if (len(parts) > 1):
            # Traverse the lookup query to distinguish related fields from
            # lookup types.
            lookup_model = model
            for counter, field_name in enumerate(parts):
                try:
                    lookup_field = lookup_model._meta.get_field(field_name)
                    self.attr_route.append(field_name)
                except FieldDoesNotExist:
                    # Not a field. Bail out.
                    self.lookup_type = parts.pop()
                    return
                # Unless we're at the end of the list of lookups, let's attempt
                # to continue traversing relations.
                if (counter + 1) < num_parts:
                    try:
                        lookup_model = lookup_field.rel.to
                    except AttributeError:
                        # Not a related field. Bail out.
                        self.lookup_type = parts.pop()
                        return
        else:
            # presumably we have a simple <field>=x with no lookup term
            # so we just use our default of exact
            self.attr_route.append(parts[0])
            return

    def get_instance_value(self, instance):
        current = instance
        for attr in self.attr_route:
            current = getattr(current, attr)
        return current

    def matches(self, instance):
        """
        Evaluates an instance against the lookup we were created with.
        Return true if the instance matches the condiiton.
        """
        if not isinstance(instance, self.manager.model):
            raise ValueError("invalid manager given for {}".format(instance))

        evaluators = {"AND": all, "OR": any}
        evaluator = evaluators[self.connector]
        return_val = None
        if self.children:
            return_val = (evaluator(c.matches(instance) for c in self.children))
        else:
            try:
                instance_value = self.get_instance_value(instance)
                return_val = self.lookup_function(instance, instance_value,
                        self.value)
            except AttributeError:
                # this is raised when we were not able to traverse the full
                # attribute route. In nearly all cases this means the match
                # failed as it specified a longer relationship chain then
                # exists for this instance.
                if (hasattr(self.lookup_function, 'none_is_true')
                    and self.lookup_function.none_is_true):
                    return_val = True
                else:
                    return_val = False
        if self.negated:
            return not return_val
        else:
            return return_val


def select_related_descend(field, restricted, requested, load_fields,
        reverse=False):
    """
    Returns True if this field should be used to descend deeper for
    select_related() purposes. Used by both the query construction code
    (sql.query.fill_related_selections()) and the model instance creation code
    (query.get_klass_info()).

    Arguments:
     * field - the field to be checked
     * restricted - a boolean field, indicating if the field list has been
       manually restricted using a requested clause)
     * requested - The select_related() dictionary.
     * load_fields - the set of fields to be loaded on this model
     * reverse - boolean, True if we are checking a reverse select related
    """
    if not field.rel:
        return False
    if field.rel.parent_link and not reverse:
        return False
    if restricted:
        if reverse and field.related_query_name() not in requested:
            return False
        if not reverse and field.name not in requested:
            return False
    if not restricted and field.null:
        return False
    if load_fields:
        if field.name not in load_fields:
            if restricted and field.name in requested:
                raise InvalidQuery("Field %s.%s cannot be both deferred"
                                   " and traversed using select_related"
                                   " at the same time." %
                                   (field.model._meta.object_name, field.name))
            return False
    return True

# This function is needed because data descriptors must be defined on a class
# object, not an instance, to have any effect.


def deferred_class_factory(model, attrs):
    """
    Returns a class object that is a copy of "model" with the specified "attrs"
    being replaced with DeferredAttribute objects. The "pk_value" ties the
    deferred attributes to a particular instance of the model.
    """
    class Meta:
        proxy = True
        app_label = model._meta.app_label

    # The app_cache wants a unique name for each model, otherwise the new class
    # won't be created (we get an old one back). Therefore, we generate the
    # name using the passed in attrs. It's OK to reuse an existing class
    # object if the attrs are identical.
    name = "%s_Deferred_%s" % (model.__name__, '_'.join(sorted(list(attrs))))
    name = util.truncate_name(name, 80, 32)

    overrides = dict([(attr, DeferredAttribute(attr, model))
            for attr in attrs])
    overrides["Meta"] = Meta
    overrides["__module__"] = model.__module__
    overrides["_deferred"] = True
    return type(str(name), (model,), overrides)


# The following function is also used to unpickle model instances with deferred
# fields.
deferred_class_factory.__safe_for_unpickling__ = True
