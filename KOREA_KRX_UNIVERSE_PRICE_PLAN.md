# Korea KRX Historical Universe / Price Acquisition Plan

Status: **pre-OOS data-source freeze**. No 2023+ Korean strategy returns are inspected here.

## Goal
Construct a historical KOSPI/KOSDAQ common-stock universe and point-in-time market data for 2015-2022 before opening the 2023+ OOS period.

## Official KRX evidence
KRX Data Marketplace exposes separate official datasets for newly listed securities and delisted securities. The delisting table includes stock code, name, market, security type, share type, listing date, delisting date, reason, industry, par value and listed shares. The security finder also has an explicit option to include delisted securities. These sources will be used to reconstruct historical membership rather than relying on today's ticker list alone.

KRX Open API documents daily stock trading data from 2010-01-04 onward and requires an AUTH_KEY request header. It is the preferred source for daily OHLC/volume/trading value/market-cap fields once an API key is available.

## Historical-universe construction
For each security create an interval [listing_date, delisting_date], with an open end for securities still listed. Include a security on event date t only when listing_date <= t and (delisting_date is null or t < delisting_date), subject to the market/security filters below.

Primary universe:
- KOSPI or KOSDAQ.
- Common stock / ordinary share only where the KRX classification permits identification.
- Exclude KONEX.
- Exclude ETFs, ETNs, SPACs, preferred shares, REIT/fund-like vehicles where identifiable.
- Retain historically delisted companies.
- Preserve code/name changes and migration/relisting flags instead of silently treating them as new economic firms.

## Market-data fields required
At minimum by stock/date:
- open, high, low, close
- volume, trading value
- market capitalization
- listed shares when available
- market classification

These support next-session-open entry, R5/R10/R20/R60/R120, ADV20, median traded value, Amihud and market-cap diagnostics.

## Point-in-time rules
- Market cap for an event is taken from the last observable trading session strictly before the entry session; never from a future date.
- ADV20 and other liquidity diagnostics use only sessions strictly before entry.
- Entry remains first KRX trading-session open strictly after the confirmed disclosure date/time rule in the research specification.
- Delisted names remain in historical samples if they were eligible on the event date.

## Research guardrail
Do not use 2023+ returns, market-cap cutoffs, FCF thresholds, holding-period optimization or exit optimization while building/validating these sources. Development remains 2015-2020 and Validation 2021-2022.

## Current blocker
The repository does not yet have a KRX Open API AUTH_KEY. Until that credential is available, do not substitute current-state pykrx output and call it survivorship-free. The official KRX listing/delisting datasets establish the reconstruction design, while the authenticated Open API is the preferred daily market-data path.
