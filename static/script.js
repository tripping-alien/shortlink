document.addEventListener('DOMContentLoaded', () => {
    // --- Element Selectors ---
    const shortenForm = document.getElementById('shorten-form');
    const submitButton = document.getElementById('submit-button');
    const buttonText = submitButton.querySelector('.button-text');
    const spinner = submitButton.querySelector('.spinner');
    const resultBox = document.getElementById('result-box');
    const shortUrlLink = document.getElementById('short-url-link');
    const copyButton = document.getElementById('copy-button');
    const ttlSelect = document.getElementById('ttl-select');
    const languageSwitcher = document.querySelector('.language-switcher');

    // --- Toast Notification Function ---
    function showToast(message, type = 'error') {
        const toastContainer = document.getElementById('toast-container');
        if (!toastContainer) return;

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;

        toastContainer.appendChild(toast);

        // Animate in
        setTimeout(() => {
            toast.classList.add('show');
        }, 100);

        // Animate out and remove after a delay
        setTimeout(() => {
            toast.classList.remove('show');
            toast.addEventListener('transitionend', () => toast.remove());
        }, 5000);
    }

    // --- Form Submission Handler ---
    if (shortenForm) {
        shortenForm.addEventListener('submit', async (event) => {
            event.preventDefault(); // This is the key fix: prevent default browser submission

            // Hide the result box while a new link is being created
            resultBox.style.display = 'none';
            resultBox.classList.remove('fade-in-up');

            // Show spinner and disable button
            buttonText.style.display = 'none';
            spinner.style.display = 'inline-block';
            submitButton.disabled = true;

            const formData = new FormData(shortenForm);
            const payload = {
                long_url: formData.get('long_url'),
                ttl: formData.get('ttl')
            };

            try {
                const response = await fetch('/api/links', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }, // Send data as JSON
                    body: JSON.stringify(payload)
                });

                const data = await response.json();

                if (!response.ok) {
                    // Smartly parse FastAPI's validation errors
                    let errorMessage = "An unexpected error occurred.";
                    if (data.detail) {
                        if (Array.isArray(data.detail) && data.detail[0] && data.detail[0].msg) {
                            errorMessage = data.detail[0].msg;
                        } else if (typeof data.detail === 'string') {
                            errorMessage = data.detail;
                        }
                    }
                    throw new Error(errorMessage);
                }

                // --- This is the fix: Populate and show the result box ---
                shortUrlLink.href = data.short_url;
                shortUrlLink.textContent = data.short_url;
                resultBox.style.display = 'block';
                resultBox.classList.add('fade-in-up'); // Trigger fade-in animation
                copyButton.textContent = 'Copy';
                copyButton.classList.remove('copied');

            } catch (error) {
                showToast(error.message);
            } finally {
                // Hide spinner and re-enable button
                buttonText.style.display = 'inline-block';
                spinner.style.display = 'none';
                submitButton.disabled = false;
            }
        });
    }

    // --- Copy Button Handler ---
    if (copyButton) {
        copyButton.addEventListener('click', () => {
            navigator.clipboard.writeText(shortUrlLink.href).then(() => {
                copyButton.textContent = 'Copied!';
                copyButton.classList.add('copied');
            }).catch(err => {
                showToast('Failed to copy link.');
                console.error('Copy failed:', err);
            });
        });
    }

    // --- Language Cookie Handler ---
    if (languageSwitcher) {
        languageSwitcher.addEventListener('click', (event) => {
            const link = event.target.closest('a');
            if (!link) return;

            const lang = link.pathname.split('/')[1];
            if (lang) {
                // Set a cookie that expires in 1 year.
                document.cookie = `lang=${lang}; path=/; max-age=31536000; samesite=lax`;
            }
        });
    }

    // --- TTL Persistence and UI Update ---
    const TTL_STORAGE_KEY = 'bijective_shorty_ttl';

    function updateTtlInfo(i18n) {
        const ttlInfoText = document.getElementById('ttl-info-text');
        if (!ttlSelect || !ttlInfoText) return;

        const selectedValue = ttlSelect.value;
        let durationText = '';

        if (selectedValue === '1h') {
            durationText = i18n.ttl_1_hour;
        } else if (selectedValue === '1d') {
            durationText = i18n.ttl_24_hours;
        } else if (selectedValue === '1w') {
            durationText = i18n.ttl_1_week;
        }

        if (selectedValue === 'never') {
            ttlInfoText.textContent = i18n.expire_never;
        } else {
            ttlInfoText.textContent = i18n.expire_in_duration.replace('{duration}', durationText);
        }
    }

    // This self-invoking async function fetches translations and initializes the TTL UI
    (async function initTtl() {
        if (!ttlSelect) return;
        const langCode = document.documentElement.lang || 'en';
        try {
            const response = await fetch(`/api/translations/${langCode}`);
            const i18n = await response.json();

            const savedTtl = localStorage.getItem(TTL_STORAGE_KEY);
            if (savedTtl) {
                ttlSelect.value = savedTtl;
            }

            ttlSelect.addEventListener('change', () => {
                localStorage.setItem(TTL_STORAGE_KEY, ttlSelect.value);
                updateTtlInfo(i18n);
            });

            updateTtlInfo(i18n);
        } catch (error) {
            console.error("Failed to initialize TTL info:", error);
        }
    })();
});