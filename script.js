document.addEventListener("DOMContentLoaded", () => {
  const shortenBtn = document.getElementById("shortenBtn");
  const inputField = document.getElementById("urlInput");
  const resultBox = document.getElementById("resultBox");
  const resultLink = document.getElementById("resultLink");

  shortenBtn.addEventListener("click", async () => {
    const url = inputField.value.trim();
    if (!url) return;

    shortenBtn.disabled = true;
    shortenBtn.innerHTML = `<span class="spinner"></span> Shortening...`;

    try {
      const response = await fetch("/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url })
      });

      const data = await response.json();

      if (data.short_url) {
        resultBox.classList.remove("d-none");
        resultLink.textContent = data.short_url;
        resultLink.href = data.short_url;
      }
    } catch (err) {
      console.log("Error:", err);
      alert("Server error. Check backend.");
    }

    shortenBtn.disabled = false;
    shortenBtn.textContent = "Shorten";
  });
});
