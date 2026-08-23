# Tracking, Pixels & CAPI

Goal: **browser pixels + server CAPI** with the same `event_id`, SHA-256 PII, Moroccan phone in `+212`, and **deferred** pixel download so LCP / PageSpeed stay clean.

---

## 1. Identifiers

| Platform | Browser env | Server env |
|---|---|---|
| Meta | `NEXT_PUBLIC_FB_PIXEL_ID` | `META_PIXEL_ID`, `META_CAPI_ACCESS_TOKEN`, optional `META_TEST_EVENT_CODE` |
| TikTok | `NEXT_PUBLIC_TIKTOK_PIXEL_ID` | `TIKTOK_PIXEL_ID`, `TIKTOK_ACCESS_TOKEN` |
| Snapchat | `NEXT_PUBLIC_SNAPCHAT_PIXEL_ID` | `SNAPCHAT_PIXEL_ID`, `SNAPCHAT_CAPI_TOKEN` |

Never ship access tokens to Next.js.

---

## 2. Deduplication key

Generate once per user action:

```ts
crypto.randomUUID() // event_id
```

| Side | Field |
|---|---|
| Meta Pixel | `fbq('track', name, params, { eventID: event_id })` |
| TikTok Pixel | `ttq.track(name, params, { event_id })` |
| Snapchat Pixel | `snaptr('track', name, { …, client_dedup_id: event_id })` |
| Meta CAPI | `event_id` |
| TikTok Events API | `event.id` |
| Snapchat CAPI | `client_dedup_id` |

If the pixel and CAPI share this id within the platform window (~48h Meta), the ad manager keeps **one** conversion.

---

## 3. Deferred web pixels (PageSpeed)

`PixelLoader` waits for `requestIdleCallback` **or** 2.5s, whichever first. Scripts use `next/script` `strategy="lazyOnload"` only after that gate.

Until scripts exist, `lib/tracking.ts` **queues** calls (`pageview`, `ViewContent`, `AddToCart`, …) and flushes on load.

This avoids competing with the hero image on 4G in-app browsers.

---

## 4. Browser snippets (injected after idle)

### Meta

```js
!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;
n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}
(window, document,'script','https://connect.facebook.net/en_US/fbevents.js');
fbq('init', PIXEL_ID);
fbq('track', 'PageView', {}, { eventID: pageviewEventId });
```

### TikTok

```js
!function (w, d, t) {
  w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];
  ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie"];
  ttq.setAndDefer=function(t,e){t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};
  for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);
  ttq.instance=function(t){for(var e=ttq._i[t]||[],n=0;n<ttq.methods.length;n++)ttq.setAndDefer(e,ttq.methods[n]);return e};
  ttq.load=function(e,n){var i="https://analytics.tiktok.com/i18n/pixel/events.js";
  ttq._i=ttq._i||{};ttq._i[e]=[];ttq._i[e]._u=i;ttq._t=ttq._t||{};ttq._t[e]=+new Date;ttq._o=ttq._o||{};ttq._o[e]=n||{};
  var o=d.createElement("script");o.type="text/javascript";o.async=!0;o.src=i+"?sdkid="+e+"&lib="+t;
  var a=d.getElementsByTagName("script")[0];a.parentNode.insertBefore(o,a)};
}(window, document, 'ttq');
ttq.load(PIXEL_ID);
ttq.page();
```

### Snapchat

```js
(function(e,t,n){if(e.snaptr)return;var a=e.snaptr=function()
{a.handleRequest?a.handleRequest.apply(a,arguments):a.queue.push(arguments)};
a.queue=[];var s='script';r=t.createElement(s);r.async=!0;
r.src='https://sc-static.net/scevent.min.js';
var u=t.getElementsByTagName(s)[0];u.parentNode.insertBefore(r,u);})(window,document);
snaptr('init', PIXEL_ID);
snaptr('track', 'PAGE_VIEW');
```

---

## 5. Event map

| Funnel step | Meta | TikTok | Snap | Server CAPI |
|---|---|---|---|---|
| Land | `PageView` | `Pageview` / `ttq.page` | `PAGE_VIEW` | optional |
| Product LP | `ViewContent` | `ViewContent` | `VIEW_CONTENT` | `POST /api/tracking/events` |
| CTA / drawer | `AddToCart` | `AddToCart` | `ADD_CART` | same |
| Open checkout | `InitiateCheckout` | `InitiateCheckout` | `START_CHECKOUT` | same |
| Order 201 | `Purchase` | `CompletePayment` | `PURCHASE` | order background task |
| Upsell accept | `Purchase` | `CompletePayment` | `PURCHASE` | upsell background task |

`value` + `currency: 'MAD'` + `content_ids: [slug]` on commerce events.

---

## 6. Moroccan phone formatting

Implementation: `backend/app/services/phone.py` and `frontend/src/lib/phone.ts`.

