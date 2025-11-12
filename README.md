# Private, Secure, and Global Shortlinks

[![Live Demo](https://img.shields.io/badge/Live_Demo-Online-brightgreen?style=for-the-badge)](https://shortlinks.art/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Language Coverage](https://img.shields.io/badge/Language_Coverage-11%20Locales-blue.svg?style=for-the-badge)](https://github.com/tripping-alien/shortlink)

A high-performance, secure, and globally scalable URL shortening service built on Python and Google Firestore. It features advanced security measures, enterprise-grade scalability, and automatic localization for 11 languages.

## ✨ Features

* **Global Scalability (Firestore):** Uses Google Firestore for persistent, low-latency, and globally distributed storage, replacing local file-based databases (SQLite).
* **11-Language Support:** The UI automatically detects the user's browser language and supports 11 locales, including English, Spanish, Japanese, Arabic, and Pirate (`arr`).
* **Obfuscated & Secure IDs:** Short codes are cryptographically random (`secrets` module) and secured with unique deletion tokens to prevent unauthorized modification or deletion.
* **Link Management:** Set links to expire (TTL) or manage them via an upcoming user Dashboard.
* **AI Metadata Enrichment:** Fetches metadata (title, description, favicon) and uses an optional **Hugging Face AI integration** for automated content summarization.
* **Security Hardened:** Implements custom FastAPI Middleware for **Content Security Policy (CSP)** and **Strict-Transport-Security (HSTS)** to mitigate XSS and Clickjacking attacks.
* **IP & Domain Filtering:** Includes advanced validation to prevent users from creating links to private IPs (SSRF defense) and known malicious/blocked domains.

## 🛠️ Tech Stack

| Component | Technology | Purpose |
| :--- | :--- | :--- |
| **Backend Framework** | Python / FastAPI | High-performance, asynchronous API and routing. |
| **Database** | Google **Firestore** | Scalable, NoSQL cloud storage for links and analytics. |
| **Security** | **Starlette Middleware** | CSP, Trusted Hosts, Rate Limiting (via `slowapi`). |
| **Metadata / AI** | `httpx`, `BeautifulSoup`, **Hugging Face** | External API calls, HTML parsing, and summarization. |
| **I18N / Flags** | Custom Python Logic | Handles 11 language translations and flag emoji generation. |

## 🚀 Running Locally

This version requires a connection to a Google Firestore instance.

1.  **Clone the repository:**
    ```sh
    git clone [https://github.com/tripping-alien/shortlink.git](https://github.com/tripping-alien/shortlink.git)
    cd shortlink
    ```

2.  **Setup Google Service Account:**
    * Create a Firebase project and enable **Firestore**.
    * Generate a service account key file (`serviceAccountKey.json`).
    * Convert the JSON file contents into a single base64 string to use as an environment variable (recommended for secure deployments).
    ```sh
    cat serviceAccountKey.json | base64
    ```

3.  **Create and activate a virtual environment:**
    ```sh
    python -m venv .venv
    source .venv/bin/activate  # macOS/Linux
    # .\venv\Scripts\activate   # Windows
    ```

4.  **Install dependencies and run the server:**
    ```sh
    pip install -r requirements.txt
    
    # Run the server using environment variables for configuration
    export FIREBASE_CONFIG='<Base64_Encoded_Firebase_Service_Account_JSON>'
    export HUGGINGFACE_API_KEY='<Your_HF_API_Key>'  # Optional, for AI summaries
    export BASE_URL='http://localhost:8000'
    
    python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
    ```

5.  **Access the application:**
    * Open your web browser and navigate to `http://localhost:8000`.

## ☁️ Deployment on Cloud Platforms (Render / Google Cloud)

Deployment requires setting the following variables in your cloud provider's environment configuration.

| Variable | Value | Purpose |
| :--- | :--- | :--- |
| `FIREBASE_CONFIG` | **Base64 Encoded Service Account JSON.** | **CRITICAL:** Database authentication. |
| `BASE_URL` | The public URL (e.g., `https://shortlinks.art`). | Essential for constructing correct short links and SEO tags. |
| `HUGGINGFACE_API_KEY` | Your Hugging Face API Key. | Enables AI summarization feature (Optional). |
| `ENVIRONMENT` | `production` | Enables restricted security headers (HSTS, Trusted Hosts). |

### Start Command (Standard for FastAPI)
* **Build Command**: `pip install -r requirements.txt`
* **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`

## ✍️ Author

* **Andrey Lopukhov** - tripping-alien

## License

This project is open source and released under the MIT License.
