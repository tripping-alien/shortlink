document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('shorten-form');
    const longUrlInput = document.getElementById('long-url-input');
    const resultBox = document.getElementById('result-box');
    const shortUrlLink = document.getElementById('short-url-link');

    // Configure the API endpoint
    const API_ENDPOINT = '/shorten'; // Use relative path

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const longUrl = longUrlInput.value;

        try {
            const response = await fetch(API_ENDPOINT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ long_url: longUrl }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to create short link.');
            }

            const data = await response.json();
            shortUrlLink.href = data.short_url;
            shortUrlLink.textContent = data.short_url;
            resultBox.style.display = 'block';
        } catch (error) {
            console.error('Error:', error);
            alert(`An error occurred: ${error.message}`);
        }
    });
});