document.addEventListener('DOMContentLoaded', () => {
    const languageSwitcher = document.querySelector('.language-switcher');
    if (!languageSwitcher) {
        return;
    }

    languageSwitcher.addEventListener('click', (event) => {
        // Find the clicked anchor tag, even if the user clicked the image inside it.
        const link = event.target.closest('a');
        if (!link) {
            return;
        }

        // Extract language code from the href (e.g., "/en/" -> "en").
        const lang = link.pathname.split('/')[1];

        if (lang) {
            // Set a cookie that expires in 1 year.
            document.cookie = `lang=${lang}; path=/; max-age=31536000; samesite=lax`;
        }
    });
});