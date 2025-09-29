# Bijective-Shorty: A URL Shortener with TTL and ID Reuse

[![Live Demo](https://img.shields.io/badge/Live_Demo-Online-brightgreen?style=for-the-badge)](https://shortlink-3rab.onrender.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

A simple, high-performance URL shortener built with Python and FastAPI, demonstrating the power of **bijective base-6 numeration**. This project serves as a practical, real-world example of how zero-less number systems can be used to create compact, unambiguous, and predictable short codes.

## ✨ Features

-   **Bijective ID Generation**: Creates the shortest possible URL-safe codes without collisions.
-   **Link Expiration (TTL)**: All links automatically expire after 24 hours to keep the database clean.
-   **ID Reuse**: Efficiently reuses the IDs of expired links to keep new codes short.
-   **Persistent Storage**: Uses a file-based JSON database that persists across server restarts.
-   **Bot Verification**: A simple math challenge protects the service from automated abuse.
-   **Production-Ready**: Includes a health check endpoint and is configured for easy deployment on platforms like Render.

## 🛠️ Tech Stack

!Python
!FastAPI
!JavaScript
!HTML5
!CSS3

## 🚀 Running Locally

1.  **Clone the repository:**
    ```sh
    git clone https://github.com/tripping-alien/shortlink.git
    cd shortlink
    ```

2.  **Set up and run the backend:**
    ```sh
    # From the project root directory
    python -m venv .venv
    # Activate the virtual environment (use .\venv\Scripts\Activate.ps1 on Windows)
    source .venv/bin/activate
    pip install -r requirements.txt
    uvicorn app:app --reload
    ```

3.  **Access the application:**
    -   Open your web browser and navigate to `http://localhost:8000`.

## ☁️ Deployment on Render

This project is configured for easy deployment on a platform like Render.

1.  **Create a new Web Service** on Render and connect it to your GitHub repository.
2.  **Set the Start Command** to:
    ```
    uvicorn app:app --host 0.0.0.0 --port $PORT
    ```
3.  **Add a Persistent Disk** to store the `db.json` file.
    -   **Name**: `data-disk`
    -   **Mount Path**: `/data`
    -   This will automatically create the `RENDER_DISK_PATH` environment variable that the application uses.
4.  **Update the Health Check Path** in your service settings to `/health`.

## License

This project is open source and released under the MIT License.