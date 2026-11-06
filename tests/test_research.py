import unittest

from taskvault_research import (
    extract_quantity,
    is_research_request,
    match_product,
    purchase_order_draft,
    quote_draft,
    run_live_research,
    run_research,
)


class ResearchEngineTests(unittest.TestCase):
    def test_matches_products_and_ignores_general_questions(self):
        product = match_product("450 boxes of latex examination gloves")
        self.assertEqual(product["key"], "latex-gloves")
        self.assertTrue(is_research_request("Find suppliers for nitrile gloves."))
        self.assertFalse(is_research_request("What are nitrile gloves used for?"))

    def test_converts_pieces_and_cartons_to_order_units(self):
        product = match_product("nitrile gloves")
        pieces = extract_quantity("5000 gloves", product)
        self.assertEqual(pieces["requested_units"], 50)
        cartons = extract_quantity("4 cartons of nitrile gloves", product)
        self.assertEqual(cartons["requested_units"], 40)

    def test_research_produces_ranked_landed_costs_and_evidence(self):
        result = run_research("Source 500 boxes of nitrile examination gloves, size M.")
        self.assertEqual(result["product"]["key"], "nitrile-gloves")
        self.assertEqual(result["quantity"]["quantity_label"], "500 boxes")
        self.assertEqual(len(result["offers"]), 5)
        self.assertEqual(result["offers"][0]["id"], result["best_value_id"])
        best = next(offer for offer in result["offers"] if offer["id"] == result["best_value_id"])
        self.assertLessEqual(best["landed_cost"], max(offer["landed_cost"] for offer in result["offers"]))
        for index, offer in enumerate(result["offers"], start=1):
            self.assertEqual(offer["rank"], index)
            self.assertTrue(offer["source_url"].startswith("/sources/"))
            self.assertIn("landed_cost", offer)
            self.assertIn("verified", offer)
        self.assertIn("No message was sent", result["summary"])
        self.assertIn("nothing was paid", result["summary"])
        self.assertGreaterEqual(result["verified_count"], 1)

    def test_live_capture_research_uses_extracted_fields_without_invented_ratings(self):
        payload = run_live_research(
            "Source 500 boxes of nitrile examination gloves.",
            {
                "captures": [
                    {
                        "url": "https://example.com/item",
                        "final_url": "https://example.com/item",
                        "host": "example.com",
                        "title": "Example Medical - Nitrile Gloves",
                        "captured_at": "2026-11-06T12:00:00+00:00",
                        "text_excerpt": "Price USD 8.10 per box. MOQ 100. Dispatch in 4 days.",
                        "screenshot_file": "source-01.png",
                        "screenshot_sha256": "a" * 64,
                        "text_sha256": "b" * 64,
                        "blocked_requests": 0,
                        "error": None,
                    }
                ],
                "captured_count": 1,
                "requested_count": 1,
                "error_count": 0,
                "blocked_requests": [],
            },
            sources=["https://example.com/item"],
        )
        self.assertEqual(payload["index"]["version"], "live-capture-v1")
        self.assertEqual(payload["offers"][0]["verification_status"], "captured_unverified")
        self.assertEqual(payload["offers"][0]["rating"], 0)
        self.assertTrue(payload["offers"][0]["price_known"])
        self.assertIn("No message was sent", payload["summary"])

    def test_quote_and_order_drafts_never_claim_external_action(self):
        result = run_research("Source 500 boxes of nitrile gloves.")
        offer = result["offers"][0]
        quote = quote_draft(result, offer, {"ship_to": "Austin, TX", "buyer_name": "Alex"})
        self.assertIn("powder-free nitrile examination gloves", quote["draft"])
        self.assertIn("500 boxes", quote["draft"])
        self.assertNotIn("sent automatically", quote["draft"])
        order = purchase_order_draft(result, offer, 1, {"approval_threshold": 100})
        self.assertGreaterEqual(order["quantity"], offer["moq_units"])
        self.assertEqual(order["supplier"], offer["supplier"])
        self.assertIn("No order has been placed", order["draft"])
        self.assertIn("approval threshold", order["draft"])


if __name__ == "__main__":
    unittest.main()
