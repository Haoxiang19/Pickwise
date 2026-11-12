---
name: Pickwise
description: A shopping agent that looks like a quiet luxury store's own site, so prices and the pay step read as calm and certain.
colors:
  white: "#ffffff"
  sand: "#f5f2ee"
  sand-deep: "#ebe5dd"
  hairline: "#e8e2da"
  control-line: "#d3cbc1"
  ink: "#141414"
  ink-hover: "#333333"
  muted: "#625a52"
  espresso: "#7a5a43"
  espresso-ink: "#6b4e3a"
  espresso-tint: "#f1eae2"
  shopper-ink: "#2b2018"
  status-green: "#1f7a3d"
  status-amber: "#8f5a00"
  status-red: "#b3261e"
  error-tint: "#fdf6f5"
  error-line: "#e7b3af"
  mock-tint: "#fff4e5"
  mock-ink: "#7a4a00"
typography:
  display:
    fontFamily: "\"Helvetica Neue\", -apple-system, BlinkMacSystemFont, \"Segoe UI\", system-ui, Roboto, Arial, sans-serif"
    fontSize: "42px"
    fontWeight: 400
    lineHeight: 1.12
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "\"Helvetica Neue\", -apple-system, BlinkMacSystemFont, \"Segoe UI\", system-ui, Roboto, Arial, sans-serif"
    fontSize: "34px"
    fontWeight: 400
    lineHeight: 1.15
    letterSpacing: "-0.025em"
  wordmark:
    fontFamily: "\"Helvetica Neue\", -apple-system, BlinkMacSystemFont, \"Segoe UI\", system-ui, Roboto, Arial, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.26em"
  total:
    fontFamily: "\"Helvetica Neue\", -apple-system, BlinkMacSystemFont, \"Segoe UI\", system-ui, Roboto, Arial, sans-serif"
    fontSize: "22px"
    fontWeight: 600
    fontFeature: "\"tnum\""
  reply:
    fontFamily: "\"Helvetica Neue\", -apple-system, BlinkMacSystemFont, \"Segoe UI\", system-ui, Roboto, Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
  body:
    fontFamily: "\"Helvetica Neue\", -apple-system, BlinkMacSystemFont, \"Segoe UI\", system-ui, Roboto, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.6
  product-title:
    fontFamily: "\"Helvetica Neue\", -apple-system, BlinkMacSystemFont, \"Segoe UI\", system-ui, Roboto, Arial, sans-serif"
    fontSize: "14.5px"
    fontWeight: 500
    lineHeight: 1.4
  card-title:
    fontFamily: "\"Helvetica Neue\", -apple-system, BlinkMacSystemFont, \"Segoe UI\", system-ui, Roboto, Arial, sans-serif"
    fontSize: "12.5px"
    fontWeight: 600
    letterSpacing: "0.14em"
  label:
    fontFamily: "\"Helvetica Neue\", -apple-system, BlinkMacSystemFont, \"Segoe UI\", system-ui, Roboto, Arial, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    letterSpacing: "0.1em"
rounded:
  tag: "2px"
  sm: "4px"
  md: "6px"
spacing:
  gutter: "32px"
  gutter-phone: "16px"
  card: "26px"
  grid-gap: "18px"
  turn: "26px"
  column-max: "780px"
  sidebar: "248px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.white}"
    rounded: "{rounded.sm}"
    padding: "15px 20px"
    width: "100%"
  button-primary-hover:
    backgroundColor: "{colors.ink-hover}"
  button-outline:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "9px 16px"
  button-send:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.white}"
    rounded: "{rounded.sm}"
    padding: "8px 20px"
  nav-item:
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "10px 12px"
  nav-item-current:
    backgroundColor: "{colors.sand-deep}"
    textColor: "{colors.ink}"
  composer:
    backgroundColor: "{colors.white}"
    rounded: "{rounded.md}"
    padding: "6px"
  product-row:
    backgroundColor: "{colors.white}"
    rounded: "{rounded.md}"
    padding: "12px 16px 12px 12px"
  product-box:
    backgroundColor: "{colors.sand}"
    rounded: "{rounded.sm}"
    size: "84px"
  rank-top-pick:
    backgroundColor: "{colors.espresso}"
    textColor: "{colors.white}"
    typography: "{typography.label}"
    rounded: "{rounded.tag}"
    padding: "2px 8px"
  shopper-message:
    backgroundColor: "{colors.espresso-tint}"
    textColor: "{colors.shopper-ink}"
    rounded: "{rounded.md}"
    padding: "11px 17px"
  money-card:
    backgroundColor: "{colors.white}"
    rounded: "{rounded.md}"
    padding: "26px 26px 22px"
  mock-badge:
    backgroundColor: "{colors.mock-tint}"
    textColor: "{colors.mock-ink}"
    rounded: "{rounded.md}"
    padding: "2px 8px"
---

# Design System: Pickwise

## Overview

**Creative North Star: "The Quiet Store"**

