import collections
import imp
from importlib import import_module
from optparse import OptionParser, NO_DEFAULT
import os
import sys

import freedom
from freedom.apps import apps
from freedom.conf import settings
from freedom.core.exceptions import ImproperlyConfigured
from freedom.core.management.base import BaseCommand, CommandError, handle_default_options
from freedom.core.management.color import color_style
from freedom.utils import lru_cache
from freedom.utils import six

# For backwards compatibility: get_version() used to be in this module.
from freedom import get_version


def find_commands(management_dir):
    """
    Given a path to a management directory, returns a list of all the command
    names that are available.

    Returns an empty list if no commands are defined.
    """
    command_dir = os.path.join(management_dir, 'commands')
    try:
        return [f[:-3] for f in os.listdir(command_dir)
                if not f.startswith('_') and f.endswith('.py')]
    except OSError:
        return []


def find_management_module(app_name):
    """
    Determines the path to the management module for the given app_name,
    without actually importing the application or the management module.

    Raises ImportError if the management module cannot be found for any reason.
    """
    # TODO: this method is only called from get_commands() which has already
    # imported the application module at that point.

    parts = app_name.split('.')
    parts.append('management')
    parts.reverse()
    part = parts.pop()
    path = None

    # When using manage.py, the project module is added to the path,
    # loaded, then removed from the path. This means that
    # testproject.testapp.models can be loaded in future, even if
    # testproject isn't in the path. When looking for the management
    # module, we need look for the case where the project name is part
    # of the app_name but the project directory itself isn't on the path.
    try:
        f, path, descr = imp.find_module(part, path)
    except ImportError:
        if os.path.basename(os.getcwd()) != part:
            raise
    else:
        if f:
            f.close()

    while parts:
        part = parts.pop()
        f, path, descr = imp.find_module(part, [path] if path else None)
        if f:
            f.close()
    return path


def load_command_class(app_name, name):
    """
    Given a command name and an application name, returns the Command
    class instance. All errors raised by the import process
    (ImportError, AttributeError) are allowed to propagate.
    """
    module = import_module('%s.management.commands.%s' % (app_name, name))
    return module.Command()


@lru_cache.lru_cache(maxsize=None)
def get_commands():
    """
    Returns a dictionary mapping command names to their callback applications.

    This works by looking for a management.commands package in freedom.core, and
    in each installed application -- if a commands package exists, all commands
    in that package are registered.

    Core commands are always included. If a settings module has been
    specified, user-defined commands will also be included.

    The dictionary is in the format {command_name: app_name}. Key-value
    pairs from this dictionary can then be used in calls to
    load_command_class(app_name, command_name)

    If a specific version of a command must be loaded (e.g., with the
    startapp command), the instantiated module can be placed in the
    dictionary in place of the application name.

    The dictionary is cached on the first call and reused on subsequent
    calls.
    """
    commands = {name: 'freedom.core' for name in find_commands(__path__[0])}

    # Find the installed apps
    try:
        settings.INSTALLED_APPS
    except ImproperlyConfigured:
        # Still useful for commands that do not require functional
        # settings, like startproject or help.
        app_names = []
    else:
        app_configs = apps.get_app_configs()
        app_names = [app_config.name for app_config in app_configs]

    # Find and load the management module for each installed app.
    for app_name in reversed(app_names):
        try:
            path = find_management_module(app_name)
            commands.update({name: app_name for name in find_commands(path)})
        except ImportError:
            pass  # No management module - ignore this app

    return commands


def call_command(name, *args, **options):
    """
    Calls the given command, with the given options and args/kwargs.

    This is the primary API you should use for calling specific commands.

    Some examples:
        call_command('syncdb')
        call_command('shell', plain=True)
        call_command('sqlall', 'myapp')
    """
    # Load the command object.
    try:
        app_name = get_commands()[name]
    except KeyError:
        raise CommandError("Unknown command: %r" % name)

    if isinstance(app_name, BaseCommand):
        # If the command is already loaded, use it directly.
        klass = app_name
    else:
        klass = load_command_class(app_name, name)

    # Grab out a list of defaults from the options. optparse does this for us
    # when the script runs from the command line, but since call_command can
    # be called programmatically, we need to simulate the loading and handling
    # of defaults (see #10080 for details).
    defaults = {}
    for opt in klass.option_list:
        if opt.default is NO_DEFAULT:
            defaults[opt.dest] = None
        else:
            defaults[opt.dest] = opt.default
    defaults.update(options)

    return klass.execute(*args, **defaults)


