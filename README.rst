Encrust
==============================

Automate all the steps to add the flavorful, savory crust that macOS
applications written in Python require to launch, which is to say:

    - universal2 binaries
    - code signing
    - notarization
    - archiving

Run ``encrust configure`` for an explanation of how to set it up globally on
your computer, then ``encrust release`` to run it for a particular project.

You will also need an ``encrust_setup.py`` to configure it for your project.

The documentation for how to use Encrust is, unfortunately, extremely thin, but
there are working examples in the `PINPal
<https://github.com/glyph/PINPal/blob/trunk/encrust_setup.py>`_ and
`Pomodouroboros
<https://github.com/glyph/Pomodouroboros/blob/trunk/encrust_setup.py>`_
projects.  Please feel free to `file an issue
<https://github.com/glyph/Encrust/issues/new>`_ if you have questions!
