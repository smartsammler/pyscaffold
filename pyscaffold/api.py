# -*- coding: utf-8 -*-
"""
Exposed API for accessing PyScaffold via Python.
"""
from __future__ import absolute_import

import os
from copy import deepcopy
from datetime import date

from six import string_types

import pyscaffold

from . import info, repo, utils
from .exceptions import (
    DirectoryAlreadyExists,
    DirectoryDoesNotExist,
    GitNotConfigured,
    GitNotInstalled,
    InvalidIdentifier
)
from .structure import (
    FileOp,
    add_namespace,
    apply_update_rules,
    create_structure,
    define_structure
)

# -------- Actions --------

DEFAULT_OPTIONS = {'update': False,
                   'force': False,
                   'namespace': '',
                   'description': 'Add a short description here!',
                   'url': 'http://...',
                   'license': 'none',
                   'version': pyscaffold.__version__,
                   'classifiers': utils.list2str(
                        ['Development Status :: 4 - Beta',
                         'Programming Language :: Python'],
                        indent=4, brackets=False, quotes=False, sep='')}


def get_default_opts(project_name, **aux_opts):
    """Creates default options using auxiliary options as keyword argument

    Use this function if you want to use PyScaffold from another application
    in order to generate an option dictionary that can than be passed to
    :obj:`create_project`.

    Args:
        project_name (str): name of the project
        **aux_opts: auxiliary options as keyword parameters
            (see :obj:`create_project` extensive list of options)

    Returns:
        dict: options with default values set

    Raises:
        :class:`~.DirectoryDoesNotExist`: when PyScaffold is told to
            update an inexistent directory
        :class:`~.GitNotInstalled`: when git command is not available
        :class:`~.GitNotConfigured`: when git does not know user information

    Note:
        This function uses git to determine some options, such as author name
        and email.
    """

    # This function uses information from git, so make sure it is available
    _verify_git()

    opts = DEFAULT_OPTIONS.copy()
    opts.update(aux_opts)
    opts['project'] = project_name

    opts.setdefault('package', utils.make_valid_identifier(opts['project']))
    opts.setdefault('author', info.username())
    opts.setdefault('email', info.email())
    opts.setdefault('release_date', date.today().strftime('%Y-%m-%d'))
    opts.setdefault('year', date.today().year)
    opts.setdefault('title',
                    '='*len(opts['project']) + '\n' + opts['project'] + '\n' +
                    '='*len(opts['project']))

    # Initialize empty list of all requirements and extensions
    # (since not using deep_copy for the DEFAULT_OPTIONS, better add compound
    # values inside this function)
    opts.setdefault('requirements', list())
    opts.setdefault('extensions', list())

    opts['namespace'] = utils.prepare_namespace(opts['namespace'])
    if opts['namespace']:
        opts['root_pkg'] = opts['namespace'][0]
        opts['namespace_pkg'] = ".".join([opts['namespace'][-1],
                                          opts['package']])
    else:
        opts['root_pkg'] = opts['package']
        opts['namespace_pkg'] = opts['package']
    if opts['update']:
        if not os.path.exists(project_name):
            raise DirectoryDoesNotExist(
                "Project {project} does not exist and thus cannot be "
                "updated!".format(project=project_name))
        opts = info.project(opts)
        # Reset project name since the one from setup.cfg might be different
        opts['project'] = project_name
    return opts


def verify_options_consistency(scaffold):
    """Perform some sanity checks about the given options."""
    opts = scaffold.options
    if os.path.exists(opts['project']):
        if not opts['update'] and not opts['force']:
            raise DirectoryAlreadyExists(
                "Directory {dir} already exists! Use the `update` option to "
                "update an existing project or the `force` option to "
                "overwrite an existing directory.".format(dir=opts['project']))
    if not utils.is_valid_identifier(opts['package']):
        raise InvalidIdentifier(
            "Package name {} is not a valid "
            "identifier.".format(opts['package']))


def init_git(scaffold):
    """Add revision control to the generated files."""
    opts = scaffold.options
    proj_struct = scaffold.changed_structure
    if not opts['update'] and not repo.is_git_repo(opts['project']):
        repo.init_commit_repo(opts['project'], proj_struct)


