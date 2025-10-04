document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('shorten-form');
    const longUrlInput = document.getElementById('long-url-input');
    const resultBox = document.getElementById('result-box');
    const shortUrlLink = document.getElementById('short-url-link');
    const submitButton = document.getElementById('submit-button');
    const buttonText = submitButton.querySelector('.button-text');
    const spinner = submitButton.querySelector('.spinner');

    const verificationLabel = document.getElementById('verification-label');
    const verificationInput = document.getElementById('verification-input');
    const ttlSelect = document.getElementById('ttl-select');
    const ttlInfoText = document.getElementById('ttl-info-text');
    let currentChallenge = {};

    // Configure the API endpoints
    const API_ENDPOINT = '/shorten'; // Use relative path
    const CHALLENGE_ENDPOINT = '/challenge';

    // --- UI State Management ---
    function setLoading(isLoading) {
        if (isLoading) {
            submitButton.disabled = true;
            buttonText.style.display = 'none';
            spinner.style.display = 'inline-block';
        } else {
            submitButton.disabled = false;
            buttonText.style.display = 'inline-block';
            spinner.style.display = 'none';
        }
    }

    // Fetch initial challenge on page load
    async function getNewChallenge() {
        try {
            const response = await fetch(CHALLENGE_ENDPOINT);
            currentChallenge = await response.json();
            verificationLabel.textContent = currentChallenge.question;
            verificationLabel.style.display = 'block';
            verificationInput.style.display = 'block';
        } catch (error) {
            console.error('Failed to fetch verification challenge:', error);
        }
    }

    // --- Dynamic UI Updates ---
    function updateTtlInfo() {
        const selectedOption = ttlSelect.options[ttlSelect.selectedIndex];
        const selectedText = selectedOption.textContent;

        if (selectedOption.value === 'never') {
            ttlInfoText.textContent = `Link will be permanent and will not expire.`;
        } else {
            ttlInfoText.textContent = `Link is private and will automatically expire in ${selectedText}.`;
        }
    }

    ttlSelect.addEventListener('change', updateTtlInfo);

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const longUrl = longUrlInput.value;
        const verificationAnswer = parseInt(verificationInput.value, 10);
        const selectedTtl = ttlSelect.value;

        setLoading(true);

        try {
            const response = await fetch(API_ENDPOINT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    long_url: longUrl,
                    challenge_answer: verificationAnswer,
                    num1: currentChallenge.num1, // Send challenge numbers for stateless verification
                    num2: currentChallenge.num2,
                    ttl: selectedTtl
                }),
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: "An unknown error occurred." }));
                // FastAPI validation errors return a 'detail' array of objects.
                if (Array.isArray(errorData.detail)) {
                    // Extract the first, most relevant error message.
                    const firstError = errorData.detail[0];
                    throw new Error(firstError.msg || 'Invalid input.');
                }
                // Handle other structured errors or simple string details.
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
        } finally {
            setLoading(false);
        }
    });

    // --- Copy to Clipboard ---
    const copyButton = document.getElementById('copy-button');
    copyButton.addEventListener('click', () => {
        // Use textContent to ensure we copy the exact string, not a resolved URL
        navigator.clipboard.writeText(shortUrlLink.textContent).then(() => {
            // Add a class to trigger the animation and change text
            copyButton.classList.add('copied');
            copyButton.textContent = 'Copied!';

            // Reset the button after the animation
            setTimeout(() => {
                copyButton.classList.remove('copied');
                copyButton.textContent = 'Copy';
            }, 1500);
        }).catch(err => {
            console.error('Failed to copy text: ', err);
            alert('Failed to copy link. Please copy it manually.');
        });
    });

    // Initial setup
    getNewChallenge();
    updateTtlInfo(); // Set the initial text on page load
    setLoading(false); // Ensure button is enabled on load
});