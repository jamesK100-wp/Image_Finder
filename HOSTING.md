# Permanent hosting on Render

This configuration uses a **paid Standard web service and 50 GB persistent
disk**. Review the current price in Render before approving deployment.
Google API usage is billed separately. Monitor disk space and expand it or
remove old jobs as needed; 50 GB is not a guarantee of capacity for 20,000 restaurants.

1. Open https://dashboard.render.com/select-repo?type=blueprint and sign in
   with GitHub. Authorize access to `jamesK100-wp/Image_Finder`.
2. Select this repository's `render.yaml` Blueprint.
3. Set `APP_PASSWORD` to a unique password of at least 16 characters. The
   username is `owner`. Set `GOOGLE_API_KEY` in Render's secret environment
   settings. Do not put either secret in GitHub or chat.
4. Review the service/disk price, then deploy. Building and first-time model
   download can take several minutes.
5. Open the HTTPS `onrender.com` address shown by Render. Sign in using
   `owner` and your password. Bookmark that address.

Your computer can be off. Workbooks, progress, outputs, and model cache persist
under `/var/data`. One workbook processes at a time. Interrupted jobs retry on
startup; successful verified rows are reused. Selection and enhancement may
repeat. Avoid redeploying during large batches. This is single-server hosting,
not a distributed queue or a promise of uninterrupted processing.

Start with a small workbook. Inspect matches, disk usage and Google billing
before increasing batch size. Back up important outputs. Sustained 20k-scale
use needs capacity planning, object storage and a durable worker queue.
