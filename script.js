// Theme toggle
const root = document.documentElement;
const themeToggle = document.getElementById("themeToggle");

themeToggle.addEventListener("click", () => {
  const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
  root.setAttribute("data-theme", next);
  themeToggle.textContent = next === "dark" ? "☀️" : "🌙";
});

// Elements
const shortenBtn = document.getElementById("shortenBtn");
const urlInput = document.getElementById("urlInput");
const customCodeInput = document.getElementById("customCode");
const ttlSelect = document.getElementById("ttl");
const resultContainer = document.getElementById("resultContainer");
const shortUrlDisplay = document.getElementById("shortUrlDisplay");
const copyBtn = document.getElementById("copyBtn");
const errorMsg = document.getElementById("errorMsg");

// Backend base: The backend already serves UI at /ui/... so relative API works
const API_ENDPOINT = "/api/v1/links";

shortenBtn.addEventListener("click", async () => {
  const long_url = urlInput.value.trim();
  const custom_code = customCodeInput.value.trim().toLowerCase() || null;
  const ttl = ttlSelect.value;

  if (!long_url) return;

  errorMsg.style.display = "none";

  const payload = { long_url, custom_code, ttl };

  try {
    const res = await fetch(API_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (!res.ok) {
      errorMsg.textContent = data.detail || "Error creating link";
      errorMsg.style.display = "block";
      return;
    }

    shortUrlDisplay.textContent = data.short_url;
    shortUrlDisplay.href = data.short_url;
    resultContainer.style.display = "block";

  } catch (err) {
    errorMsg.textContent = "Network error — check your connection.";
    errorMsg.style.display = "block";
  }
});

// Copy button
copyBtn.addEventListener("click", () => {
  navigator.clipboard.writeText(shortUrlDisplay.textContent);
  copyBtn.textContent = "✅ Copied!";
  setTimeout(() => (copyBtn.textContent = "Copy"), 1500);
});
