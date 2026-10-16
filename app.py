import json
import math
import os
import time
from typing import Any

import mysql.connector
from flask import Flask, jsonify, request, send_from_directory
from mysql.connector import Error as MySQLError
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_REQUEST_BYTES = 24 * 1024
MAX_MESSAGES = 12
MAX_MESSAGE_LENGTH = 1500
MAX_COMPLETION_TOKENS = 2048
def is_nvidia_quota_exhausted(error: RateLimitError) -> bool:
    body = error.body
    if not isinstance(body, dict):
        return False
    details = body.get("error")
    return isinstance(details, dict) and details.get("code") in {
        "credit_balance_exhausted",
        "insufficient_quota",
    }


app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "product_scout"),
        connection_timeout=5,
    )


def load_products() -> list[dict[str, Any]]:
    connection = get_db_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT id, name, brand, category, description, price, currency,
                       key_features, battery_life_hours, noise_cancelling,
                       weight_grams, warranty_years
                FROM products
                ORDER BY brand, name
                """
            )
            rows = cursor.fetchall()
        finally:
            cursor.close()
    finally:
        connection.close()

    products = []
    for row in rows:
        features = row["key_features"]
        if isinstance(features, str):
            features = json.loads(features)
        products.append(
            {
                "id": row["id"],
                "name": row["name"],
                "brand": row["brand"],
                "category": row["category"],
                "description": row["description"],
                "price": float(row["price"]),
                "currency": row["currency"],
                "key_features": features,
                "battery_life_hours": (
                    float(row["battery_life_hours"])
                    if row["battery_life_hours"] is not None
                    else None
                ),
                "noise_cancelling": bool(row["noise_cancelling"]),
                "weight_grams": (
                    float(row["weight_grams"]) if row["weight_grams"] is not None else None
                ),
                "warranty_years": (
                    float(row["warranty_years"])
                    if row["warranty_years"] is not None
                    else None
                ),
            }
        )
    return products


def validate_messages(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
        raise ValueError("Send a JSON object containing a messages array.")

    messages = payload["messages"]
    if not messages or len(messages) > MAX_MESSAGES:
        raise ValueError(f"Send between 1 and {MAX_MESSAGES} messages.")

    validated = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in ("user", "assistant"):
            raise ValueError("Each message must have a user or assistant role.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Messages must contain non-empty text.")
        if len(content) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Messages must be no longer than {MAX_MESSAGE_LENGTH} characters.")
        validated.append({"role": message["role"], "content": content.strip()})

    if validated[-1]["role"] != "user":
        raise ValueError("The most recent message must be from the user.")
    return validated


def make_catalog_prompt(products: list[dict[str, Any]]) -> str:
    catalog = json.dumps(products, ensure_ascii=False, separators=(",", ":"))
    return (
        "You are Product Scout, a shopping assistant. Answer using only the product "
        "catalog JSON below. Treat the catalog as the complete and exclusive source "
        "of product facts: never invent products, prices, availability, or specifications. "
        "If a product or detail is absent, say it is not listed in the catalog. "
        "When comparing products, explain meaningful trade-offs grounded in their listed "
        "facts. Be concise and normally keep recommendations under 120 words. "
        "Connect recommendations to the user's stated needs, and ask a concise "
        "follow-up if their needs are unclear. You may use conversation history to "
        "understand preferences, but not as a source of product facts.\n\n"
        f"Catalog JSON:\n{catalog}"
    )


def create_nvidia_client() -> tuple[OpenAI, str]:
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("Chat is not configured: set NVIDIA_API_KEY on the server.")

    model = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
    base_url = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    try:
        timeout_seconds = float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "180"))
    except ValueError as error:
        raise RuntimeError("NVIDIA_TIMEOUT_SECONDS must be a positive number.") from error
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise RuntimeError("NVIDIA_TIMEOUT_SECONDS must be a positive number.")

    return (
        OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
            timeout=timeout_seconds,
        ),
        model,
    )


def make_chat_request_messages(
    messages: list[dict[str, str]], products: list[dict[str, Any]]
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": make_catalog_prompt(products)},
        *messages,
    ]


def get_chat_response(messages: list[dict[str, str]], products: list[dict[str, Any]]) -> str:
    client, model = create_nvidia_client()
    request_messages = make_chat_request_messages(messages, products)

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=request_messages,
                temperature=1.0,
                top_p=0.95,
                max_tokens=MAX_COMPLETION_TOKENS,
            )
            if not response.choices:
                app.logger.warning("NVIDIA completion contained no choices")
                raise RuntimeError("The chat service returned an invalid response.")
            choice = response.choices[0]
            message = choice.message
            answer = message.content
            if not answer or not answer.strip():
                app.logger.warning(
                    "NVIDIA completion had no visible answer (finish_reason=%s, "
                    "refusal_present=%s, reasoning_present=%s)",
                    choice.finish_reason,
                    bool(getattr(message, "refusal", None)),
                    bool(getattr(message, "reasoning_content", None)),
                )
                raise RuntimeError(
                    "NVIDIA returned no visible answer"
                    f" (finish reason: {choice.finish_reason or 'unknown'}). "
                    "Please try again or select another active NVIDIA model."
                )
            return answer.strip()
        except RateLimitError as error:
            if is_nvidia_quota_exhausted(error) or attempt == 2:
                raise
            time.sleep(0.5 * (2**attempt))
        except (APIConnectionError, APITimeoutError, InternalServerError):
            if attempt == 2:
                raise
            time.sleep(0.5 * (2**attempt))
        except APIStatusError:
            raise
    raise RuntimeError("The chat service could not complete the request.")


def nvidia_error_message(error: Exception) -> tuple[str, int]:
    if isinstance(error, RuntimeError):
        return str(error), 503
    if isinstance(error, RateLimitError):
        if is_nvidia_quota_exhausted(error):
            return (
                "NVIDIA API quota or credits are exhausted. Check the NVIDIA API key's "
                "usage limits and billing, then try again.",
                503,
            )
        return "The chat service is temporarily unavailable. Please try again.", 502
    if isinstance(error, APITimeoutError):
        return (
            "The NVIDIA model took too long to respond. Please try again, or increase "
            "NVIDIA_TIMEOUT_SECONDS on the server.",
            504,
        )
    if isinstance(error, (APIConnectionError, InternalServerError)):
        return "The chat service is temporarily unavailable. Please try again.", 502
    if isinstance(error, AuthenticationError):
        return (
            "NVIDIA API authentication failed. Set NVIDIA_API_KEY to a valid NVIDIA API key "
            "and restart the server.",
            503,
        )
    if isinstance(error, APIStatusError) and error.status_code == 410:
        return (
            "The configured NVIDIA model is no longer available. Set NVIDIA_MODEL to "
            "an active NVIDIA hosted model, such as "
            "'nvidia/nemotron-3.5-lightning-30b-a3b', then restart the server.",
            503,
        )
    return "The chat service could not process the request. Please try again later.", 502


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/api/products")
def products_endpoint():
    try:
        return jsonify({"products": load_products()})
    except (MySQLError, ValueError, TypeError) as error:
        app.logger.exception("Unable to load product catalog")
        return jsonify({"error": f"Product catalog unavailable: {error}"}), 503


@app.post("/api/chat")
def chat_endpoint():
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json."}), 415
    try:
        messages = validate_messages(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    try:
        products = load_products()
    except (MySQLError, ValueError, TypeError) as error:
        app.logger.exception("Unable to load catalog for chat")
        return jsonify({"error": f"Product catalog unavailable: {error}"}), 503
    if not products:
        return jsonify({"error": "The product catalog is empty; chat is unavailable."}), 503

    try:
        answer = get_chat_response(messages, products)
        return jsonify({"answer": answer})
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 503
    except (APIConnectionError, APITimeoutError, APIStatusError) as error:
        message, status = nvidia_error_message(error)
        if isinstance(error, AuthenticationError):
            app.logger.error("NVIDIA API authentication failed; check NVIDIA_API_KEY")
        elif is_nvidia_quota_exhausted(error):
            app.logger.error("NVIDIA API quota is exhausted; check account usage and billing")
        else:
            app.logger.exception("NVIDIA chat request failed after rate-limit retries")
        return jsonify({"error": message}), status

@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"error": "Request is too large. Please shorten your message."}), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
