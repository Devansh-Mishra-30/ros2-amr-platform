#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Run every shutdown stage while preserving cleanup failures."""


def run_teardown(stages, primary_error=None):
    """
    Run named cleanup callables in order.

    A stage returning exactly ``False`` marks cleanup unsuccessful. Exceptions
    never disappear: the first failure is re-raised with its traceback, and
    subsequent failures are attached as notes instead of replacing it.
    """
    failure = primary_error
    failure_traceback = (primary_error.__traceback__
                         if primary_error is not None else None)
    success = True
    unsuccessful_stages = []

    for name, cleanup in stages:
        try:
            if cleanup() is False:
                success = False
                unsuccessful_stages.append(name)
        except BaseException as error:
            if failure is None:
                failure = error
                failure_traceback = error.__traceback__
            elif error is not failure:
                failure.add_note(
                    f'Secondary teardown failure in {name}: '
                    f'{type(error).__name__}: {error}'
                )

    if failure is not None:
        if unsuccessful_stages:
            failure.add_note(
                'Unsuccessful teardown result(s): '
                + ', '.join(unsuccessful_stages)
            )
        raise failure.with_traceback(failure_traceback)
    return success
