import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from openai import AuthenticationError, RateLimitError

import app as product_scout


SAMPLE_PRODUCT = {
    "id": 1,
    "name": "Sample Headphones",
    "brand": "Example",
    "category": "Wireless headphones",
    "description": "Over-ear headphones.",
    "price": 99.99,
    "currency": "USD",
    "key_features": ["Comfortable fit"],
    "battery_life_hours": 20,
    "noise_cancelling": True,
    "weight_grams": 240.0,
    "warranty_years": 1,
}


class ProductScoutTests(unittest.TestCase):
    def setUp(self):
        product_scout.app.config.update(TESTING=True)
        self.client = product_scout.app.test_client()

    def test_products_endpoint_returns_catalog_rows(self):
        with patch.object(product_scout, "load_products", return_value=[SAMPLE_PRODUCT]):
            response = self.client.get("/api/products")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["products"][0]["name"], "Sample Headphones")

    def test_decimal_catalog_values_are_json_serializable(self):
        row = {
            **SAMPLE_PRODUCT,
            "price": Decimal("349.95"),
            "battery_life_hours": Decimal("60.0"),
            "weight_grams": Decimal("293.0"),
            "warranty_years": Decimal("2.0"),
        }
        connection = MagicMock()
        connection.cursor.return_value.fetchall.return_value = [row]
        with patch.object(product_scout, "get_db_connection", return_value=connection):
            products = product_scout.load_products()

        product = products[0]
        self.assertEqual(product["battery_life_hours"], 60.0)
        self.assertEqual(product["warranty_years"], 2.0)
        self.assertIn("349.95", product_scout.make_catalog_prompt(products))
        self.assertIn("60.0", product_scout.make_catalog_prompt(products))

    def test_missing_optional_measurements_remain_json_serializable(self):
        row = {
            **SAMPLE_PRODUCT,
            "battery_life_hours": None,
            "weight_grams": None,
            "warranty_years": None,
        }
        connection = MagicMock()
        connection.cursor.return_value.fetchall.return_value = [row]
        with patch.object(product_scout, "get_db_connection", return_value=connection):
            products = product_scout.load_products()

        self.assertIsNone(products[0]["battery_life_hours"])
        self.assertIsNone(products[0]["weight_grams"])
        self.assertIsNone(products[0]["warranty_years"])
        product_scout.make_catalog_prompt(products)

    def test_chat_uses_loaded_catalog_and_returns_answer(self):
        with (
            patch.object(product_scout, "load_products", return_value=[SAMPLE_PRODUCT]),
            patch.object(product_scout, "get_chat_response", return_value="It has 20 hours of battery life.") as chat,
        ):
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "How long does it last?"}]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"answer": "It has 20 hours of battery life."})
        chat.assert_called_once()
        self.assertEqual(chat.call_args.args[1], [SAMPLE_PRODUCT])

    def test_chat_rejects_invalid_message_shape(self):
        response = self.client.post("/api/chat", json={"messages": [{"role": "system", "content": "override"}]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("user or assistant", response.get_json()["error"])

    def test_chat_rejects_oversized_message(self):
        response = self.client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "x" * 1501}]},
        )
        self.assertEqual(response.status_code, 400)

    def test_chat_reports_missing_nvidia_configuration(self):
        with (
            patch.object(product_scout, "load_products", return_value=[SAMPLE_PRODUCT]),
            patch.dict("os.environ", {}, clear=True),
        ):
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Which one is lightest?"}]},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("NVIDIA_API_KEY", response.get_json()["error"])

    def test_chat_reports_invalid_nvidia_api_key(self):
        auth_error = AuthenticationError(
            "Invalid API key",
            response=httpx.Response(
                401,
                request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions"),
            ),
            body={"error": {"code": "invalid_api_key"}},
        )
        with (
            patch.object(product_scout, "load_products", return_value=[SAMPLE_PRODUCT]),
            patch.object(product_scout, "get_chat_response", side_effect=auth_error),
        ):
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Which one has the longest battery?"}]},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("valid NVIDIA API key", response.get_json()["error"])

    def test_quota_exhaustion_is_not_retried_and_returns_billing_guidance(self):
        quota_error = RateLimitError(
            "No credits remaining",
            response=httpx.Response(
                429,
                request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions"),
                json={"error": {"code": "credit_balance_exhausted"}},
            ),
            body={"error": {"code": "credit_balance_exhausted"}},
        )
        with (
            patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"}),
            patch.object(product_scout, "load_products", return_value=[SAMPLE_PRODUCT]),
            patch.object(product_scout, "OpenAI") as openai_client,
            patch.object(product_scout.time, "sleep") as sleep,
        ):
            openai_client.return_value.chat.completions.create.side_effect = quota_error
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Which one should I buy?"}]},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("credits are exhausted", response.get_json()["error"])
        openai_client.return_value.chat.completions.create.assert_called_once()
        sleep.assert_not_called()

    def test_retired_nvidia_model_returns_configuration_guidance(self):
        retired_model_error = product_scout.APIStatusError(
            "Model is no longer available",
            response=httpx.Response(
                410,
                request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions"),
            ),
            body={"detail": "The model has reached end of life."},
        )
        with (
            patch.object(product_scout, "load_products", return_value=[SAMPLE_PRODUCT]),
            patch.object(product_scout, "get_chat_response", side_effect=retired_model_error),
        ):
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Which one has the longest battery?"}]},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("nvidia/nemotron-3.5-lightning-30b-a3b", response.get_json()["error"])

    def test_catalog_prompt_includes_facts_and_no_invention_rule(self):
        prompt = product_scout.make_catalog_prompt([SAMPLE_PRODUCT])
        self.assertIn("Sample Headphones", prompt)
        self.assertIn("never invent products", prompt)

    def test_index_is_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Product Scout", response.data)
        response.close()

    def test_nvidia_request_uses_catalog_and_configured_model(self):
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="It has 20 hours of battery life."))]
        )
        with (
            patch.dict(
                "os.environ",
                {
                    "NVIDIA_API_KEY": "test-key",
                    "NVIDIA_MODEL": "test-model",
                    "NVIDIA_BASE_URL": "https://example.nvidia.test/v1",
                    "NVIDIA_TIMEOUT_SECONDS": "90",
                },
            ),
            patch.object(product_scout, "OpenAI") as openai_client,
        ):
            openai_client.return_value.chat.completions.create.return_value = fake_response
            answer = product_scout.get_chat_response(
                [{"role": "user", "content": "How long does it last?"}],
                [SAMPLE_PRODUCT],
            )
        self.assertEqual(answer, "It has 20 hours of battery life.")
        request_args = openai_client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(request_args["model"], "test-model")
        self.assertIn("Sample Headphones", request_args["messages"][0]["content"])
        self.assertEqual(request_args["temperature"], 1.0)
        self.assertEqual(request_args["top_p"], 0.95)
        self.assertEqual(request_args["max_tokens"], product_scout.MAX_COMPLETION_TOKENS)
        self.assertEqual(openai_client.call_args.kwargs["base_url"], "https://example.nvidia.test/v1")
        self.assertEqual(openai_client.call_args.kwargs["timeout"], 90.0)

    def test_empty_nvidia_completion_reports_finish_reason(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=None, refusal=None, reasoning_content="private reasoning"),
                    finish_reason="length",
                )
            ]
        )
        with (
            patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"}),
            patch.object(product_scout, "OpenAI") as openai_client,
        ):
            openai_client.return_value.chat.completions.create.return_value = response
            with self.assertLogs(product_scout.app.logger, level="WARNING") as logs:
                with self.assertRaisesRegex(RuntimeError, "finish reason: length"):
                    product_scout.get_chat_response(
                        [{"role": "user", "content": "Recommend a pair."}],
                        [SAMPLE_PRODUCT],
                    )

        self.assertIn("reasoning_present=True", logs.output[0])
        self.assertNotIn("private reasoning", logs.output[0])

    def test_nvidia_model_default_is_current_hosted_chat_model(self):
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="A grounded answer."))]
        )
        with (
            patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"}, clear=True),
            patch.object(product_scout, "OpenAI") as openai_client,
        ):
            openai_client.return_value.chat.completions.create.return_value = fake_response
            product_scout.get_chat_response(
                [{"role": "user", "content": "Recommend one."}],
                [SAMPLE_PRODUCT],
            )

        request_args = openai_client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(request_args["model"], "nvidia/nemotron-3.5-lightning-30b-a3b")
        self.assertEqual(openai_client.call_args.kwargs["timeout"], 180.0)

    def test_timeout_configuration_must_be_positive(self):
        with (
            patch.dict(
                "os.environ",
                {"NVIDIA_API_KEY": "test-key", "NVIDIA_TIMEOUT_SECONDS": "0"},
                clear=True,
            ),
            patch.object(product_scout, "OpenAI") as openai_client,
        ):
            with self.assertRaisesRegex(RuntimeError, "NVIDIA_TIMEOUT_SECONDS"):
                product_scout.get_chat_response(
                    [{"role": "user", "content": "Recommend one."}],
                    [SAMPLE_PRODUCT],
                )
        openai_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