The page looks like a luxury store's own website, not a chat app. It uses white space, black type, thin sand-coloured lines and product pictures on a sand backdrop. The goal is that prices, the order total and the pay button look calm and certain. Nothing decorative competes with the money steps.

There is one main colour pair: white and sand for surfaces, black for type and the money buttons. Espresso brown is the only accent, used in small amounts to mark what matters: the top pick, the chosen product, the current view, the agent's name. Green, amber and red appear only to report a state. The owner rejected chat-app chrome: tinted bubbles everywhere, pill buttons, saturated deep fills, navy and bright blue, and an icon logo.

**Key Characteristics:**
- White main area, sand sidebar, sand notice strip, sand product backdrops.
- Thin hairlines instead of shadows.
- Near-square corners (2, 4 and 6 px).
- Small uppercase tracked labels for titles and tags; controls in sentence case.
- Black buttons only where the user acts on the conversation or on money.
- System font stack, no web fonts (owner's brand commitment).
- Motion is only 150 ms state transitions.

## Colors

A warm neutral palette (white, sand, black) with one espresso accent and three state colours.

### Primary
- **Espresso** (`espresso`): the highlight colour. Used on the brand mark, the "Top pick" rank, the ring and button of the chosen product, the current view's icon, the focus ring, the input caret and the progress spinner.
- **Espresso Ink** (`espresso-ink`): espresso darkened for text. The agent's name above each reply, the "Ruled out" toggle, the hover colour of example requests, and the icon on memory entries.
- **Espresso Tint** (`espresso-tint`): the shopper's own messages, memory entry icon tiles, text selection.

### Neutral
- **White** (`white`): the main area, cards and default buttons.
- **Sand** (`sand`): the sidebar, the notice strip, product picture backdrops, small tags and empty states.
- **Deep Sand** (`sand-deep`): the current and hovered sidebar item.
- **Hairline** (`hairline`): every divider, card border and list rule.
- **Control Line** (`control-line`): the border of outlined buttons and the input box; also the scrollbar.
- **Ink** (`ink`): body text and the black buttons; `ink-hover` is their hover.
- **Muted** (`muted`): secondary text, reasons, notes, retailer brand names, idle icons.
- **Shopper Ink** (`shopper-ink`): text inside the shopper's message.

### State
- **Green / Amber / Red** (`status-green`, `status-amber`, `status-red`): order status chips (Paid, Partly refunded, Cancelled or failed). Red also marks error messages, a failed order card's border (`error-line`) and the Delete action on a memory entry.
- **Mock Amber** (`mock-tint`, `mock-ink`): the mock-mode badges in the notice strip.

### Named Rules
**The Espresso Is a Highlight Rule.** Espresso marks one thing per area: what is chosen, current, or recommended first. It never fills a large surface or a button at rest.

**The State-Only Colour Rule.** Green, amber and red mean a status, an error or a destructive action. They are never decoration.

## Typography

**Display Font:** system stack, "Helvetica Neue" first (with -apple-system, Segoe UI, Roboto, Arial)
**Body Font:** the same stack

**Character:** One family in a few weights. Large headings are regular weight with tight tracking; small labels are bold, uppercase and widely tracked, like a store's product labels.

### Hierarchy
- **Display** (400, 42 px, 1.12): the empty-state question "What are you shopping for?". 30 px on phones.
- **Headline** (400, 34 px, 1.15): the Orders and What I remember page titles. 28 px on phones.
- **Total** (600, 22 px, tabular figures): the order total. The order card's grand total is 20 px.
- **Reply** (400, 16 px, 1.6): the agent's replies and example requests.
- **Body** (400, 15 px, 1.6): default text. Notes and reasons drop to 13 px in `muted`.
- **Product title** (500, 14.5 px, 1.35): product names in product rows.
- **Card title** (600, 12.5 px, 0.14em, uppercase): "Order summary", "Order #...", "Refund for order #...", "Your orders".
- **Label** (600, 11 px, 0.1em, uppercase): rank tags, retailer brand names, table column heads, the "Shopping Agent" descriptor. The "Ruled out" toggle is 12 px; the agent's name is 11 px at 0.18em.
- **Wordmark** (600, 18 px, 0.26em, uppercase): "PICKWISE" in the sidebar.

### Named Rules
**The Labels Shout, Controls Speak Rule.** Uppercase tracking is for labels and card titles only. Every button and input stays in sentence case.

**The Tabular Money Rule.** Every price, total, quantity and status uses tabular figures so amounts line up.

## Layout

Desktop is a two-column grid: a 248 px sand sidebar (sticky, full height) and the main area. The main area holds the notice strip on top, then one centred column at most 780 px wide with 32 px side padding. The input is docked at the bottom of the conversation and fades the content above it into white.

Products are a stack of product rows with 8 px gaps, used for the three picks and for every item of a set: an 84 px sand box, the text, then price and action in a right-hand column so prices line up. Conversation turns are spaced 26 px apart. Money cards use 26 px padding. Lists (examples, ruled out, order lines, memory) are rows between hairlines, not boxes.

Below 860 px the sidebar becomes a top bar: the brand and New conversation on one row, the three views as equal tabs with the icon above the label. The column padding drops to 16 px; a product row shrinks its box to 64 px and moves price and action under the text. The top bar keeps its own height (grid rows `auto 1fr`). The page works at 375 px.

## Elevation & Depth

The system is flat. There are no drop shadows. Depth comes from tone (white on sand, sand on deep sand) and 1 px hairlines. The only box-shadow is an inset 1 px espresso ring that, with the espresso border, marks the chosen product row or the selected option of a set.

### Named Rules
**The Hairline Rule.** Separate things with a 1 px `hairline` line or a change of tone, never with a shadow.

## Shapes

Corners are near-square: 4 px for buttons, inputs and nav items, 6 px for cards, product rows, the shopper's message, badges and the input box, 2 px for rank tags. Only the status dot and spinner are round. Icons are thin line drawings (18 px, 1.5 px stroke, round caps) from an inline SVG sprite. The mark is three stacked cards with the front one checked, in espresso, always next to the PICKWISE wordmark.

## Components

### Buttons
- **Shape:** gently squared (4 px).
- **Primary (money step):** black fill, white text, full width, 15 px text, 15 px by 20 px padding. Used only for "Confirm and pay with PayPal" and "Confirm refund". Hover goes to dark grey.
- **Send:** black fill, compact, inside the input box.
- **Outline:** white with a `control-line` border; hover turns the border black. Used for New conversation and Choose.
- **Text link:** underlined, no border, for small actions (Refund this item, Details, Delete). Delete is red.
- **Disabled:** 45 % opacity. The pay button disables after one click.
- **Focus:** 2 px espresso outline, 2 px offset, on every control.

### Navigation
- Sidebar items: icon plus sentence-case label, 14.5 px. Hover and current item sit on deep sand; the current item is bold with its icon in espresso. On phones the three items become tabs.

### Inputs / Fields
- **Composer:** one white box with a `control-line` border and 6 px corners, the text field and Send inside. The border turns black when focused. The caret is espresso.

### Cards / Containers
- **Money cards** (order summary, order result, order list, refund draft): white, 1 px hairline border, 6 px corners, 26 px padding, no shadow. A failed order's border is `error-line`.
- **Empty state:** sand block, 6 px corners, centred muted text and a 24 px line icon.

### Product row (signature)
One row design for the three picks and for every item of a set (`productRow` in the page script). Left: an 84 px sand box with the brand name in small uppercase, covered by the catalog picture when it loads (blended with multiply). Middle: brand label and a tag ("Top pick" or "Best fit" in espresso, "Pick 2" and "Pick 3" on sand), the title, the reason in muted 13 px. Right: the price, then the action: a Choose button for a pick, a radio button with "Selected" / "Select" for a set option (the whole row is its label). The chosen pick and the selected option get an espresso border and ring; the chosen pick's button turns espresso.

### Ruled out list
A small uppercase espresso toggle with a chevron that turns 90 degrees when open. Inside, hairline rows with title, price and the reason for each rejected product.

### Status chip
Text with a 7 px dot in the same colour: green Paid, amber Partly refunded, red Cancelled or failed, muted for the rest. Refunded lines are struck through in muted and carry a sand "Refunded" tag.

### Notice strip
Sand strip across the top of the main area with the simulation sentence in muted 12.5 px and the mock-mode badges in amber.

### Trust cues (must keep)
A later change must keep each of these visible, with this exact text and meaning:
- The "Confirm and pay with PayPal" button (disabled after one click) and the note "Nothing is charged until you approve the payment on PayPal."
- The order total, always the server's number.
- The refund draft with "Nothing is refunded until you click Confirm refund." and its Confirm refund button.
- The concierge-simulation sentence in the notice strip ("no real money moves and nothing ships").
- The mock-mode badges.
- The "Ruled out" list with the reason for each product.

**The One Black Button Rule.** On any money card there is exactly one black full-width button, and it is the step that moves money after a human click.

## Do's and Don'ts

### Do:
- **Do** use the tokens in `:root` of `static/index.html`; add a new colour only for a new state.
- **Do** keep espresso to one highlight per area (chosen, current, top pick, agent name).
- **Do** separate content with 1 px `hairline` lines and tone, and keep surfaces flat.
- **Do** keep corners at 2, 4 or 6 px.
- **Do** use tabular figures for every amount.
- **Do** limit motion to 150 ms ease transitions of colour, border, ring and the chevron turn, and turn them off under reduced motion.
- **Do** keep every trust cue listed under Components with its exact text.

### Don't:
- **Don't** use pill buttons, saturated deep fills, navy or bright blue.
- **Don't** add drop shadows or entrance animations.
- **Don't** put uppercase tracking on buttons or inputs.
- **Don't** use green, amber or red for anything but a state, an error or a destructive action.
- **Don't** use a PayPal logo, wordmark or font, or anything that makes the page look like an official PayPal page.
- **Don't** load web fonts or icon libraries; icons are inline SVG line drawings.
- **Don't** let a decorative element sit closer to the eye than a price, a total, or the pay and refund buttons.
