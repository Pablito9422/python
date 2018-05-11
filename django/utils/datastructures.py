import copy
from collections import OrderedDict
from collections.abc import Mapping
from functools import wraps


class OrderedSet:
    """
    A set which keeps the ordering of the inserted items.
    Currently backs onto OrderedDict.
    """

    def __init__(self, iterable=None):
        self.dict = OrderedDict.fromkeys(iterable or ())

    def add(self, item):
        self.dict[item] = None

    def remove(self, item):
        del self.dict[item]

    def discard(self, item):
        try:
            self.remove(item)
        except KeyError:
            pass

    def __iter__(self):
        return iter(self.dict)

    def __contains__(self, item):
        return item in self.dict

    def __bool__(self):
        return bool(self.dict)

    def __len__(self):
        return len(self.dict)


class MultiValueDictKeyError(KeyError):
    pass


class MultiValueDict(dict):
    """
    A subclass of dictionary customized to handle multiple values for the
    same key.

    >>> d = MultiValueDict({'name': ['Adrian', 'Simon'], 'position': ['Developer']})
    >>> d['name']
    'Simon'
    >>> d.getlist('name')
    ['Adrian', 'Simon']
    >>> d.getlist('doesnotexist')
    []
    >>> d.getlist('doesnotexist', ['Adrian', 'Simon'])
    ['Adrian', 'Simon']
    >>> d.get('lastname', 'nonexistent')
    'nonexistent'
    >>> d.setlist('lastname', ['Holovaty', 'Willison'])

    This class exists to solve the irritating problem raised by cgi.parse_qs,
    which returns a list for every key, even though most Web forms submit
    single name-value pairs.
    """
    def __init__(self, key_to_list_mapping=()):
        super().__init__(key_to_list_mapping)

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, super().__repr__())

    def __getitem__(self, key):
        """
        Return the last data value for this key, or [] if it's an empty list;
        raise KeyError if not found.
        """
        try:
            list_ = super().__getitem__(key)
        except KeyError:
            raise MultiValueDictKeyError(key)
        try:
            return list_[-1]
        except IndexError:
            return []

    def __setitem__(self, key, value):
        super().__setitem__(key, [value])

    def __copy__(self):
        return self.__class__([
            (k, v[:])
            for k, v in self.lists()
        ])

    def __deepcopy__(self, memo):
        result = self.__class__()
        memo[id(self)] = result
        for key, value in dict.items(self):
            dict.__setitem__(result, copy.deepcopy(key, memo),
                             copy.deepcopy(value, memo))
        return result

    def __getstate__(self):
        return {**self.__dict__, '_data': {k: self._getlist(k) for k in self}}

    def __setstate__(self, obj_dict):
        data = obj_dict.pop('_data', {})
        for k, v in data.items():
            self.setlist(k, v)
        self.__dict__.update(obj_dict)

    def get(self, key, default=None):
        """
        Return the last data value for the passed key. If key doesn't exist
        or value is an empty list, return `default`.
        """
        try:
            val = self[key]
        except KeyError:
            return default
        if val == []:
            return default
        return val

    def _getlist(self, key, default=None, force_list=False):
        """
        Return a list of values for the key.

        Used internally to manipulate values list. If force_list is True,
        return a new copy of values.
        """
        try:
            values = super().__getitem__(key)
        except KeyError:
            if default is None:
                return []
            return default
        else:
            if force_list:
                values = list(values) if values is not None else None
            return values

    def getlist(self, key, default=None):
        """
        Return the list of values for the key. If key doesn't exist, return a
        default value.
        """
        return self._getlist(key, default, force_list=True)

    def setlist(self, key, list_):
        super().__setitem__(key, list_)

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
            # Do not return default here because __setitem__() may store
            # another value -- QueryDict.__setitem__() does. Look it up.
        return self[key]

    def setlistdefault(self, key, default_list=None):
        if key not in self:
            if default_list is None:
                default_list = []
            self.setlist(key, default_list)
            # Do not return default_list here because setlist() may store
            # another value -- QueryDict.setlist() does. Look it up.
        return self._getlist(key)

    def appendlist(self, key, value):
        """Append an item to the internal list associated with key."""
        self.setlistdefault(key).append(value)

    def items(self):
        """
        Yield (key, value) pairs, where value is the last item in the list
        associated with the key.
        """
        for key in self:
            yield key, self[key]

    def lists(self):
        """Yield (key, list) pairs."""
        return iter(super().items())

    def values(self):
        """Yield the last value on every key list."""
        for key in self:
            yield self[key]

    def copy(self):
        """Return a shallow copy of this object."""
        return copy.copy(self)

    def update(self, *args, **kwargs):
        """Extend rather than replace existing key lists."""
        if len(args) > 1:
            raise TypeError("update expected at most 1 arguments, got %d" % len(args))
        if args:
            other_dict = args[0]
            if isinstance(other_dict, MultiValueDict):
                for key, value_list in other_dict.lists():
                    self.setlistdefault(key).extend(value_list)
            else:
                try:
                    for key, value in other_dict.items():
                        self.setlistdefault(key).append(value)
                except TypeError:
                    raise ValueError("MultiValueDict.update() takes either a MultiValueDict or dictionary")
        for key, value in kwargs.items():
            self.setlistdefault(key).append(value)

    def dict(self):
        """Return current object as a dict with singular values."""
        return {key: self[key] for key in self}


