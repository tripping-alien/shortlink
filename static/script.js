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
    const animationOverlay = document.getElementById('animation-overlay');

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

    // --- Paper Airplane Animation ---
    function playPaperAirplaneAnimation() {
        if (!animationOverlay) return;

        const airplane = document.createElement('div');
        airplane.className = 'paper-airplane';
        airplane.innerHTML = `
            <svg viewBox="0 0 512 512" fill="currentColor">
                <path d="M498.1 5.6c10.1 7 15.4 19.1 13.5 31.2l-64 416c-1.5 9.7-7.4 18.2-16 23s-18.9 5.4-28 1.6l-119.2-49.7-63.8 63.8c-8.7 8.7-20.3 13.5-32.5 13.5s-23.8-4.8-32.5-13.5l-63.8-63.8L2.6 295.4c-4.4-6.6-6.1-14.3-5.5-22s3.3-14.9 8.6-20.3l432-352c9.3-7.6 21.8-9.2 33.5-4.1s20.5 15.8 22.4 28zM64 400c0 17.7 14.3 32 32 32s32-14.3 32-32-14.3-32-32-32-32 14.3-32 32z"/>
            </svg>
        `;
        animationOverlay.appendChild(airplane);

        // Calculate start and end points
        const startRect = submitButton.getBoundingClientRect();
        const endRect = resultBox.getBoundingClientRect();

        airplane.style.left = `${startRect.left + startRect.width / 2}px`;
        airplane.style.top = `${startRect.top + startRect.height / 2}px`;

        // Trigger the animation
        requestAnimationFrame(() => {
            airplane.style.setProperty('--end-x', `${endRect.left + endRect.width / 2}px`);
            airplane.style.setProperty('--end-y', `${endRect.top + endRect.height / 2}px`);
            airplane.classList.add('fly');
        });

        // Clean up the airplane element after the animation
        airplane.addEventListener('animationend', () => {
            airplane.remove();
            // Show the result box as the plane "delivers" it
            resultBox.style.display = 'block';
            resultBox.classList.add('fade-in-up');
        });
    }

    // --- Copy Button Handler ---
    if (copyButton) {
        copyButton.addEventListener('click', () => {
            navigator.clipboard.writeText(shortUrlLink.href).then(() => {
                copyButton.textContent = 'Copied!';
                copyButton.classList.add('copied');
                setTimeout(() => {
                    copyButton.textContent = 'Copy';
                    copyButton.classList.remove('copied');
                }, 2000);
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
        const langCode = document.body.lang || 'en';
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