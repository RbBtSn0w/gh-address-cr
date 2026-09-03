# gh-address-cr product site

Static marketing homepage for Cloudflare Pages.

## Local preview

```bash
npx wrangler pages dev public
```

## Deploy

Cloudflare Pages Git Integration is the default deployment path. The project is
connected to `RbBtSn0w/gh-address-cr`, uses `website` as its root directory and
`public` as its output directory. Push changes to any non-`main` branch for a
preview; push `main` for production. The path filter is `website/**`, so nested
assets such as `website/public/zh/` also trigger a deployment.

The production custom domain is `gh-address-cr.rbbtsn0w.me`. Wrangler Direct
Upload remains available only as an emergency/manual fallback.

## Content operations

- Keep the category sentence in the title, description, first paragraph, and
  `public/llms.txt` aligned: “GitHub pull request review resolution for AI
  coding agents”.
- Add a new use case only when the runtime or packaged skill supports it; do
  not add customer logos, outcome metrics, or compatibility claims without
  evidence.
- Review search queries and GitHub referral clicks monthly. The current page
  deliberately uses no third-party tracker; add Cloudflare Web Analytics or
  another privacy-reviewed measurement tool only after its account token and
  retention policy are decided.
- After changing copy, update `public/sitemap.xml` only when new indexable URLs
  are introduced. Keep the homepage canonical URL and `llms.txt` links in sync.

## Pre-publish checklist

1. Confirm every product claim against the root `README.md` and `skill/`.
2. Run the static HTML/resource checks and preview with Pages locally.
3. Test the install CTA, external links, keyboard navigation, and mobile menu.
4. Deploy the exact `public/` directory and verify the custom domain over HTTPS.
