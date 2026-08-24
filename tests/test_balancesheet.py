import unittest
from unittest.mock import Mock, patch

import pandas as pd

import balancesheet


class _Response:
    text = """
    <select id="ddlMaliTabloFirst">
      <option>2026/3</option><option>2025/12</option><option>2025/9</option>
      <option>2025/6</option><option>2025/3</option>
    </select>
    <select id="ddlMaliTabloGroup"><option value="XI_29">Grup</option></select>
    """


def _fake_values(_url, _params):
    return [
        {
            "itemCode": "A",
            "itemDescTr": "Net Faaliyet Kar/Zararı",
            "itemDescEng": "Operating profit",
            "value1": 1,
            "value2": 2,
            "value3": 3,
            "value4": 4,
        },
        {
            "itemCode": "B",
            "itemDescTr": "Amortisman Giderleri",
            "itemDescEng": "Depreciation",
            "value1": 10,
            "value2": 20,
            "value3": 30,
            "value4": 40,
        },
    ]


def _fake_values_with_missing(_url, _params):
    values = _fake_values(_url, _params)
    values[1]["value1"] = None
    return values


class BalanceSheetTests(unittest.TestCase):
    def tearDown(self):
        balancesheet.clear_http_cache()

    def test_json_requests_reuse_short_lived_cache(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"value": [{"itemDescTr": "Satış Gelirleri"}]}
        session = Mock()
        session.get.return_value = response

        with patch.object(balancesheet, "_session", return_value=session):
            first = balancesheet._get_json_with_retry(
                "https://example.test/data", (("companyCode", "TEST"),), retries=1
            )
            first[0]["itemDescTr"] = "değiştirildi"
            second = balancesheet._get_json_with_retry(
                "https://example.test/data", (("companyCode", "TEST"),), retries=1
            )

        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(second[0]["itemDescTr"], "Satış Gelirleri")

    @patch.object(balancesheet, "_get_json_with_retry", side_effect=_fake_values)
    @patch.object(balancesheet, "_get_with_retry", return_value=_Response())
    def test_history_does_not_require_a_hardcoded_march_period(self, _get, _get_json):
        result = balancesheet.bilanco_cekme(["TEST"])
        self.assertEqual(result.index.min(), pd.Timestamp("2025-06-01"))
        self.assertEqual(result.index.max(), pd.Timestamp("2026-03-01"))
        self.assertEqual(result.loc[pd.Timestamp("2026-03-01"), "FAVÖK"], 11)

    def test_multiple_symbols_are_rejected_instead_of_silently_returning_last(self):
        with self.assertRaises(ValueError):
            balancesheet.bilanco_cekme(["AAA", "BBB"])

    @patch.object(balancesheet, "_get_json_with_retry", side_effect=_fake_values_with_missing)
    @patch.object(balancesheet, "_get_with_retry", return_value=_Response())
    def test_missing_source_value_is_preserved_instead_of_becoming_zero(self, _get, _get_json):
        result = balancesheet.bilanco_cekme(["TEST"])

        self.assertTrue(pd.isna(result.loc[pd.Timestamp("2026-03-01"), "Amortisman Giderleri"]))
        self.assertTrue(pd.isna(result.loc[pd.Timestamp("2026-03-01"), "FAVÖK"]))


if __name__ == "__main__":
    unittest.main()
