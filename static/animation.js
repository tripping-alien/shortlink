document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('background-animation');
    if (!canvas) {
        console.error("Animation canvas not found.");
        return;
    }
    const ctx = canvas.getContext('2d');

    let width, height, columns, drops;

    const chars = "123456abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";

    function getCssVariable(varName) {
        return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
    }

    function hexToRgb(hex) {
        const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
        return result ? {
            r: parseInt(result[1], 16),
            g: parseInt(result[2], 16),
            b: parseInt(result[3], 16)
        } : { r: 0, g: 0, b: 0 };
    }

    function resetAnimation() {
        width = canvas.width = window.innerWidth;
        height = canvas.height = window.innerHeight;
        columns = Math.floor(width / 20);
        drops = [];
        for (let x = 0; x < columns; x++) {
            drops[x] = 1;
        }
        // Instantly set the background color on reset
        ctx.fillStyle = getCssVariable('--bg-color');
        ctx.fillRect(0, 0, width, height);
    }

    function draw() {
        // Create a semi-transparent overlay for the fading trail effect
        const bgColor = getCssVariable('--bg-color');
        const rgb = hexToRgb(bgColor);
        ctx.fillStyle = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.1)`;
        ctx.fillRect(0, 0, width, height);

        ctx.fillStyle = getCssVariable('--rain-color');
        ctx.font = '15px Fira Code';

        for (let i = 0; i < drops.length; i++) {
            const text = chars[Math.floor(Math.random() * chars.length)];
            ctx.fillText(text, i * 20, drops[i] * 20);

            if (drops[i] * 20 > height && Math.random() > 0.975) {
                drops[i] = 0;
            }
            drops[i]++;
        }
    }

    // Initialize and start the animation
    resetAnimation();
    setInterval(draw, 33);

    // Reset on window resize
    window.addEventListener('resize', resetAnimation);
});