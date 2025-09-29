document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('shorten-form');
    const longUrlInput = document.getElementById('long-url-input');
    const resultBox = document.getElementById('result-box');
    const shortUrlLink = document.getElementById('short-url-link');

    const verificationGroup = document.getElementById('verification-group');
    const verificationLabel = document.getElementById('verification-label');
    const verificationInput = document.getElementById('verification-input');
    let currentChallenge = {};

    // Configure the API endpoints
    const API_ENDPOINT = '/shorten'; // Use relative path
    const CHALLENGE_ENDPOINT = '/challenge';

    // Fetch initial challenge on page load
    async function getNewChallenge() {
        try {
            const response = await fetch(CHALLENGE_ENDPOINT);
            currentChallenge = await response.json();
            verificationLabel.textContent = currentChallenge.question;
            verificationGroup.style.display = 'block';
        } catch (error) {
            console.error('Failed to fetch verification challenge:', error);
        }
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const longUrl = longUrlInput.value;
        const verificationAnswer = parseInt(verificationInput.value, 10);

        try {
            const response = await fetch(API_ENDPOINT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    long_url: longUrl,
                    challenge_answer: verificationAnswer,
                    num1: currentChallenge.num1, // Send challenge numbers for stateless verification
                    num2: currentChallenge.num2
                }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to create short link.');
            }

            const data = await response.json();
            shortUrlLink.href = data.short_url;
            shortUrlLink.textContent = data.short_url;
            resultBox.style.display = 'block';

            // Get a new challenge for the next submission
            verificationInput.value = '';
            getNewChallenge();
        } catch (error) {
            console.error('Error:', error);
            alert(`An error occurred: ${error.message}`);
        }
    });

    getNewChallenge();
});