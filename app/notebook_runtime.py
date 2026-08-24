from __future__ import annotations

import re
import sys
import threading
import types
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import nbformat
import pandas as pd


_MODULE_EXEC_LOCK = threading.RLock()
_COMPILED_NOTEBOOK_CACHE: dict[tuple[str, int, int], types.CodeType] = {}


def _strip_main_guard(code: str) -> str:
    pattern = re.compile(r"^\s*if\s+__name__\s*==\s*[\"']__main__[\"']\s*:\s*$", re.M)
    m = pattern.search(code)
    if not m:
        return code
    return code[: m.start()].rstrip() + "\n"


@dataclass(frozen=True)
class RenderedOutput:
    tables: list[dict[str, str]]
    charts: list[dict[str, Any]]
    meta: dict[str, Any]


class NotebookRuntime:
    """
    Loads a .ipynb file and executes its code cells in an isolated module namespace.
    """

    def __init__(self, notebook_path: Path, project_root: Path, outputs_dir: Path):
        self.notebook_path = notebook_path
        self.project_root = project_root
        self.outputs_dir = outputs_dir
        self._module: types.ModuleType | None = None

    @classmethod
    def clear_compiled_cache(cls) -> None:
        """Clear the process-local notebook code cache (primarily for tests/reload)."""
        with _MODULE_EXEC_LOCK:
            _COMPILED_NOTEBOOK_CACHE.clear()

    def _compiled_code(self) -> types.CodeType:
        resolved = self.notebook_path.resolve()
        stat = resolved.stat()
        cache_key = (str(resolved), stat.st_mtime_ns, stat.st_size)
        with _MODULE_EXEC_LOCK:
            cached = _COMPILED_NOTEBOOK_CACHE.get(cache_key)
            if cached is not None:
                return cached

            nb = nbformat.read(resolved, as_version=4)
            code_cells: list[str] = []
            for cell in nb.cells:
                if cell.get("cell_type") != "code":
                    continue
                src = cell.get("source") or ""
                if isinstance(src, list):
                    src = "".join(src)
                if src.strip():
                    code_cells.append(str(src))

            code = _strip_main_guard("\n\n".join(code_cells))
            compiled = compile(code, str(resolved), "exec")
            # Keep only the newest version of a given notebook path.
            for old_key in [key for key in _COMPILED_NOTEBOOK_CACHE if key[0] == str(resolved)]:
                _COMPILED_NOTEBOOK_CACHE.pop(old_key, None)
            _COMPILED_NOTEBOOK_CACHE[cache_key] = compiled
            return compiled

    def module(self) -> types.ModuleType:
        if self._module is not None:
            return self._module

        compiled_code = self._compiled_code()

        mod = types.ModuleType(self.notebook_path.stem.replace(" ", "_"))
        mod.__file__ = str(self.notebook_path)
        mod.__dict__["__name__"] = "__notebook__"

        # Imports inside notebooks need the project root, but changing the
        # process-wide working directory is unsafe while FastAPI handles
        # concurrent requests. Keep the global-path mutation short and locked;
        # also restore warning and pandas display options changed at top level.
        project_root_text = str(self.project_root)
        with _MODULE_EXEC_LOCK, warnings.catch_warnings(), pd.option_context(
            "display.float_format",
            pd.get_option("display.float_format"),
            "display.max_columns",
            pd.get_option("display.max_columns"),
        ):
            # Importing IPython can itself install warning filters, so keep the
            # import inside the same warning-restoration boundary as notebook exec.
            try:
                from IPython.display import display as _ipython_display

                mod.__dict__["display"] = _ipython_display
            except ImportError:
                mod.__dict__["display"] = lambda *a, **kw: None

            path_added = project_root_text not in sys.path
            if path_added:
                sys.path.insert(0, project_root_text)
            try:
                exec(compiled_code, mod.__dict__)
            finally:
                if path_added:
                    try:
                        sys.path.remove(project_root_text)
                    except ValueError:
                        pass

        self._module = mod
        return mod

    def with_plotly_saver(
        self,
        *,
        request_id: str,
        prefix: str,
    ) -> tuple[
        Callable[[], list[dict[str, Any]]],
        Callable[[str, dict[str, Any] | None], None],
    ]:
        """
        Monkeypatches the notebook module's `show(fig)` helper so Plotly figures
        produced by notebook plot functions are captured as JSON-safe dicts
        instead of being opened in a browser tab.

        Notebook plot functions are expected to call `show(fig)` (a plain
        module-level function, injected by the notebook itself and defaulting
        to `fig.show()`) instead of `fig.show()` directly, so this method can
        intercept it.

        Returns (cleanup, snapshot):
          - cleanup()  → restores the original `show`, returns the full list
                         of collected chart dicts.
          - snapshot(category) → tags all newly collected charts (since the
                                 last snapshot call) with the given category.
        """

        from .plotly_theme import to_json_safe

        mod = self.module()
        collected: list[dict[str, Any]] = []
        _snap_idx = [0]
        original_show = mod.__dict__.get("show")

        def captured_show(fig: Any, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
            fig_json = to_json_safe(fig)
            collected.append(
                {
                    "name": f"{prefix}_{request_id}_{uuid.uuid4().hex[:10]}",
                    "figure": fig_json,
                }
            )

        mod.__dict__["show"] = captured_show

        def snapshot(category: str, chart_meta: dict[str, Any] | None = None) -> None:
            """Tag newly captured charts and optionally attach UI metadata."""
            for chart in collected[_snap_idx[0] :]:
                chart.setdefault("category", category)
                if chart_meta:
                    layout = chart.setdefault("figure", {}).setdefault("layout", {})
                    existing_meta = layout.get("meta")
                    if not isinstance(existing_meta, dict):
                        existing_meta = {}
                    layout["meta"] = {**existing_meta, **chart_meta}
            _snap_idx[0] = len(collected)

        def cleanup() -> list[dict[str, Any]]:
            if original_show is not None:
                mod.__dict__["show"] = original_show
            else:
                mod.__dict__.pop("show", None)
            # Tag any charts not yet tagged (e.g. if a snapshot call was skipped on error)
            for chart in collected[_snap_idx[0] :]:
                chart.setdefault("category", "diğer")
            return collected

        return cleanup, snapshot
