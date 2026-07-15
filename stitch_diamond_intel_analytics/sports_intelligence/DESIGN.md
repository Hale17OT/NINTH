---
name: Sports Intelligence
colors:
  surface: '#200f09'
  surface-dim: '#200f09'
  surface-bright: '#4b342d'
  surface-container-lowest: '#1a0a05'
  surface-container-low: '#2a1711'
  surface-container: '#2e1b15'
  surface-container-high: '#3a251f'
  surface-container-highest: '#462f29'
  on-surface: '#ffdbd1'
  on-surface-variant: '#bacac6'
  inverse-surface: '#ffdbd1'
  inverse-on-surface: '#412b25'
  outline: '#859490'
  outline-variant: '#3b4a47'
  surface-tint: '#2bdec8'
  primary: '#a8ffef'
  on-primary: '#003731'
  primary-container: '#41ead4'
  on-primary-container: '#00665b'
  inverse-primary: '#006b5f'
  secondary: '#ffb2be'
  on-secondary: '#660026'
  secondary-container: '#ff4d7d'
  on-secondary-container: '#5a0020'
  tertiary: '#fbe9ff'
  on-tertiary: '#422256'
  tertiary-container: '#ecc4ff'
  on-tertiary-container: '#6f4c83'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#58fae4'
  primary-fixed-dim: '#2bdec8'
  on-primary-fixed: '#00201c'
  on-primary-fixed-variant: '#005047'
  secondary-fixed: '#ffd9de'
  secondary-fixed-dim: '#ffb2be'
  on-secondary-fixed: '#400015'
  on-secondary-fixed-variant: '#900039'
  tertiary-fixed: '#f4d9ff'
  tertiary-fixed-dim: '#e1b7f6'
  on-tertiary-fixed: '#2c0b40'
  on-tertiary-fixed-variant: '#5a396e'
  background: '#200f09'
  on-background: '#ffdbd1'
  surface-variant: '#462f29'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: '1.1'
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: '1.4'
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  stat-main:
    fontFamily: IBM Plex Mono
    fontSize: 20px
    fontWeight: '600'
    lineHeight: '1'
  stat-support:
    fontFamily: IBM Plex Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '1'
    letterSpacing: 0.05em
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: '1'
    letterSpacing: 0.08em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 48px
  container-max: 1440px
  gutter: 16px
---

## Brand & Style
The design system is engineered for "Sports Intelligence"—a high-performance aesthetic that merges the precision of a professional financial terminal with the sleek, consumer-grade polish of top-tier productivity software. It targets serious bettors and data analysts who require high density without sacrificing clarity.

The style is **Modern/Glassmorphic**, utilizing layered translucent surfaces to create depth without visual clutter. It prioritizes "mechanical" precision, using sharp execution, subtle glows, and a technical atmosphere to evoke a sense of authority and real-time responsiveness.

## Colors
The palette is rooted in a deep "Pitch Black" blue (`#050A14`) to provide maximum contrast for data visualization. 

- **Primary (Teal):** Used for "High Confidence" signals, primary actions, and successful trends.
- **Secondary (Electric Pink):** Reserved for "Live" indicators, high-volatility "sharp" money, and critical upsets.
- **Deep Purple:** Identifies AI-generated insights and proprietary advanced modeling.
- **Glass Effects:** Border colors for glass elements should use `20%` opacity of the primary or neutral white to create the "etched" look.

## Typography
Typography is split into two functional roles: **Inter** handles the UI narrative and hierarchy, while **IBM Plex Mono** is used exclusively for numerical data, betting odds, and player statistics to ensure character alignment in dense tables.

For mobile, `display-lg` scales down to `32px`. All numerical data should maintain its monospace styling regardless of screen size to ensure rapid scanning of moving odds.

## Layout & Spacing
The system uses a **Fixed Grid** on desktop (12 columns, 1440px max-width) and a **Fluid Grid** on mobile (4 columns). 

The spacing rhythm is strictly based on a **4px base unit**. Given the data-rich nature of the platform, the "Compact" density model is the default. Margins are generally `24px` on desktop, but internal card padding should remain at `16px` to maximize screen real estate for charts and tables.

## Elevation & Depth
Depth is conveyed through **Glassmorphism** and **Tonal Layering** rather than traditional drop shadows.

- **Level 0 (Base):** `#050A14` (The canvas).
- **Level 1 (Cards/Sidebar):** `#07111F` with a `1px` solid border at `10%` white opacity.
- **Level 2 (Modals/Popovers):** `#081827` with a `Backdrop Blur` of `12px` and a `1px` top-highlight border.
- **Featured State:** A soft, outer glow using the Primary Teal (`#41EAD4`) at `15%` opacity, restricted to high-confidence betting picks or featured games.

## Shapes
The shape language is "Soft-Technical." A standard radius of `4px` (`rounded-sm`) is used for buttons and inputs to maintain a professional, precise feel. Larger containers and cards use `8px` (`rounded-lg`). 

Player headshots and team logos should use a `12%` radius (squircle) rather than full circles to maintain the modern, "Apple-style" software aesthetic.

## Components
- **Buttons:** Primary buttons use a solid Teal (`#41EAD4`) with black text. Secondary buttons use a glass background (10% white fill) with a 1px border.
- **Data Cards:** Must include a "header" area for the sport/game time and a "footer" for AI insights. Use subtle vertical separators between stats.
- **Odds Toggle:** A segmented control (glass style) to switch between American, Decimal, and Fractional odds.
- **Live Indicator:** A small `8px` dot using the Secondary Pink (`#FF206E`) with a localized "pulse" animation (expanding ring).
- **Input Fields:** Dark background (`#050A14`) with a focus state that illuminates the entire border in Primary Teal.
- **Progress Bars:** Used for "Win Probability." Use a dual-gradient fill (Teal to Deep Purple) to represent the shift in momentum.
- **Chips/Badges:** Use low-opacity fills (e.g., 10% Pink for "Upset Alert") with high-contrast text.