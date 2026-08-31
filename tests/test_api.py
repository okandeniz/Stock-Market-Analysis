import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.notebook_runtime import RenderedOutput


class ApiValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_options_endpoints(self):
        self.assertEqual(self.client.get("/api/sector/options").status_code, 200)
        company_response = self.client.get("/api/company/options")
        self.assertEqual(company_response.status_code, 200)
        self.assertEqual(company_response.json(), {"degerleme": ["EVET", "HAYIR"]})

    def test_sector_rejects_string_boolean(self):
        response = self.client.post(
            "/api/sector/run",
            json={
                "sektor": "Teknoloji",
                "analiz_turu": "TOPLAM",
                "excel_durum": "HAYIR",
                "piotroski_hesapla": "false",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_sector_rejects_unknown_sector(self):
        response = self.client.post(
            "/api/sector/run",
            json={
                "sektor": "../gecersiz",
                "analiz_turu": "TOPLAM",
                "excel_durum": "EVET",
                "piotroski_hesapla": False,
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_company_valuation_uses_rule_based_api_contract(self):
        output = RenderedOutput(tables=[], charts=[], meta={"degerleme": "EVET"})
        with patch("app.main.run_company_analysis", return_value=output) as run_analysis:
            response = self.client.post(
                "/api/company/run",
                json={
                    "hisse": "THYAO",
                    "degerleme": "EVET",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("tufe_kullan", run_analysis.call_args.kwargs)
        self.assertNotIn("evds_api_key", run_analysis.call_args.kwargs)
        self.assertNotIn("required_return_pct", run_analysis.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
