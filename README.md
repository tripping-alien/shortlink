# Bijective-Shorty: A Modern URL Shortener

[![Live Demo](https://img.shields.io/badge/Live_Demo-Online-brightgreen?style=for-the-badge)](https://shortlinks.art/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

A simple, high-performance URL shortener built with Python and FastAPI. It uses the **Hashids** library to generate short, non-sequential, and unique codes from database IDs, providing a clean and secure way to shorten links.

## ✨ Features

-   **Obfuscated & Reversible IDs**: Uses the Hashids library to convert sequential database IDs into short, non-sequential, and URL-safe codes.
-   **Link Expiration (TTL)**: Set links to expire after a specific duration (1 hour, 24 hours, 1 week) or never.
-   **Link Previews**: Enhances user security by providing a preview page (`/get/<hash>`) to show the destination URL before redirecting.
-   **Persistent & Scalable Storage**: Uses a file-based **SQLite** database that persists across server restarts.
-   **Privacy-Focused**: No tracking or analytics. Just simple, fast redirects.
-   **Automatic Internationalization**: The UI automatically detects the user's browser language and displays one of 9 supported languages.
-   **Production-Ready**: Includes a health check endpoint and is configured for easy deployment on platforms like Render.

## 🛠️ Tech Stack

!Python
!FastAPI
!SQLite
!JavaScript
!HTML5
!CSS3

## 🚀 Running Locally

1.  **Clone the repository:**
    ```sh
    git clone https://github.com/tripping-alien/shortlink.git
    cd shortlink
    ```

2.  **Create and activate a virtual environment:**
    ```sh
    python -m venv .venv
    # On macOS/Linux:
    source .venv/bin/activate
    # On Windows (Command Prompt/PowerShell):
    .\.venv\Scripts\activate
    ```

3.  **Install dependencies and run the server:**
    ```sh
    pip install -r requirements.txt
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload
    ```

4.  **Access the application:**
    -   Open your web browser and navigate to `http://localhost:8000`.

## ☁️ Deployment on Render

This project is configured for easy deployment on a platform like Render.

1.  **Create a new Web Service** on Render and connect it to your GitHub repository.
2.  **Set the Start Command** to:
    ```
    uvicorn app:app --host 0.0.0.0 --port $PORT
    ```
3.  **Add Environment Variables**:
    -   `PYTHON_VERSION`: `3.11` (or your desired Python version).
    -   `HASHIDS_SALT`: A long, random, and secret string. This is **critical** for security. You can generate one locally using `python -c "import secrets; print(secrets.token_hex(32))"`.
    -   `BASE_URL`: The public URL of your web service (e.g., `https://shortlinks.art`).
4.  **Add a Persistent Disk** to store the `shortlinks.db` file.
    -   **Name**: `data-disk`
    -   **Mount Path**: `/var/data`
    -   The application is configured to use the `RENDER_DISK_PATH` environment variable, which Render automatically sets to this mount path.
5.  **Update the Health Check Path** in your service settings to `/health`.

## ✍️ Author

-   **Andrey Lopukhov** - tripping-alien

## License

This project is open source and released under the MIT License.