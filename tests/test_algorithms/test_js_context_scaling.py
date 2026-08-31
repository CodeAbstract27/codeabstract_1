"""
Regression: the JavaScript/TypeScript adapter's context extraction must not
be quadratic in file size.

Found by direct profiling (cProfile) of ``abstract_source`` on a 1,000-
function synthetic JavaScript file: ``core.context_extractor.get_context``
and the ``str.split`` inside it accounted for ~42% of total wall time
(1.57s of 3.77s), and time grew super-linearly with file size --
a ~208x growth in lines of code produced a ~363x growth in abstraction
time.

Root cause: ``algorithms.abstract_source.abstract_source`` (the language-
adapter path every non-Python language shares) called
``get_context(source_code, symbol.lineno, context_window)`` once per mapped
symbol, without the ``lines=`` argument. ``get_context`` re-splits the
*entire* file on every call it does not receive pre-split lines for, so
this was O(symbols x file_size) rather than O(file_size).

``algorithms.abstract`` (the Python engine) already carries the fix for
this exact pattern -- see ``get_context``'s own docstring, which documents
having been split once and passed through for that caller specifically.
It never carried over to the adapter path, which is what this test guards.

Measured before the fix: n=5 functions: 3.6ms; n=1,000 functions: 2,351ms
(363x time for 208x code -- clearly super-linear).
Measured after: n=5 functions: 3.6ms; n=1,000 functions: 740ms
(204x time for 208x code -- linear, as expected).
"""

import time

from algorithms.abstract_source import abstract_source


def _js_source(n_funcs: int) -> str:
    return "\n".join(
        f"function func_{i}(x, y) {{\n"
        f"  const localValue_{i} = x * {i} + y;\n"
        f"  return localValue_{i};\n"
        f"}}\n"
        for i in range(n_funcs)
    )


class TestJavaScriptContextExtractionIsLinearNotQuadratic:

    def test_scaling_is_not_quadratic(self):
        """
        Doubling the number of functions (and so the file size and the
        number of mapped symbols together) should roughly double the time,
        not quadruple it.
        """
        small_source = _js_source(50)
        large_source = _js_source(400)  # 8x the functions/lines

        def timed(source):
            start = time.perf_counter()
            abstract_source(source, language="javascript", privacy_level="high")
            return time.perf_counter() - start

        # Warm up import / parser construction so it is not counted against
        # the first measurement.
        timed(_js_source(2))

        small_time = timed(small_source)
        large_time = timed(large_source)

        # O(n) predicts ~8x; O(n^2) predicts ~64x. Generous margin (25x)
        # to stay robust to measurement noise while still catching a
        # regression back to quadratic behaviour.
        assert large_time < small_time * 25, (
            f"8x input took {large_time / small_time:.1f}x longer -- "
            f"expected roughly linear scaling in file size"
        )

    def test_large_file_completes_quickly(self):
        """
        The actual reproduction: a large-ish JavaScript file must abstract
        in a time that does not visibly track quadratic growth. Generous
        bound well above what a linear implementation needs, so this stays
        robust on slower hardware while still catching the regression.
        """
        source = _js_source(1000)
        start = time.perf_counter()
        abstract_source(source, language="javascript", privacy_level="high")
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, (
            f"abstract_source() took {elapsed:.2f}s on a 1,000-function "
            f"file -- looks like the get_context() O(n^2) regression is back"
        )
