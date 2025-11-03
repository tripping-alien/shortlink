<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Shortlinks.art - URL Shortener</title>

<!-- Google SEO -->
<meta name="description" content="Fast and simple URL shortener. Generate short links instantly.">
<meta name="keywords" content="shorten url, link shortener, short links, fast links">
<meta name="author" content="Shortlinks.art">
<link rel="canonical" href="https://shortlinks.art/">

<!-- Adsense Auto Ads -->
<script data-ad-client="pub-6170587092427912" async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"></script>

<style>
  :root {
    --primary-color: #4f46e5;
    --secondary-color: #6366f1;
    --accent-color: #facc15;
    --bg-color: #f3f4f6;
    --text-color: #111827;
    --button-color: var(--primary-color);
    --button-hover: var(--secondary-color);
  }

  body {
    margin: 0;
    font-family: Arial, sans-serif;
    background: var(--bg-color);
    color: var(--text-color);
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
  }

  .container {
    background: #fff;
    padding: 2rem;
    border-radius: 12px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.1);
    width: 100%;
    max-width: 480px;
    text-align: center;
  }

  h1 {
    color: var(--primary-color);
  }

  input, select {
    padding: 0.8rem;
    width: 100%;
    margin: 0.5rem 0;
    border-radius: 8px;
    border: 1px solid #d1d5db;
    font-size: 1rem;
  }

  button {
    background: var(--button-color);
    color: white;
    border: none;
    padding: 0.8rem 1.5rem;
    font-size: 1rem;
    border-radius: 8px;
    cursor: pointer;
    margin-top: 0.5rem;
  }

  button:hover {
    background: var(--button-hover);
  }

  .short-link {
    margin-top: 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.6rem;
    background: #f9fafb;
    border-radius: 8px;
  }

  .short-link span {
    overflow-wrap: anywhere;
  }

  .copy-btn {
    background: var(--accent-color);
    border: none;
    padding: 0.5rem 0.8rem;
    border-radius: 6px;
    cursor: pointer;
    color: #111827;
  }
</style>
</head>
<body>

<div class="container">
  <h1>Shortlinks.art</h1>
  <input type="url" id="longUrl" placeholder="Enter your URL here">
  <select id="ttl">
    <option value="1h">1 Hour</option>
    <option value="24h" selected>24 Hours</option>
    <option value="1w">1 Week</option>
    <option value="never">Never</option>
  </select>
  <input type="text" id="customCode" placeholder="Custom code (optional)">
  <button id="shortenBtn">Shorten</button>

  <div id="result" style="display:none;">
    <div class="short-link">
      <span id="shortUrl"></span>
      <button class="copy-btn" id="copyBtn">Copy</button>
    </div>
  </div>
</div>

<script>
const shortenBtn = document.getElementById("shortenBtn");
const resultDiv = document.getElementById("result");
const shortUrlSpan = document.getElementById("shortUrl");
const copyBtn = document.getElementById("copyBtn");

shortenBtn.addEventListener("click", async () => {
    const longUrl = document.getElementById("longUrl").value.trim();
    const ttl = document.getElementById("ttl").value;
    const customCode = document.getElementById("customCode").value.trim() || undefined;

    if (!longUrl) {
        alert("Please enter a URL.");
        return;
    }

    try {
        const res = await fetch("/api/v1/links", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({long_url: longUrl, ttl: ttl, custom_code: customCode})
        });
        const data = await res.json();
        if (res.ok) {
            shortUrlSpan.textContent = data.short_url;
            resultDiv.style.display = "block";
        } else {
            alert(data.detail || "Error creating short link");
        }
    } catch (err) {
        console.error(err);
        alert("Failed to connect to the server. Try again later.");
    }
});

copyBtn.addEventListener("click", () => {
    navigator.clipboard.writeText(shortUrlSpan.textContent)
      .then(() => alert("Copied!"))
      .catch(() => alert("Failed to copy."));
});
</script>

</body>
</html>
