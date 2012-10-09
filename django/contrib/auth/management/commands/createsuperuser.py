"""
Management utility to create superusers.
"""

import getpass
import sys
from optparse import make_option

from django.contrib.auth import get_user_model
from django.contrib.auth.management import get_default_username
from django.core import exceptions
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS
from django.utils.six.moves import input
from django.utils.text import capfirst


class Command(BaseCommand):

    def __init__(self, *args, **kwargs):
        # an __init__ method is here largely to support swapping out custom user
        # models in tests
        super(Command, self).__init__(*args, **kwargs)
        self.UserModel = get_user_model()
        self.required_fields = self.UserModel.REQUIRED_FIELDS
        self.username_field_name = getattr(self.UserModel, 'USERNAME_FIELD', 'username')
        self.username_field = self.UserModel._meta.get_field(self.username_field_name)
        if 'username' in self.required_fields and not self.username_field_name == 'username':
            CommandError('Custom User objects requiring a "username" field must'
                    'designate it as the USERNAME_FIELD. This is required when'
                    'creating superusers')

        self.option_list = BaseCommand.option_list + (
            make_option('--%s' % self.username_field_name, dest='username', default=None,
                help='Specifies the %s for the superuser.' % self.username_field_name),
            make_option('--noinput', action='store_false', dest='interactive', default=True,
                help=('Tells Django to NOT prompt the user for input of any kind. '
                    'You must use --%s with --noinput, along with an option for '
                    'any other required field. Superusers created with --noinput will '
                    ' not be able to log in until they\'re given a valid password.' %
                    self.username_field_name)),
            make_option('--database', action='store', dest='database',
                default=DEFAULT_DB_ALIAS, help='Specifies the database to use. Default is "default".'),
        ) + tuple(
            make_option('--%s' % field, dest=field, default=None,
                help='Specifies the %s for the superuser.' % field)
            for field in self.required_fields
        )

    option_list = BaseCommand.option_list
    help = 'Used to create a superuser.'

    def handle(self, *args, **options):
        username = options.get('username', None)
        interactive = options.get('interactive')
        verbosity = int(options.get('verbosity', 1))
        database = options.get('database')

        other_fields = self.required_fields

        # If not provided, create the user with an unusable password
        password = None
        other_data = {}

        # Do quick and dirty validation if --noinput
        if not interactive:
            try:
                if not username:
                    raise CommandError("You must use --%s with --noinput." %
                            self.username_field_name)
                username = self.username_field.clean(username, None)

                for field_name in other_fields:
                    if options.get(field_name):
                        field = self.UserModel._meta.get_field(field_name)
                        other_data[field_name] = field.clean(options[field_name], None)
                    else:
                        raise CommandError("You must use --%s with --noinput." % field_name)
            except exceptions.ValidationError as e:
                raise CommandError('; '.join(e.messages))

        else:
            # Prompt for username/password, and any other required fields.
            # Enclose this whole thing in a try/except to trap for a
            # keyboard interrupt and exit gracefully.
            default_username = get_default_username()
            try:

                # Get a username
                while username is None:
                    if not username:
                        input_msg = capfirst(self.username_field.verbose_name)
                        if default_username:
                            input_msg += " (leave blank to use '%s')" % default_username
                        raw_value = input(input_msg + ': ')

                    if default_username and raw_value == '':
                        raw_value = default_username
                    try:
                        username = self.username_field.clean(raw_value, None)
                    except exceptions.ValidationError as e:
                        self.stderr.write("Error: %s" % '; '.join(e.messages))
                        username = None
                        continue
                    try:
                        self.UserModel.objects.using(database).get_by_natural_key(
                                username)
                    except self.UserModel.DoesNotExist:
                        pass
                    else:
                        self.stderr.write("Error: That %s is already taken." %
                                self.username_field.verbose_name)
                        username = None

                for field_name in other_fields:
                    field = self.UserModel._meta.get_field(field_name)
                    other_data[field_name] = options.get(field_name)
                    while other_data[field_name] is None:
                        raw_value = input(capfirst(field.verbose_name + ': '))
                        try:
                            other_data[field_name] = field.clean(raw_value, None)
                        except exceptions.ValidationError as e:
                            self.stderr.write("Error: %s" % '; '.join(e.messages))
                            other_data[field_name] = None

                # Get a password
                while password is None:
                    if not password:
                        password = getpass.getpass()
                        password2 = getpass.getpass('Password (again): ')
                        if password != password2:
                            self.stderr.write("Error: Your passwords didn't match.")
                            password = None
                            continue
                    if password.strip() == '':
                        self.stderr.write("Error: Blank passwords aren't allowed.")
                        password = None
                        continue

            except KeyboardInterrupt:
                self.stderr.write("\nOperation cancelled.")
                sys.exit(1)

        self.UserModel.objects.db_manager(database).create_superuser(username=username, password=password, **other_data)
        if verbosity >= 1:
            self.stdout.write("Superuser created successfully.")
