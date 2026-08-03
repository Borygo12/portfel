// Zweryfikowane adresy i stałe gTrade na Arbitrum. Źródło: docs.gains.trade
// (technical-reference/contracts + contract-addresses/arbitrum-mainnet), stan 2026-07.
//
// UWAGA: kolumna "Token Address" w docs collateralu bywa myląca — mogą to być
// adresy gToken-vault, a nie surowe ERC20. Dlatego preflight.js ODCZYTUJE symbol()
// z każdego adresu, zamiast ślepo ufać. Nic tu nie hardcode'ujemy jako pewnik do
// egzekucji, dopóki preflight nie potwierdzi tożsamości tokenów.

export const ARBITRUM = {
  chainId: 42161,
  // Publiczny RPC; można nadpisać przez env GTRADE_RPC_URL (np. własny Alchemy/Infura).
  rpcUrl: process.env.GTRADE_RPC_URL || "https://arb1.arbitrum.io/rpc",

  // Główny kontrakt handlowy (diamond) — openTrade / closeTradeMarket.
  diamond: "0xFF162c694eAA571f685030649814282eA457f169",

  // Adresy z kolumny "Token Address" w docs gTrade. POTWIERDZONE PRZEZ PREFLIGHT (2026-07-13):
  // to są gToken-VAULTY (gUSDC/gDAI/gETH), NIE collateral do wpłaty. Trzymane tu tylko
  // informacyjnie / do porównań — NIE używać jako token do approve/wpłaty.
  gTokenVaults: {
    USDC: "0xd3443ee1e91aF28e5FB858Fbd0D72A63bA8046E0", // gUSDC
    DAI: "0xd85E038593d7A098614721EaE955EC2022B9B91B",  // gDAI
    WETH: "0x5977A9682D7AF81D347CFc338c61692163a2784C", // gETH
  },

  // WŁAŚCIWY collateral do handlu (surowe ERC20). To tu wpłacasz środki i to na te
  // adresy robimy approve dla diamentu. Potwierdzone symbol()/decimals() w preflight.
  collateral: {
    USDC: { address: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", decimals: 6 },  // USDC natywne (Circle) — DOMYŚLNY
    DAI: { address: "0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1", decimals: 18 },
    WETH: { address: "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", decimals: 18 },
  },

  // Alias na potrzeby preflight (porównanie docs vs kanoniczne).
  get collateralDocs() { return { USDC: this.gTokenVaults.USDC, DAI: this.gTokenVaults.DAI, WETH: this.gTokenVaults.WETH }; },
  get collateralCanonical() { return { USDC: this.collateral.USDC.address, DAI: this.collateral.DAI.address, WETH: this.collateral.WETH.address }; },
};

// Precyzje ze specyfikacji kontraktu (technical-reference).
export const PRECISION = {
  price: 10n ** 10n,      // openPrice / tp / sl : 1e10
  leverage: 10n ** 3n,    // leverage : 1e3  (np. 2x -> 2000)
  slippage: 10n ** 3n,    // maxSlippageP : 1e3 (np. 1% -> 1000)
  // collateralAmount : "collateral precision" == decimals danego tokena (USDC=6, DAI=18)
};
