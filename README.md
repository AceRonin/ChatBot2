# Product Scout

Product Scout is a small shopping assistant for comparing wireless headphones. Flask serves the responsive browser interface and JSON APIs; product facts are read from MySQL for both the catalog and every chat request. Chat completions use NVIDIA's hosted, OpenAI-compatible API through the server-side `NVIDIA_API_KEY`.

## Requirements

- Python 3.10 or newer
- MySQL 8.0+ (or XAMPP MySQL/MariaDB with JSON support)
- An NVIDIA API key for the hosted model API

## Setup

1. Start MySQL in XAMPP.
2. Create the database and load the sample catalog:

   ```powershell
   Get-Content .\schema.sql | & "C:\xampp\mysql\bin\mysql.exe" -u root
   ```

   Adjust the XAMPP path if needed. If `mysql` is already on `PATH`, you can use `Get-Content .\schema.sql | mysql -u root` or import `schema.sql` through phpMyAdmin.
3. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
4. Set server environment variables in PowerShell. The database defaults match a typical local XAMPP setup; override them if needed:

   ```powershell
   $env:MYSQL_HOST = "127.0.0.1"
   $env:MYSQL_PORT = "3306"
   $env:MYSQL_USER = "root"
   $env:MYSQL_PASSWORD = ""
   $env:MYSQL_DATABASE = "product_scout"
   $env:NVIDIA_API_KEY = "your-NVIDIA-API-key"
   $env:NVIDIA_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
   $env:NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
   $env:NVIDIA_TIMEOUT_SECONDS = "180"
   ```

   `.env.example` lists the supported settings. The application reads environment variables directly and does not load a local `.env` file.
5. Run the app:

   ```powershell
   py app.py
   ```

6. Open <http://127.0.0.1:5000>.

## API

- `GET /api/products` — product catalog from MySQL.
- `POST /api/chat` — accepts `{"messages":[{"role":"user","content":"..."}]}` and returns `{"answer":"..."}`. Include recent `user`/`assistant` messages for conversational context. Messages are limited to 12 entries and 1,500 characters each; request bodies are limited to 24 KiB.

Catalog/database failures return HTTP 503; invalid chat requests return HTTP 400; oversized requests return HTTP 413. Chat requires `NVIDIA_API_KEY`. NVIDIA requests use a 180-second timeout by default, configurable with `NVIDIA_TIMEOUT_SECONDS`. Temporary NVIDIA API connection, timeout, rate-limit, and server errors are retried twice; exhausted quota is reported without retries.

## Product facts and grounding

`schema.sql` creates the `products` table and inserts four sample products. The catalog fields include product name, brand, category, description, price/currency, key features, battery life, noise-cancelling capability, weight, and warranty. Each chat request loads current catalog rows from MySQL and supplies them as the product-facts source. The system prompt instructs the assistant to state when a product or detail is not listed rather than invent it.

## Checks

Run the focused backend tests with:

```powershell
py -m unittest discover -s tests
```

The app needs a running MySQL instance and an NVIDIA API key with hosted-model access for the live end-to-end flow. The NVIDIA API key is only used by the Python backend and must never be put in frontend files.
