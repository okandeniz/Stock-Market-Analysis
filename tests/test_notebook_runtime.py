import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import nbformat
import pandas as pd

from app.notebook_runtime import NotebookRuntime


class NotebookRuntimeTests(unittest.TestCase):
    def test_compilation_is_cached_and_global_options_are_restored(self):
        original_float_format = pd.get_option("display.float_format")
        original_filters = list(warnings.filters)

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            root = Path(temp)
            notebook_path = root / "tiny.ipynb"
            notebook = nbformat.v4.new_notebook(
                cells=[
                    nbformat.v4.new_code_cell(
                        "import warnings\n"
                        "import pandas as pd\n"
                        "warnings.filterwarnings('ignore')\n"
                        "pd.set_option('display.float_format', lambda value: 'changed')\n"
                        "VALUE = 42\n"
                    )
                ]
            )
            nbformat.write(notebook, notebook_path)

            NotebookRuntime.clear_compiled_cache()
            with patch("app.notebook_runtime.nbformat.read", wraps=nbformat.read) as reader:
                first = NotebookRuntime(notebook_path, root, root).module()
                second = NotebookRuntime(notebook_path, root, root).module()

            self.assertEqual(first.VALUE, 42)
            self.assertEqual(second.VALUE, 42)
            self.assertEqual(reader.call_count, 1)

        self.assertIs(pd.get_option("display.float_format"), original_float_format)
        self.assertEqual(warnings.filters, original_filters)

    def test_snapshot_attaches_chart_toggle_and_section_metadata(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            root = Path(temp)
            notebook_path = root / "chart.ipynb"
            notebook = nbformat.v4.new_notebook(
                cells=[
                    nbformat.v4.new_code_cell(
                        "import plotly.graph_objects as go\n"
                        "def make_chart():\n"
                        "    show(go.Figure(go.Scatter(y=[1, 2])))\n"
                    )
                ]
            )
            nbformat.write(notebook, notebook_path)
            runtime = NotebookRuntime(notebook_path, root, root)
            module = runtime.module()
            cleanup, snapshot = runtime.with_plotly_saver(request_id="test", prefix="chart")

            module.make_chart()
            snapshot(
                "büyüme",
                {
                    "analysis_section": "income_statement_changes",
                    "analysis_section_title": "Gelir Tablosu Kalemleri",
                    "chart_toggle_group": "income_statement_change_period",
                    "chart_toggle_label": "Yıllıklandırılmış",
                },
            )
            charts = cleanup()

        self.assertEqual(charts[0]["category"], "büyüme")
        meta = charts[0]["figure"]["layout"]["meta"]
        self.assertEqual(meta["analysis_section_title"], "Gelir Tablosu Kalemleri")
        self.assertEqual(meta["chart_toggle_label"], "Yıllıklandırılmış")


if __name__ == "__main__":
    unittest.main()
