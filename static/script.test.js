// This is a simplified example assuming the toBijective function is accessible.
// In a real project, you would configure Jest to handle modules.

const toBijective = (n) => {
    if (n <= 0) return '';
    let result = '';
    while (n > 0) {
        result = '123456'[(n - 1) % 6] + result;
        n = Math.floor((n - 1) / 6);
    }
    return result;
};

describe('toBijective', () => {
    test('should correctly convert single-digit numbers', () => {
        expect(toBijective(1)).toBe('1');
        expect(toBijective(6)).toBe('6');
    });

    test('should correctly convert multi-digit numbers', () => {
        expect(toBijective(7)).toBe('11');
        expect(toBijective(43)).toBe('111');
    });
});