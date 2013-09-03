# -*- encoding: utf-8 -*-
from __future__ import unicode_literals

import unittest

from django.utils.encoding import force_bytes, force_text, filepath_to_uri
from django.utils import six


class TestEncodingUtils(unittest.TestCase):
    def test_force_bytes_exception(self):
        """
        Test that force_bytes knows how to convert to bytes an exception
        containing non-ASCII characters in its args.
        """
        error_msg = "This is an exception, voilà"
        exc = ValueError(error_msg)
        result = force_bytes(exc)
        self.assertEqual(result, error_msg.encode('utf-8'))

    def test_filepath_to_uri(self):
        self.assertEqual(filepath_to_uri('upload\\чубака.mp4'),
            'upload/%D1%87%D1%83%D0%B1%D0%B0%D0%BA%D0%B0.mp4')
        self.assertEqual(filepath_to_uri('upload\\чубака.mp4'.encode('utf-8')),
            'upload/%D1%87%D1%83%D0%B1%D0%B0%D0%BA%D0%B0.mp4')

    def test_force_text_on_object_with_unbound__unicode__method(self):
        class SomeClass(object):
            def __unicode__(self):
                return u'hi there'

        self.assertEqual(force_text(SomeClass), six.text_type(SomeClass))
