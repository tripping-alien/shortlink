# Bijective-Shorty: A URL Shortener with TTL and ID Reuse

A simple, high-performance URL shortener built with Python, FastAPI, and the mathematical concept of bijective base-6 numeration. This project serves as a practical, real-world example of how zero-less number systems can be used to create compact, unambiguous, and predictable short codes.

This version includes advanced features like a Time-To-Live (TTL) for all links and a mechanism to reuse the IDs of expired links, ensuring the service remains efficient and short codes stay as short as possible over time.

## How It Works

The core of this project is the bijective base-6 system combined with a smart ID management strategy:

1.  **ID Pool:** The system maintains a pool of IDs from links that have expired.
2.  **ID Assignment:** When a new URL is submitted, the system first attempts to assign it an ID from the reusable pool. If the pool is empty, it generates a new, auto-incrementing ID.
3.  **TTL:** Every new link is created with a 24-hour Time-To-Live (TTL).
4.  **Bijective Conversion:** The assigned integer ID is converted into its bijective base-6 representation (e.g., ID `7` becomes `11`, ID `43` becomes `111`). This becomes the short URL path.
5.  **Expiration Check:** When a short link is accessed, the system checks if it has expired. If it has, the link is deleted, its ID is returned to the reusable pool, and the user is shown an error.

This method guarantees no collisions, keeps codes short, and manages resources effectively.

## Tech Stack

-   **Backend**: Python 3.8+ with FastAPI
-   **Frontend**: Vanilla HTML, CSS, and JavaScript
-   **Server**: Uvicorn

## Running Locally

1.  **Clone the repository:**
    