class LaxOptionParser(OptionParser):
    """
    An option parser that doesn't raise any errors on unknown options.

    This is needed because the --settings and --pythonpath options affect
    the commands (and thus the options) that are available to the user.
    """
    def error(self, msg):
        pass

    def print_help(self):
        """Output nothing.

        The lax options are included in the normal option parser, so under
        normal usage, we don't need to print the lax options.
        """
        pass

    def print_lax_help(self):
        """Output the basic options available to every command.

        This just redirects to the default print_help() behavior.
        """
        OptionParser.print_help(self)

    def _process_args(self, largs, rargs, values):
        """
        Overrides OptionParser._process_args to exclusively handle default
        options and ignore args and other options.

        This overrides the behavior of the super class, which stop parsing
        at the first unrecognized option.
        """
        while rargs:
            arg = rargs[0]
            try:
                if arg[0:2] == "--" and len(arg) > 2:
                    # process a single long option (possibly with value(s))
                    # the superclass code pops the arg off rargs
                    self._process_long_opt(rargs, values)
                elif arg[:1] == "-" and len(arg) > 1:
                    # process a cluster of short options (possibly with
                    # value(s) for the last one only)
                    # the superclass code pops the arg off rargs
                    self._process_short_opts(rargs, values)
                else:
                    # it's either a non-default option or an arg
                    # either way, add it to the args list so we can keep
                    # dealing with options
                    del rargs[0]
                    raise Exception
            except:  # Needed because we might need to catch a SystemExit
                largs.append(arg)


