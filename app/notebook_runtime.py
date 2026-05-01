from __future__ import annotations

import json
import os
import re
import types
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import nbformat


def _strip_main_guard(code: str) -> str:
    pattern = re.compile(r"^\s*if\s+__name__\s*==\s*[\"']__main__[\"']\s*:\s*$", re.M)
    m = pattern.search(code)
    if not m:
        return code
    return code[: m.start()].rstrip() + "\n"


@dataclass(frozen=True)
class RenderedOutput:
    tables: list[dict[str, str]]
    images: list[dict[str, str]]
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

    def module(self) -> types.ModuleType:
        if self._module is not None:
            return self._module

        nb = nbformat.read(self.notebook_path, as_version=4)
        code_cells: list[str] = []
        for cell in nb.cells:
            if cell.get("cell_type") != "code":
                continue
            src = cell.get("source") or ""
            if isinstance(src, list):
                src = "".join(src)
            if not src.strip():
                continue
            code_cells.append(str(src))

        code = "\n\n".join(code_cells)
        code = _strip_main_guard(code)

        mod = types.ModuleType(self.notebook_path.stem.replace(" ", "_"))
        mod.__file__ = str(self.notebook_path)
        mod.__dict__["__name__"] = "__notebook__"

        # Inject Jupyter builtins that may not be available outside of a kernel.
        try:
            from IPython.display import display as _ipython_display
            mod.__dict__["display"] = _ipython_display
        except ImportError:
            mod.__dict__["display"] = lambda *a, **kw: None  # no-op outside Jupyter

        # Ensure relative file IO resolves from project root (where xlsx/csv live).
        cwd = os.getcwd()
        try:
            os.chdir(self.project_root)
            exec(compile(code, str(self.notebook_path), "exec"), mod.__dict__)
        finally:
            os.chdir(cwd)

        self._module = mod
        return mod

    def with_matplotlib_saver(
        self,
        *,
        request_id: str,
        prefix: str,
    ) -> tuple[Callable[[], list[dict[str, str]]], Callable[[str], None]]:
        """
        Monkeypatches matplotlib.pyplot.show so notebook plot functions can be used
        in a web context.

        Returns (cleanup, snapshot):
          - cleanup()  → saves any remaining open figures, restores plt.show,
                         returns the full list of collected image dicts.
          - snapshot(category) → tags all newly collected images (since the last
                                 snapshot call) with the given category string.
        """

        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt  # noqa: WPS433

        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        collected: list[dict[str, str]] = []
        _snap_idx = [0]
        original_show = plt.show

        def _save_current_figures() -> None:
            fignums = plt.get_fignums()
            for n in fignums:
                fig = plt.figure(n)
                filename = f"{prefix}_{request_id}_{uuid.uuid4().hex[:10]}.png"
                out_path = self.outputs_dir / filename
                fig.savefig(out_path, dpi=140, bbox_inches="tight")
                collected.append(
                    {
                        "name": filename,
                        "url": f"/static/outputs/{filename}",
                    }
                )
            plt.close("all")

        def patched_show(*args: Any, **kwargs: Any) -> None:  # noqa: ANN401
            _save_current_figures()

        plt.show = patched_show

        def snapshot(category: str) -> None:
            """Tag all images captured since the last snapshot with the given category."""
            for img in collected[_snap_idx[0] :]:
                img.setdefault("category", category)
            _snap_idx[0] = len(collected)

        def cleanup() -> list[dict[str, str]]:
            try:
                _save_current_figures()
            finally:
                plt.show = original_show
            # Tag any images not yet tagged (e.g. if a snapshot call was skipped on error)
            for img in collected[_snap_idx[0] :]:
                img.setdefault("category", "diğer")
            return collected

        return cleanup, snapshot
