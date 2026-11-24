/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        studio: {
          bg: "#0b0d12",
          panel: "#121620",
          card: "#171c28",
          border: "#252c3d",
          accent: "#6366f1",
          accentHover: "#4f46e5",
        },
      },
    },
  },
  plugins: [],
};
