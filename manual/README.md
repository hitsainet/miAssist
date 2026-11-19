# miAssist manual

The public manual for miAssist, built with Docusaurus and published to GitHub Pages from the public
mirror. `npm ci && npm test && npm run build` builds it; the build fails on a broken link, and
`scripts/check-published.mjs` refuses a built page carrying anything in `publish-rules.json`.
