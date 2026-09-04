const colors = require("tailwindcss/colors");

const channelColor = (name) =>
  `color-mix(in srgb, var(--color-${name}) calc(<alpha-value> * 100%), transparent)`;
const themedScale = (name, shades) =>
  Object.fromEntries(shades.map((shade) => [shade, channelColor(`${name}-${shade}`)]));

const primary = themedScale("primary", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]);
const secondary = themedScale("secondary", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]);
const dark = themedScale("dark", [50, 100, 200, 300, 400, 500, 600]);

module.exports = {
  content: [
    "./backend/**/templates/**/*.html",
    "./backend/**/*.py",
    "./backend/**/static/**/*.js",
    "./frontend/templates/**/*.html",
    "./frontend/static/**/*.js",
    "!./backend/horilla_theme/static/horilla_theme/assets/js/tailwind*.js",
    "!./frontend/static/build/vendor/**/*.js",
    "!./frontend/static/build/**/*.min.js",
    "!./frontend/static/jquery/**/*.js",
  ],
  safelist: [
    {
      pattern: /^(bg|text|border|ring)-(primary|brand|secondary|dark)-(50|100|200|300|400|500|600|700|800|900)$/,
      variants: ["hover", "focus", "focus-visible", "peer-checked"],
    },
    {
      pattern: /^(bg|text|border|ring)-info-(50|100|200|300|400|500|600|700|800|900)$/,
      variants: ["hover", "focus"],
    },
  ],
  theme: {
    extend: {
      colors: {
        primary,
        brand: primary,
        secondary,
        dark,
        info: {
          50: "#eaf6fc",
          100: "#c9e8f7",
          200: "#95d0ec",
          300: "#5eb8e2",
          400: "#3aa6da",
          500: "#2E9BD6",
          600: "#2E9BD6",
          700: "#2585b8",
          800: "#1f6d97",
          900: "#184f6f",
        },
        color: { 600: colors.gray[700] },
        success: { light: colors.green[300], DEFAULT: colors.green[500], dark: colors.green[700] },
        warning: { light: colors.amber[200], DEFAULT: colors.amber[500], dark: colors.amber[700] },
        danger: { light: colors.red[300], DEFAULT: colors.red[500], dark: colors.red[700] },
      },
      boxShadow: {
        card: "0 0 10px rgb(0 0 0 / 0.05)",
      },
      spacing: {
        18: "4.5rem",
        84: "21rem",
      },
      borderRadius: {
        "4xl": "2rem",
        "5xl": "2.5rem",
      },
      fontSize: {
        xxs: "0.625rem",
      },
      height: {
        "screen-50": "50vh",
        "screen-75": "75vh",
      },
    },
  },
};