class ManagementUtility(object):
    """
    Encapsulates the logic of the freedom-admin.py and manage.py utilities.

    A ManagementUtility has a number of commands, which can be manipulated
    by editing the self.commands dictionary.
    """
    def __init__(self, argv=None):
        self.argv = argv or sys.argv[:]
        self.prog_name = os.path.basename(self.argv[0])

    def main_help_text(self, commands_only=False):
        """
        Returns the script's main help text, as a string.
        """
        if commands_only:
            usage = sorted(get_commands().keys())
        else:
            usage = [
                "",
                "Type '%s help <subcommand>' for help on a specific subcommand." % self.prog_name,
                "",
                "Available subcommands:",
            ]
            commands_dict = collections.defaultdict(lambda: [])
            for name, app in six.iteritems(get_commands()):
                if app == 'freedom.core':
                    app = 'freedom'
                else:
                    app = app.rpartition('.')[-1]
                commands_dict[app].append(name)
            style = color_style()
            for app in sorted(commands_dict.keys()):
                usage.append("")
                usage.append(style.NOTICE("[%s]" % app))
                for name in sorted(commands_dict[app]):
                    usage.append("    %s" % name)
            # Output an extra note if settings are not properly configured
            try:
                settings.INSTALLED_APPS
            except ImproperlyConfigured as err:
                usage.append(style.NOTICE(
                    "Note that only Freedom core commands are listed as settings "
                    "are not properly configured (error: %s)." % err))

        return '\n'.join(usage)

    def fetch_command(self, subcommand):
        """
        Tries to fetch the given subcommand, printing a message with the
        appropriate command called from the command line (usually
        "freedom-admin.py" or "manage.py") if it can't be found.
        """
        # Get commands outside of try block to prevent swallowing exceptions
        commands = get_commands()
        try:
            app_name = commands[subcommand]
        except KeyError:
            # This might trigger ImproperlyConfigured (masked in get_commands)
            settings.INSTALLED_APPS
            sys.stderr.write("Unknown command: %r\nType '%s help' for usage.\n" %
                (subcommand, self.prog_name))
            sys.exit(1)
        if isinstance(app_name, BaseCommand):
            # If the command is already loaded, use it directly.
            klass = app_name
        else:
            klass = load_command_class(app_name, subcommand)
        return klass

    def autocomplete(self):
        """
        Output completion suggestions for BASH.

        The output of this function is passed to BASH's `COMREPLY` variable and
        treated as completion suggestions. `COMREPLY` expects a space
        separated string as the result.

        The `COMP_WORDS` and `COMP_CWORD` BASH environment variables are used
        to get information about the cli input. Please refer to the BASH
        man-page for more information about this variables.

        Subcommand options are saved as pairs. A pair consists of
        the long option string (e.g. '--exclude') and a boolean
        value indicating if the option requires arguments. When printing to
        stdout, a equal sign is appended to options which require arguments.

        Note: If debugging this function, it is recommended to write the debug
        output in a separate file. Otherwise the debug output will be treated
        and formatted as potential completion suggestions.
        """
        # Don't complete if user hasn't sourced bash_completion file.
        if 'DJANGO_AUTO_COMPLETE' not in os.environ:
            return

        cwords = os.environ['COMP_WORDS'].split()[1:]
        cword = int(os.environ['COMP_CWORD'])

        try:
            curr = cwords[cword - 1]
        except IndexError:
            curr = ''

        subcommands = list(get_commands()) + ['help']
        options = [('--help', None)]

        # subcommand
        if cword == 1:
            print(' '.join(sorted(filter(lambda x: x.startswith(curr), subcommands))))
        # subcommand options
        # special case: the 'help' subcommand has no options
        elif cwords[0] in subcommands and cwords[0] != 'help':
            subcommand_cls = self.fetch_command(cwords[0])
            # special case: 'runfcgi' stores additional options as
            # 'key=value' pairs
            if cwords[0] == 'runfcgi':
                from freedom.core.servers.fastcgi import FASTCGI_OPTIONS
                options += [(k, 1) for k in FASTCGI_OPTIONS]
            # special case: add the names of installed apps to options
            elif cwords[0] in ('dumpdata', 'sql', 'sqlall', 'sqlclear',
                    'sqlcustom', 'sqlindexes', 'sqlsequencereset', 'test'):
                try:
                    app_configs = apps.get_app_configs()
                    # Get the last part of the dotted path as the app name.
                    options += [(app_config.label, 0) for app_config in app_configs]
                except ImportError:
                    # Fail silently if DJANGO_SETTINGS_MODULE isn't set. The
                    # user will find out once they execute the command.
                    pass
            options += [(s_opt.get_opt_string(), s_opt.nargs) for s_opt in
                        subcommand_cls.option_list]
            # filter out previously specified options from available options
            prev_opts = [x.split('=')[0] for x in cwords[1:cword - 1]]
            options = [opt for opt in options if opt[0] not in prev_opts]

            # filter options by current input
            options = sorted((k, v) for k, v in options if k.startswith(curr))
            for option in options:
                opt_label = option[0]
                # append '=' to options which require args
                if option[1]:
                    opt_label += '='
                print(opt_label)
        sys.exit(1)

    def execute(self):
        """
        Given the command-line arguments, this figures out which subcommand is
        being run, creates a parser appropriate to that command, and runs it.
        """
        # Preprocess options to extract --settings and --pythonpath.
        # These options could affect the commands that are available, so they
        # must be processed early.
        parser = LaxOptionParser(usage="%prog subcommand [options] [args]",
                                 version=get_version(),
                                 option_list=BaseCommand.option_list)
        try:
            options, args = parser.parse_args(self.argv)
            handle_default_options(options)
        except:  # Needed because parser.parse_args can raise SystemExit
            pass  # Ignore any option errors at this point.

        try:
            settings.INSTALLED_APPS
        except ImproperlyConfigured:
            # Some commands are supposed to work without configured settings
            pass
        else:
            freedom.setup()

        self.autocomplete()

        try:
            subcommand = self.argv[1]
        except IndexError:
            subcommand = 'help'  # Display help if no arguments were given.

        if subcommand == 'help':
            if len(args) <= 2:
                parser.print_lax_help()
                sys.stdout.write(self.main_help_text() + '\n')
            elif args[2] == '--commands':
                sys.stdout.write(self.main_help_text(commands_only=True) + '\n')
            else:
                self.fetch_command(args[2]).print_help(self.prog_name, args[2])
        elif subcommand == 'version':
            sys.stdout.write(parser.get_version() + '\n')
        # Special-cases: We want 'freedom-admin.py --version' and
        # 'freedom-admin.py --help' to work, for backwards compatibility.
        elif self.argv[1:] == ['--version']:
            # LaxOptionParser already takes care of printing the version.
            pass
        elif self.argv[1:] in (['--help'], ['-h']):
            parser.print_lax_help()
            sys.stdout.write(self.main_help_text() + '\n')
        else:
            self.fetch_command(subcommand).run_from_argv(self.argv)


def execute_from_command_line(argv=None):
    """
    A simple method that runs a ManagementUtility.
    """
    utility = ManagementUtility(argv)
    utility.execute()