# -------- API --------

def create_project(opts):
    """Create the project's directory structure

    Args:
        opts (dict): options of the project

    Valid options include:

    :Naming:                - **project** (*str*)
                            - **package** (*str*)
                            - **namespace** (*str*)

    :Package Information:   - **author** (*str*)
                            - **email** (*str*)
                            - **release_date** (*str*)
                            - **year** (*str*)
                            - **title** (*str*)
                            - **description** (*str*)
                            - **url** (*str*)
                            - **classifiers** (*str*)
                            - **requirements** (*list*)

    :PyScaffold Control:    - **update** (*bool*)
                            - **force** (*bool*)
                            - **extensions** (*list*)

    Some of these options are equivalent to the command line options, others
    are used for creating the basic python package meta information, but the
    last tree can change the way PyScaffold behaves.

    When the **force** flag is ``True`` existing files will be overwritten.
    When the **update** flag is ``True``, PyScaffold will consider that some
    files can be updated (usually the packaging boilerplate),
    but will keep others intact.

    Finally, the **extensions** list may contain any function that follows the
    `extension API <extensions>`_. Note that some PyScaffold features, such as
    travis, tox and pre-commit support, are implemented as built-in extensions.
    In order to use these features it is necessary to include the respective
    functions in the extension list.
    All built-in extensions are accessible via :mod:`pyscaffold.extensions`
    submodule, and use ``extend_project`` as naming convention::

        # Using built-in extensions
        from pyscaffold.extensions import pre_commit, travis, tox

        opts = { #...
                 "extensions": [e.extend_project
                                for e in pre_commit, travis, tox]}
        create_project(opts)

    Note that extensions may define extra options. For example, built-in
    cookiecutter extension define a ``cookiecutter_template`` option that
    should be the address to the git repository used as template.
    """
    scaffold = Scaffold(opts, define_structure(opts),
                        before_generate=[verify_options_consistency],
                        after_generate=[init_git])

    # Activate the extensions
    extensions = opts.get('extensions', [])
    for extend in extensions:
        extend(scaffold)

    # Call the before_generate hooks
    for hook in scaffold.before_generate:
        hook(scaffold)

    # Decide which files should be generated, and do the job
    proj_struct = apply_update_rules(scaffold.structure, scaffold.options)
    proj_struct = add_namespace(opts, proj_struct)
    # ^ add namespace here, so extensions may benefit
    changed = create_structure(proj_struct,
                               update=opts['update'] or opts['force'])
    scaffold.changed_structure = changed

    # Call the before_generate hooks
    for hook in scaffold.after_generate:
        hook(scaffold)


class Scaffold(FileOp):
    """Representation of the actions performed by the ``putup`` command.

    Args:
        options (dict): dict with all PyScaffold options, including the ones
            parsed from command line

    Attributes:
        options (dict): dict with all PyScaffold options, including the ones
            parsed from command line
        before_generate ([function]): array filled with functions that will be
            executed **before** the generation of files
        after_generate ([function]): array filled with functions that will be
            executed **after** the generation of files
        structure (dict): directory tree representation as a (possibly nested)
            dictionary.
            The keys indicate the path where a file will be generated,
            while the value indicates the content.
            Additionally, tuple values are allowed in order to specify the
            rule that will be followed during an ``update`` operation
            (see :class:`~.FileOp`).
            In this case, the first element is the file content and the second
            element is the update rule. For example, the dictionary::

                {'project': {
                    'namespace': {
                        'module.py': ('print("Hello World!")',
                                      Scaffold.NO_UPDATE)}}

            represents a ``project/namespace/module.py`` file with content
            ``print("Hello World!")``, that will be created only if not
            present.
        changed_structure (dict): similar to :attr:`~.Scaffold.structure`
            but just contains the files that were actually changed by
            PyScaffold, without any update rule. This attribute is an empty
            dict most of the time, but can be used in
            :attr:`~Scaffold.after_generate` hooks.

    Note:
        :attr:`~Scaffold.before_generate` and :attr:`~Scaffold.after_generate`
        hooks should be defined as a function of a single argument,
        the :class:`Scaffold` instance itself.
    """

    def __init__(self, options, structure=None,
                 before_generate=None, after_generate=None):
        self.options = options
        self.structure = structure or {}
        self.changed_structure = {}
        self.before_generate = before_generate or []
        self.after_generate = after_generate or []

    def ensure(self, path, content=None, update_rule=None):
        self.structure = Helper.ensure(self.structure, path, content,
                                       update_rule)

    def reject(self, path):
        self.structure = Helper.reject(self.structure, path)

    def merge(self, new):
        self.structure = Helper.merge(self.structure, new)


