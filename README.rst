devpi-constrained: releases filter for devpi-server
===================================================

This plugin adds a *constrained* index to `devpi-server`_.
The *constrained* index is read-only and filters releases from its bases similar to `Constraints Files`_ in `pip`_.

.. _devpi-server: http://pypi.python.org/pypi/devpi-server
.. _Constraints Files: https://pip.pypa.io/en/stable/user_guide/#constraints-files
.. _pip: https://pip.pypa.io/


Installation
------------

``devpi-constrained`` needs to be installed alongside ``devpi-server`` to enable *constrained* indexes.

You can install it with::

    pip install devpi-constrained

There is no configuration needed as ``devpi-server`` will automatically discover the plugin through calling hooks using the setuptools entry points mechanism.


Motivation
----------

It is often useful to filter Python packages available for installation.
For example:

- Filter package versions with known security issues
- Provide a "Known Good Set" of packages which have been tested
- Prevent installation of packages with incompatible licenses
- Only allowing vetted packages
- Block package versions with breaking changes

With ``devpi-constrained`` it is possible to provide a package index which enables all of the above and more.


Usage
-----

Create a *constrained* index with ``root/pypi`` as base:

.. code-block::

    $ devpi index -c prod/devpi type=constrained bases=root/pypi
    https://example.com/prod/devpi:
      type=constrained
      bases=root/pypi
      volatile=True
      acl_upload=root
      acl_toxresult_upload=:ANONYMOUS:
      constraints=
      mirror_whitelist=

    $ devpi use prod/devpi

With no constraints set, all releases are available from ``root/pypi``.

Lets add a constraint for ``pip``:

.. code-block::

    $ devpi index constraints+="pip==6.0"
    /prod/devpi constraints+=pip==6.0
    https://example.com/prod/devpi?no_projects=:
      type=constrained
      bases=root/pypi
      volatile=True
      acl_upload=root
      acl_toxresult_upload=:ANONYMOUS:
      constraints=pip==6.0
      mirror_whitelist=

Now only ``pip 6.0`` will be listed when looking for releases of ``pip``:

.. code-block::

    $ devpi list --all pip
    http://localhost:3141/root/pypi/+f/610/3897f1bb68d3f/pip-6.0.tar.gz
    http://localhost:3141/root/pypi/+f/5ec/6732505bd8be4/pip-6.0-py2.py3-none-any.whl

All other packages are still unconstrained.

To block everything else we add the ``*`` constraint:

.. code-block::

    $ devpi index constraints+="*"
    /prod/devpi constraints+=*
    https://example.com/prod/devpi?no_projects=:
      type=constrained
      bases=root/pypi
      volatile=True
      acl_upload=root
      acl_toxresult_upload=:ANONYMOUS:
      constraints=pip==6.0,*
      mirror_whitelist=

This is the difference to ``pip`` constraints, where this isn't possible.

.. code-block::

    $ devpi list --all devpi-server
    GET https://example.com/prod/devpi/devpi-server/
    404 Not Found: no project 'devpi-server'

The ``constraints`` option can be set in bulk from a file.
Create a file ``constraints.txt`` with each constraint in one line::

    pip<8,>4
    # a comment
    devpi-server>=4

Set the ``constraints`` option on your index from the file::

    $ devpi index constraints="$(cat constraints.txt)"
