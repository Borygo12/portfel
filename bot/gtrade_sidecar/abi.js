// Minimalne ABI. Na Fazę 0 potrzebujemy tylko odczytów ERC20 (tożsamość tokenów,
// salda, allowance). openTrade/closeTradeMarket zostawione jako REFERENCJA na Fazę 1
// — NIE wołane, dopóki preflight nie potwierdzi collateralu i nie dopniemy pairIndex/ceny.

export const ERC20_ABI = [
  "function symbol() view returns (string)",
  "function decimals() view returns (uint8)",
  "function balanceOf(address) view returns (uint256)",
  "function allowance(address owner, address spender) view returns (uint256)",
  "function approve(address spender, uint256 amount) returns (bool)",
];

// --- REFERENCJA (Faza 1), nie używane jeszcze ---
// struct ITradingStorage.Trade:
//   (address user, uint32 index, uint16 pairIndex, uint24 leverage, bool long,
//    bool isOpen, uint8 collateralIndex, uint8 tradeType, uint120 collateralAmount,
//    uint64 openPrice, uint64 tp, uint64 sl, ...)  -- dokładny layout do potwierdzenia z ABI diamentu.
export const TRADING_ABI_REFERENCE = [
  "function openTrade((address,uint32,uint16,uint24,bool,bool,uint8,uint8,uint120,uint64,uint64,uint64) _trade, uint16 _maxSlippageP, address _referrer) external",
  "function closeTradeMarket(uint32 _index, uint64 _expectedPrice) external",
];