class ImmutableList(tuple):
    """
    A tuple-like object that raises useful errors when it is asked to mutate.

    Example::

        >>> a = ImmutableList(range(5), warning="You cannot mutate this.")
        >>> a[3] = '4'
        Traceback (most recent call last):
            ...
        AttributeError: You cannot mutate this.
    """

    def __new__(cls, *args, warning='ImmutableList object is immutable.', **kwargs):
        self = tuple.__new__(cls, *args, **kwargs)
        self.warning = warning
        return self

    def complain(self, *wargs, **kwargs):
        if isinstance(self.warning, Exception):
            raise self.warning
        else:
            raise AttributeError(self.warning)

    # All list mutation functions complain.
    __delitem__ = complain
    __delslice__ = complain
    __iadd__ = complain
    __imul__ = complain
    __setitem__ = complain
    __setslice__ = complain
    append = complain
    extend = complain
    insert = complain
    pop = complain
    remove = complain
    sort = complain
    reverse = complain


class DictWrapper(dict):
    """
    Wrap accesses to a dictionary so that certain values (those starting with
    the specified prefix) are passed through a function before being returned.
    The prefix is removed before looking up the real value.

    Used by the SQL construction code to ensure that values are correctly
    quoted before being used.
    """
    def __init__(self, data, func, prefix):
        super().__init__(data)
        self.func = func
        self.prefix = prefix

    def __getitem__(self, key):
        """
        Retrieve the real value after stripping the prefix string (if
        present). If the prefix is present, pass the value through self.func
        before returning, otherwise return the raw value.
        """
        use_func = key.startswith(self.prefix)
        if use_func:
            key = key[len(self.prefix):]
        value = super().__getitem__(key)
        if use_func:
            return self.func(value)
        return value


def _destruct_iterable_mapping_values(data):
    for i, elem in enumerate(data):
        if len(elem) != 2:
            raise ValueError("dictionary update sequence element #{} has "
                             "length {}; 2 is required".format(i, len(elem)))

        if not isinstance(elem[0], str):
            raise ValueError('Element key invalid, only strings are allowed')

        yield tuple(elem)


def lowercased_key(method):
    @wraps(method)
    def wrapped(self, key, *args, **kwargs):
        return method(self, key.lower(), *args, **kwargs)
    return wrapped


class ImmutableCaseInsensitiveDict(Mapping):
    """An immutable case-insensitive dictionary that still preserves
    the case of the original keys used to create it."""

    def __init__(self, data):
        if not isinstance(data, Mapping):
            data = {k: v for k, v in _destruct_iterable_mapping_values(data)}
        self._store = {k.lower(): (k, v) for k, v in data.items()}

    @lowercased_key
    def __getitem__(self, key):
        return self._store[key][1]

    def __len__(self):
        return len(self._store)

    def __eq__(self, other):
        if not isinstance(other, Mapping):
            return NotImplemented
        return {
            k.lower(): v for k, v in self.items()
        } == {
            k.lower(): v for k, v in other.items()
        }

    def __iter__(self):
        return (original_key for original_key, value in self._store.values())

    def __repr__(self):
        return repr({key: value for key, value in self._store.values()})

    def copy(self):
        return ImmutableCaseInsensitiveDict({
            k: v[1] for k, v in self._store.items()
        })


class EnvironHeaders(ImmutableCaseInsensitiveDict):
    IGNORE_EXCEPTIONS = {'HTTP_CONTENT_TYPE', 'HTTP_CONTENT_LENGTH'}
    SPECIAL_UNCHANGED_HEADERS = {'CONTENT_TYPE', 'CONTENT_LENGTH'}
    HTTP_PREFIX = 'HTTP_'

    def __init__(self, environ):
        header_name_generator = ((
            self.parse_cgi_header_name(header_name), value
        ) for header_name, value in environ.items())
        headers = {
            header: value for header, value in header_name_generator if header
        }

        super().__init__(headers)

    @classmethod
    def _style_header_name(cls, header_name):
        return header_name.title()

    @classmethod
    def parse_cgi_header_name(cls, cgi_header):
        ignore_header = (
            cgi_header in cls.IGNORE_EXCEPTIONS or
            not cgi_header.startswith(cls.HTTP_PREFIX) and
            cgi_header not in cls.SPECIAL_UNCHANGED_HEADERS)

        if ignore_header:
            return None

        if cgi_header not in cls.SPECIAL_UNCHANGED_HEADERS:
            cgi_header = cgi_header[len(cls.HTTP_PREFIX):]

        return cls._style_header_name(cgi_header.replace('_', '-'))
