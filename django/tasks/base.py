from __future__ import unicode_literals

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from django.utils.module_loading import import_by_path


DEFAULT_CACHE_ALIAS = 'default'


class InvalidTaskBackendError(Exception):
    pass


def _get_task_backend(alias=None):

    if not alias:
        alias = DEFAULT_CACHE_ALIAS
    try:
        conf = settings.QUEUES[alias]
    except KeyError:
        raise ImproperlyConfigured("%s is not defined in QUEUES" % alias)

    args = conf.copy()
    backend = args.pop('BACKEND')
    connection = args.pop('CONNECTION', None)
    try:
        # Trying to import the given backend, in case it's a dotted path
        backend_cls = import_by_path(backend)
    except ImproperlyConfigured as e:
        raise InvalidTaskBackendError("Could not find backend '%s': %s" % (
            backend, e))

    return backend_cls(connection, **args)


class Task(object):
    def __init__(self, func=None, name=None):
        if not func and not (hasattr(self, 'run') and hasattr(self, 'name')):
            raise
        self.run = func
        if name is not None:
            self.name = name
        elif not hasattr(self, 'name'):
            n = getattr(func, '__name__', func.__class__.__name__)
            self.name = '%s.%s' % (func.__module__, n)

    def __repr__(self):
        return "<task %s>" % self.name

    def _get_backend(self, alias=None):
        return _get_task_backend(alias)

    def delay(self, *args, **kwargs):
        backend = self._get_backend()
        return backend.delay(self, *args, **kwargs)

    def __call__(self, *args, **kwargs):
        # call it right away
        return self.run(*args, **kwargs)

