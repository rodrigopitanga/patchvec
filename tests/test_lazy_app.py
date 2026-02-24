# (C) 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import sys


def test_importing_build_app_and_version_does_not_build_app():
    """Importing build_app or VERSION must not trigger store/model init."""
    # Reload pave.main from scratch to clear any cached _app.
    for key in list(sys.modules):
        if key == "pave.main":
            del sys.modules[key]

    import pave.main as m
    # Force a fresh _app=None state (module may have been loaded by conftest).
    m._app = None

    # Accessing build_app and VERSION must leave _app untouched.
    _ = m.build_app
    _ = m.VERSION
    assert m._app is None, "_app must stay None after importing build_app/VERSION"


def test_accessing_app_attribute_builds_and_caches():
    """Accessing pave.main.app must build the app exactly once."""
    import pave.main as m
    m._app = None  # reset

    app1 = m.app
    assert app1 is not None
    app2 = m.app
    assert app1 is app2, "app must be the same object on repeated access (cached)"
