/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { burmese: ["'Noto Sans Myanmar'", "'Myanmar Text'", "Padauk", "sans-serif"] },
    },
  },
  plugins: [],
};