class Helper(FileOp):
    """Useful functions for manipulating the action list and project structure.

    Considered a namespace instead of class.
    """

    # -------- Project Structure --------

    @classmethod
    def ensure(cls, structure, path, content=None, update_rule=None):
        """Ensure a file exists in the representation of the project tree
        with the provided content.
        All the parent directories are automatically created.

        Args:
            structure (dict): project representation as (possibly) nested
                :obj:`dict`. See :obj:`~.merge`.
            path (str or list): file path relative to the structure root.
                The directory separator should be ``/`` (forward slash) if
                present.
                Alternatively, a list with the parts of the path can be
                provided, ordered from the structure root to the file itself.
                The following examples are equivalent::

                    'docs/api/index.html'
                    ['docs', 'api', 'index.html']
            content (str): file text contents
            update_rule: see :class:`~.FileOp`, ``None`` by default

        Note:
            Use an empty string as content to ensure a file is created empty.
        """
        # Ensure path is a list.
        if isinstance(path, string_types):
            path = path.split('/')

        # Walk the entire path, creating parents if necessary.
        root = deepcopy(structure)
        last_parent = root
        name = path[-1]
        for parent in path[:-1]:
            if parent not in last_parent:
                last_parent[parent] = {}
            last_parent = last_parent[parent]

        # Get the old value if existent.
        old_value = last_parent.get(name, (None, None))

        # Update the value.
        new_value = (content, update_rule)
        last_parent[name] = cls._merge_file_leaf(old_value, new_value)

        return root

    @staticmethod
    def reject(structure, path):
        """Remove a file from the project tree representation if existent.

        Args:
            structure (dict): project representation as (possibly) nested
                :obj:`dict`. See :obj:`~.merge`.
            path (str or list): file path relative to the structure root.
                The directory separator should be ``/`` (forward slash) if
                present.
                Alternatively, a list with the parts of the path can be
                provided, ordered from the structure root to the file itself.
                The following examples are equivalent::

                    'docs/api/index.html'
                    ['docs', 'api', 'index.html']
        """
        # Ensure path is a list.
        if isinstance(path, string_types):
            path = path.split('/')

        # Walk the entire path, creating parents if necessary.
        root = deepcopy(structure)
        last_parent = root
        name = path[-1]
        for parent in path[:-1]:
            if parent not in last_parent:
                return root  # one ancestor already does not exist, do nothing
            last_parent = last_parent[parent]

        if name in last_parent:
            del last_parent[name]

        return root

    @classmethod
    def merge(cls, old, new):
        """Merge two dict representations for the directory structure.

        Basically a deep dictionary merge, except from the leaf update method.

        Args:
            old (dict): directory descriptor that takes low precedence
                        during the merge
            new (dict): directory descriptor that takes high precedence
                        during the merge

        The directory tree is represented as a (possibly nested) dictionary.
        The keys indicate the path where a file will be generated, while the
        value indicates the content.  Additionally, tuple values are allowed in
        order to specify the rule that will be followed during an ``update``
        operation (see :class:`~.FileOp`).  In this case, the first element is
        the file content and the second element is the update rule. For
        example, the dictionary::

            {'project': {
                'namespace': {
                    'module.py': ('print("Hello World!")',
                                  helpers.NO_UPDATE)}}

        represents a ``project/namespace/module.py`` file with content
        ``print("Hello World!")``, that will be created only if not
        present.

        Returns:
            dict: resulting merged directory representation

        Note:
            Use an empty string as content to ensure a file is created empty.
        """
        return cls._inplace_merge(deepcopy(old), new)

    @classmethod
    def _inplace_merge(cls, old, new):
        """Similar to :obj:`~.merge` but modifies the first dict."""

        for key, value in new.items():
            old_value = old.get(key, None)
            new_is_dict = isinstance(value, dict)
            old_is_dict = isinstance(old_value, dict)
            if new_is_dict and old_is_dict:
                old[key] = cls._inplace_merge(old_value, value)
            elif old_value is not None and not new_is_dict and not old_is_dict:
                # both are defined and final leaves
                old[key] = cls._merge_file_leaf(old_value, value)
            else:
                old[key] = deepcopy(value)

        return old

    @staticmethod
    def _merge_file_leaf(old_value, new_value):
        """Merge leaf values for the directory tree representation.

        The leaf value is expected to be a tuple ``(content, update_rule)``.
        When a string is passed, it is assumed to be the content and
        ``None`` is used for the update rule.

        Args:
            old_value (tuple or str): descriptor for the file that takes low
                                      precedence during the merge
            new_value (tuple or str): descriptor for the file that takes high
                                      precedence during the merge

        Note:
            ``None`` contents are ignored, use and empty string to force empty
            contents.

        Returns:
            tuple or str: resulting value for the merged leaf
        """
        if not isinstance(old_value, (list, tuple)):
            old_value = (old_value, None)
        if not isinstance(new_value, (list, tuple)):
            new_value = (new_value, None)

        content = new_value[0] if new_value[0] is not None else old_value[0]
        rule = new_value[1] if new_value[1] is not None else old_value[1]

        if rule is None:
            return content

        return (content, rule)

    # -------- Action List --------

    @classmethod
    def register(cls, actions, action, before=None, after=None):
        """Register a new action to be performed during scaffold.

        Args:
            actions (list): previous action list.
            action (callable): function with two arguments: the first one is a
                (nested) dict representing the file structure of the project
                and the second is a dict with scaffold options.
                This function **MUST** return a tuple with two elements similar
                to its arguments. Example::

                    def do_nothing(struct, opts):
                        return (struct, opts)

            **kwargs (dict): keyword arguments make it possible to choose a
                specific order when executing actions: when ``before`` or
                ``after`` keywords are provided, the argument value is used as
                a reference position for the new action. Example::

                    helpers.register(actions, do_nothing,
                                     after='create_structure')
                        # Look for the first action with a name
                        # `create_structure` and inserts `do_nothing` after it.
                        # If more than one registered action is named
                        # `create_structure`, the first one is selected.

                    helpers.register(
                        actions, do_nothing,
                        before='pyscaffold.structure:create_structure')
                        # Similar to the previous example, but the probability
                        # of name conflict is decreased by including the module
                        # name.

                When no keyword argument is provided, the default execution
                order specifies that the action will be performed after the
                project structure is defined, but before it is written to the
                disk. Example::


                    helpers.register(actions, do_nothing)
                        # The action will take place after
                        # `pyscaffold.structure:define_structure`

        Returns:
            list: modified action list.
        """
        reference = before or after or cls._qualify(define_structure)
        position = cls._find(actions, reference)
        if not before:
            position += 1

        clone = actions[:]
        clone.insert(position, action)

        return clone

    @classmethod
    def unregister(cls, actions, reference):
        """Prevent a specific action to be executed during scaffold.

        Args:
            actions (list): previous action list.
            reference (str): action identifier. Similarly to the keyword
                arguments of :obj:`~.register` it can assume two formats:

                    - the name of the function alone,
                    - the name of the module followed by ``:`` and the name
                      of the function

        Returns:
            list: modified action list.
        """
        position = cls._find(actions, reference)
        return actions[:position] + actions[position+1:]

    @classmethod
    def _find(cls, actions, name):
        if ':' in name:
            names = [cls._qualify(action) for action in actions]
        else:
            names = [action.__name__ for action in actions]

        return names.index(name)

    @staticmethod
    def _qualify(function):
        """Given a function, calculate its identifier.

        A identifier is a string in the format <module name>:<function name>,
        similarly to the convention used for setuptools entry points.
        """
        return '{}:{}'.format(function.__module__, function.__name__)


# -------- Auxiliary functions --------


def _verify_git():
    """Check if git is installed and able to provide the required information.
    """
    if not info.is_git_installed():
        raise GitNotInstalled
    if not info.is_git_configured():
        raise GitNotConfigured
