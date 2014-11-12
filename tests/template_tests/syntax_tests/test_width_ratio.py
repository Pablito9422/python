from django.template.base import TemplateSyntaxError
from django.template.loader import get_template
from django.test import TestCase
from django.utils import six

from .utils import render, setup


class WidthRatioTagTests(TestCase):

    @setup({'widthratio01': '{% widthratio a b 0 %}'})
    def test_widthratio01(self):
        output = render('widthratio01', {'a': 50, 'b': 100})
        self.assertEqual(output, '0')

    @setup({'widthratio02': '{% widthratio a b 100 %}'})
    def test_widthratio02(self):
        output = render('widthratio02', {'a': 0, 'b': 0})
        self.assertEqual(output, '0')

    @setup({'widthratio03': '{% widthratio a b 100 %}'})
    def test_widthratio03(self):
        output = render('widthratio03', {'a': 0, 'b': 100})
        self.assertEqual(output, '0')

    @setup({'widthratio04': '{% widthratio a b 100 %}'})
    def test_widthratio04(self):
        output = render('widthratio04', {'a': 50, 'b': 100})
        self.assertEqual(output, '50')

    @setup({'widthratio05': '{% widthratio a b 100 %}'})
    def test_widthratio05(self):
        output = render('widthratio05', {'a': 100, 'b': 100})
        self.assertEqual(output, '100')

    @setup({'widthratio06': '{% widthratio a b 100 %}'})
    def test_widthratio06(self):
        """
        62.5 should round to 63 on Python 2 and 62 on Python 3
        See http://docs.python.org/py3k/whatsnew/3.0.html
        """
        output = render('widthratio06', {'a': 50, 'b': 80})
        self.assertEqual(output, '62' if six.PY3 else '63')

    @setup({'widthratio07': '{% widthratio a b 100 %}'})
    def test_widthratio07(self):
        """
        71.4 should round to 71
        """
        output = render('widthratio07', {'a': 50, 'b': 70})
        self.assertEqual(output, '71')

    # Raise exception if we don't have 3 args, last one an integer
    @setup({'widthratio08': '{% widthratio %}'})
    def test_widthratio08(self):
        with self.assertRaises(TemplateSyntaxError):
            get_template('widthratio08')

    @setup({'widthratio09': '{% widthratio a b %}'})
    def test_widthratio09(self):
        with self.assertRaises(TemplateSyntaxError):
            render('widthratio09', {'a': 50, 'b': 100})

    @setup({'widthratio10': '{% widthratio a b 100.0 %}'})
    def test_widthratio10(self):
        output = render('widthratio10', {'a': 50, 'b': 100})
        self.assertEqual(output, '50')

    @setup({'widthratio11': '{% widthratio a b c %}'})
    def test_widthratio11(self):
        """
        #10043: widthratio should allow max_width to be a variable
        """
        output = render('widthratio11', {'a': 50, 'c': 100, 'b': 100})
        self.assertEqual(output, '50')

    # #18739: widthratio should handle None args consistently with
    # non-numerics
    @setup({'widthratio12a': '{% widthratio a b c %}'})
    def test_widthratio12a(self):
        output = render('widthratio12a', {'a': 'a', 'c': 100, 'b': 100})
        self.assertEqual(output, '')

    @setup({'widthratio12b': '{% widthratio a b c %}'})
    def test_widthratio12b(self):
        output = render('widthratio12b', {'a': None, 'c': 100, 'b': 100})
        self.assertEqual(output, '')

    @setup({'widthratio13a': '{% widthratio a b c %}'})
    def test_widthratio13a(self):
        output = render('widthratio13a', {'a': 0, 'c': 100, 'b': 'b'})
        self.assertEqual(output, '')

    @setup({'widthratio13b': '{% widthratio a b c %}'})
    def test_widthratio13b(self):
        output = render('widthratio13b', {'a': 0, 'c': 100, 'b': None})
        self.assertEqual(output, '')

    @setup({'widthratio14a': '{% widthratio a b c %}'})
    def test_widthratio14a(self):
        with self.assertRaises(TemplateSyntaxError):
            render('widthratio14a', {'a': 0, 'c': 'c', 'b': 100})

    @setup({'widthratio14b': '{% widthratio a b c %}'})
    def test_widthratio14b(self):
        with self.assertRaises(TemplateSyntaxError):
            render('widthratio14b', {'a': 0, 'c': None, 'b': 100})

    @setup({'widthratio15': '{% load custom %}{% widthratio a|noop:"x y" b 0 %}'})
    def test_widthratio15(self):
        """
        Test whitespace in filter argument
        """
        output = render('widthratio15', {'a': 50, 'b': 100})
        self.assertEqual(output, '0')

    # Widthratio with variable assignment
    @setup({'widthratio16': '{% widthratio a b 100 as variable %}-{{ variable }}-'})
    def test_widthratio16(self):
        output = render('widthratio16', {'a': 50, 'b': 100})
        self.assertEqual(output, '-50-')

    @setup({'widthratio17': '{% widthratio a b 100 as variable %}-{{ variable }}-'})
    def test_widthratio17(self):
        output = render('widthratio17', {'a': 100, 'b': 100})
        self.assertEqual(output, '-100-')

    @setup({'widthratio18': '{% widthratio a b 100 as %}'})
    def test_widthratio18(self):
        with self.assertRaises(TemplateSyntaxError):
            get_template('widthratio18')

    @setup({'widthratio19': '{% widthratio a b 100 not_as variable %}'})
    def test_widthratio19(self):
        with self.assertRaises(TemplateSyntaxError):
            get_template('widthratio19')

    @setup({'widthratio20': '{% widthratio a b 100 %}'})
    def test_widthratio20(self):
        output = render('widthratio20', {'a': float('inf'), 'b': float('inf')})
        self.assertEqual(output, '')

    @setup({'widthratio21': '{% widthratio a b 100 %}'})
    def test_widthratio21(self):
        output = render('widthratio21', {'a': float('inf'), 'b': 2})
        self.assertEqual(output, '')
