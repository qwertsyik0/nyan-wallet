# Nyan VIP asset integration

Uses **all 17 original PNG assets** supplied by the user, without redrawing or recompressing.

Files are placed at `assets/vip/`. UI is extended within the **existing** Nyan VIP modal, keeping the existing VIP purchase process, price, term length, weekly bonuses and retry protection unchanged.

## Setup in an existing checkout

```bash
python3 /path/to/nyan-vip-integration/apply_vip_integration.py --repo /path/to/nyan-wallet --check
python3 /path/to/nyan-vip-integration/apply_vip_integration.py --repo /path/to/nyan-wallet
```

The installer is deliberately not a deployment script; it does not push Git commits or overwrite production databases. Verify backend migration/app registration and deploy with the usual tested VPS process. Front-end GitHub Pages and VPS backend update independently.

## Changes

1. Enhanced popup with banner and 9 perk tiles using original pictures.
2. Visible VIP badge and profile decoration, including export of Nyan ID PNG.
3. User-controlled exclusive VIP wallet background; unavailable without server-authenticated active VIP.
4. VIP priority for open requests in the Wallet owner's **appeals** queue.
5. Owner-issued gifts and admissions to VIP raffles with auditable, idempotent grants; raffle admissions can be revoked.
6. Owner-published early-access announcements, served only to valid VIP members.
7. Owner-verified Shop cashback ledger, 8% for VIP at order time and 5% for everyone else, rounded down to whole lapcoins.

## Limitations requiring external integration

**Nyan Shop's checkout / existing 5% cashback is not present in this repository.** Its verified paid-order handler must call the owner-approved cashback integration once per order and cease granting the old 5% separately. This repository offers the owner-only `POST /api/owner/vip/shop-cashback` endpoint, a manual owner UI and a signed `POST /api/integrations/nyan-shop/cashback` webhook; it cannot automatically alter checkout code that is hosted elsewhere. Do not double-credit orders.

**VIP priority** is implemented for the wallet's built-in appeals queue. The separate Shop support bot has its own database/process and cannot be prioritised without an authenticated cross-service integration.

**Early access** gates the preview content returned by the wallet API. A public URL entered by the owner is not itself made private; do not put unreleased secrets at public URLs.

**VIP gifts/raffles** are never automatically granted; the owner has direct controls inside the VIP modal.

The source bundle is a *candidate implementation*. Run local/backend tests and a staged deployment before presenting it as production ready.

## Merchant API connection

A merchant-side integration helper is included as `bot_addons/nyan_shop_vip_cashback.py`. After verifying an order is paid, the Shop checkout must call:

    record_confirmed_shop_purchase(telegram_id=ID, order_id=STABLE_PAID_ORDER_ID, paid_kopecks=PRICE_IN_KOPECKS, purchased_at=PAYMENT_TIME)

Set the same strong random `NYAN_SHOP_CASHBACK_SECRET` on both Shop and Wallet backend environments. Calls are authenticated with HMAC SHA-256, and the order ID prevents duplicate credit. The payload amount comes from verified checkout records, not from user messages. **Remove/disable legacy 5% credit for those orders** or they will be paid twice. If the order is 251.10 ₽, standard cashback is 12 🐾, VIP cashback is 20 🐾, and the two are mutually exclusive.
