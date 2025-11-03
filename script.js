// Theme toggle
const root = document.documentElement;
const themeToggle = document.getElementById("themeToggle");

themeToggle.addEventListener("click", () => {
  const current = root.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  root.setAttribute("data-theme", next);
  themeToggle.textContent = next === "dark" ? "☀️" : "🌙";
});

// Generate shortlink (temporary demo)
const shortenBtn = document.getElementById("shortenBtn");
const urlInput = document.getElementById("urlInput");
const resultContainer = document.getElementById("resultContainer");
const shortCode = document.getElementById("shortCode");
const copyBtn = document.getElementById("copyBtn");

shortenBtn.addEventListener("click", () => {
  let url = urlInput.value.trim();
  if (!url) return;

  // Generate a code
  const code = Math.random().toString(36).substring(2, 8);
  shortCode.textContent = code;
  resultContainer.style.display = "block";
});

// Copy
copyBtn.addEventListener("click", () => {
  navigator.clipboard.writeText(shortCode.textContent);
  copyBtn.textContent = "✅ Copied!";
  setTimeout(() => (copyBtn.textContent = "Copy"), 1500);
});
