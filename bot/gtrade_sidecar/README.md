# gTrade sidecar (Gains Network, Arbitrum)

Most **Node.js ↔ blockchain** dla NewsTradera. Python (`../broker_gtrade.py`) woła ten sidecar
przez HTTP; sidecar podpisuje i wysyła transakcje na Arbitrum przez `ethers`.

```
Python (broker_gtrade.py)  --HTTP/JSON-->  Node sidecar  --ethers-->  Arbitrum (gTrade diamond)
```

## Dlaczego sidecar, a nie czysty Python
Oficjalny stack gTrade (`@gainsnetwork/sdk`) jest w TypeScript i liczy pairIndex, ceny,
opłaty i likwidacje dokładnie jak kontrakty. Zamiast reimplementować to w web3.py, owijamy
oficjalny SDK cienkim serwerem Node — mniej ryzyka błędu w kodowaniu zleceń.

## Status
- ✅ **Faza 0 (gotowa):** `preflight.js` — odczyt-only. Potwierdza łączność z Arbitrum
  i **tożsamość collateralu**.
- ⏳ **Faza 1 (do zrobienia):** `server.js` — endpointy z kontraktu poniżej, rozwiązanie
  pairIndex + ceny z SDK, kodowanie `openTrade`/`closeTradeMarket`, `approve` USDC.

## ⚠️ Zweryfikowane on-chain (2026-07-13) — ważne
Adresy z kolumny „Token Address" w docs gTrade to **gToken-vaulty**, NIE collateral do wpłaty:

| docs mówi | adres | to naprawdę | collateral do WPŁATY |
|---|---|---|---|
| USDC | `0xd344…46E0` | **gUSDC** (vault) | `0xaf88…5831` (natywne USDC, 6 dec) |
| DAI  | `0xd85E…B91B` | **gDAI** (vault)  | `0xDA10…0da1` (18 dec) |
| WETH | `0x5977…784C` | **gETH** (vault)  | `0x82aF…Bab1` (18 dec) |

`approve` i wpłatę robimy na **kanoniczne** adresy (`config.js` → `collateral`). Domyślnie USDC.

## Uruchomienie
```bash
cd bot/gtrade_sidecar
npm install
node preflight.js                              # sam sprawdza sieć + tokeny
GTRADE_PRIVATE_KEY=0x... node preflight.js      # + salda burner walletu
```

## Zmienne środowiskowe
| env | znaczenie | domyślnie |
|---|---|---|
| `GTRADE_PRIVATE_KEY` | klucz prywatny **burner walletu** (tylko w env, nigdy w repo) | — |
| `GTRADE_RPC_URL` | endpoint RPC Arbitrum (własny Alchemy/Infura zalecany do produkcji) | publiczny `arb1.arbitrum.io/rpc` |
| `GTRADE_SIDECAR_PORT` | port serwera dla Pythona | `8787` |
| `GTRADE_COLLATERAL` | USDC / DAI / WETH | `USDC` |
| `GTRADE_LEVERAGE` | dźwignia gTrade (rozkład notional→collateral) | `5` |
| `GTRADE_MAX_SLIPPAGE_PCT` | maks. poślizg zlecenia | `1.0` |

## 🔐 Bezpieczeństwo
- Używaj **osobnego burner walletu** tylko do bota. Klucz tego portfela musi być w env,
  by bot mógł podpisywać — więc trzymaj tam **mało środków**.
- **Nigdy** nie wkładaj tu klucza swojego głównego Trust Walletu.
- Klucz prywatny czytany wyłącznie z env; nie jest logowany ani zapisywany.

## Kontrakt HTTP (server.js — Faza 1)
Zdefiniowany w nagłówku `../broker_gtrade.py` (endpointy `/health`, `/account`, `/positions`,
`/find_pair`, `/price`, `/open`, `/close`, `/update_sl`).
