---
name: meta-ads-cockpit
description: Meta (Facebook) Ads Manager via DevScope — use meta-ads-control MCP and /meta/* bridge routes for campaigns, insights, spend alerts, and gated write ops.
---

# Meta Ads Cockpit

DevScope reads and manages Meta ad accounts through the Marketing API (token at `~/.dev-bridge/meta_ads_token.json`) and optionally Meta's official HTTP MCP (`https://mcp.facebook.com/ads`).

## Setup (once)

```bash
export FACEBOOK_APP_ID=...
export FACEBOOK_APP_SECRET=...
python -m devscope_bridge.meta_ads.authorize_meta_ads
```

Requires Admin/Advertiser on the ad account in Business Manager.

Optional official MCP:

```bash
claude mcp add --transport http meta-ads-official https://mcp.facebook.com/ads
```

## Tools (meta-ads-control)

- `meta_list_accounts()`
- `meta_list_campaigns(ad_account_id, limit?)`
- `meta_get_insights(ad_account_id, date_preset?)`
- `meta_update_campaign_status(campaign_id, status, dry_run?)` — **dry_run=true by default**
- `meta_update_campaign_budget(campaign_id, daily_budget, dry_run?)` — **dry_run=true by default**

## Safety

Never pause, activate, or change budget without `dry_run=false` **and** explicit user confirmation. Read + insights are safe autonomously.