Steps:

1. Strip everything except digits and a leading `+`.
2. Map to E.164:
   - `0[5-7]XXXXXXXX` (10 digits) → `+212` + nine-digit national (drop the 0)
   - `00212[5-7]XXXXXXXX` → `+212…`
   - `212[5-7]XXXXXXXX` → `+212…`
   - `[5-7]XXXXXXXX` (9 digits) → `+212…`
3. Reject otherwise.

Display national: `0` + 9 digits (`0612345678`).

---

## 7. SHA-256 hashing (CAPI user data)

Hex digest of **UTF-8** bytes, **lowercase**. Hash **after** normalize.

| Field | Normalize then hash |
|---|---|
| Phone `ph` | E.164 **without** `+` and without spaces: `2126xxxxxxxx` |
| Email `em` | `trim.lower` (email is optional in this COD funnel) |
| City `ct` | `trim.lower`, strip Arabic tatweel, collapse spaces. Hash the **French** city key when available (`casablanca`) so Meta’s geo matching is latin-friendly; also send `country` = hash(`ma`) |
| First name `fn` | first token of `full_name`, lower, no diacritics if latin |
| Last name `ln` | remainder of name, same |

**Never hash:** `client_ip_address`, `client_user_agent`, `fbp`, `fbc`, `ttclid`, `sccid` / `ScCid`.

Python:

```python
import hashlib

def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
```

---

## 8. Meta CAPI body (Purchase)

```json
{
  "data": [
    {
      "event_name": "Purchase",
      "event_time": 1710000000,
      "event_id": "UUID",
      "event_source_url": "https://chifaglow.com/thank-you",
      "action_source": "website",
      "user_data": {
        "ph": ["<sha256>"],
        "fn": ["<sha256>"],
        "ln": ["<sha256>"],
        "ct": ["<sha256>"],
        "country": ["<sha256 of ma>"],
        "client_ip_address": "105.x.x.x",
        "client_user_agent": "Mozilla/…",
        "fbp": "fb.1.…",
        "fbc": "fb.1.…"
      },
      "custom_data": {
        "currency": "MAD",
        "value": 279.0,
        "content_type": "product",
        "content_ids": ["quran"],
        "contents": [{ "id": "quran", "quantity": 2, "item_price": 139.5 }],
        "order_id": "…"
      }
    }
  ],
  "access_token": "…",
  "test_event_code": "TEST12345"
}
```

`test_event_code` only if `META_TEST_EVENT_CODE` is set (Events Manager test).

---

## 9. TikTok Events API (v1.3)

Header: `Access-Token: TIKTOK_ACCESS_TOKEN`

```json
{
  "event_source": "web",
  "event_source_id": "PIXEL_ID",
  "data": [
    {
      "event": "CompletePayment",
      "event_time": 1710000000,
      "event_id": "UUID",
      "user": {
        "phone": "<sha256 of +2126… E.164 with plus stripped per TikTok: 2126…>",
        "ip": "105.x.x.x",
        "user_agent": "…",
        "ttclid": "…"
      },
      "properties": {
        "currency": "MAD",
        "value": 279,
        "content_ids": ["quran"]
      },
      "page": { "url": "https://chifaglow.com/thank-you" }
    }
  ]
}
```

---

## 10. Snapchat CAPI v3

`POST https://tr.snapchat.com/v3/{PIXEL_ID}/events?access_token=TOKEN`

```json
{
  "data": [
    {
      "event_name": "PURCHASE",
      "event_time": 1710000000,
      "event_source_url": "https://chifaglow.com/thank-you",
      "action_source": "WEB",
      "event_id": "UUID",
      "user_data": {
        "ph": ["<sha256>"],
        "client_ip_address": "…",
        "client_user_agent": "…",
        "sc_click_id": "…"
      },
      "custom_data": { "currency": "MAD", "value": "279.00" }
    }
  ]
}
```

Also set `client_dedup_id` = `event_id` when the Snap payload version expects it (we send both `event_id` and `client_dedup_id` with the same UUID).

---

## 11. Click ids to persist

| Cookie / query | Store on order |
|---|---|
| `_fbp` | `fbp` |
| `_fbc` or `?fbclid=` | `fbc` (`fb.1.{ts}.{fbclid}` if we must build it) |
| `ttclid` | `ttclid` |
| `ScCid` / `sccid` | `sccid` |

Frontend `lib/tracking.ts` reads cookies + query on each CAPI-bound request.

---

## 12. QA

1. Place a test order with `META_TEST_EVENT_CODE` set — Events Manager **Test events** should show a **deduped** Purchase (browser + server, one id).
2. Confirm hashed `ph` corresponds to `2126…` not `0612…` and not `+2126…`.
3. Confirm pixels are absent from the initial HTML document (view-source) and appear after idle.
4. Confirm `/api/tracking/events` and `/api/orders` never return tokens.
