// Faza 0 — bezpieczny preflight gTrade (TYLKO ODCZYT, zero transakcji).
//
// Cel: zanim wyślemy jakikolwiek realny trejd, potwierdzić on-chain rzeczy, których
// nie chcemy zgadywać:
//   1. Czym NAPRAWDĘ są adresy collateralu z docs (surowy USDC/DAI/WETH czy gToken-vault?)
//      -> odczyt symbol()/decimals() z adresów "docs" i porównanie z kanonicznymi.
//   2. Łączność z Arbitrum (RPC, chainId, numer bloku).
//   3. Jeśli podano GTRADE_PRIVATE_KEY: adres portfela + saldo ETH (gas) + salda tokenów
//      + allowance dla diamentu. NIC NIE PODPISUJE ani nie wysyła.
//
// Uruchomienie:
//   node preflight.js                (sam sprawdza sieć + tożsamość tokenów)
//   GTRADE_PRIVATE_KEY=0x... node preflight.js   (dodatkowo salda portfela)
//
// Klucz prywatny czytamy TYLKO z env — nigdy nie zapisujemy, nie logujemy w całości.

import { ethers } from "ethers";
import { ARBITRUM } from "./config.js";
import { ERC20_ABI } from "./abi.js";

const line = (s = "") => process.stdout.write(s + "\n");
const short = (a) => (a ? a.slice(0, 6) + "…" + a.slice(-4) : "—");

async function tokenInfo(provider, address) {
  try {
    const c = new ethers.Contract(address, ERC20_ABI, provider);
    const [symbol, decimals] = await Promise.all([c.symbol(), c.decimals()]);
    return { address, symbol, decimals: Number(decimals), ok: true };
  } catch (e) {
    return { address, symbol: "?", decimals: null, ok: false, err: e.shortMessage || e.message };
  }
}

async function main() {
  line("=== gTrade preflight (Arbitrum, tylko odczyt) ===\n");

  const provider = new ethers.JsonRpcProvider(ARBITRUM.rpcUrl, ARBITRUM.chainId);

  // 1) Łączność
  let block, net;
  try {
    [block, net] = await Promise.all([provider.getBlockNumber(), provider.getNetwork()]);
  } catch (e) {
    line("❌ Brak łączności z RPC: " + (e.shortMessage || e.message));
    line("   Ustaw własny endpoint: GTRADE_RPC_URL=... (np. Alchemy/Infura)");
    process.exit(1);
  }
  line(`RPC: ${ARBITRUM.rpcUrl}`);
  line(`Sieć: chainId=${net.chainId} (oczekiwane 42161), blok #${block}`);
  line(`Diamond (kontrakt handlowy): ${ARBITRUM.diamond}\n`);

  // 2) Tożsamość collateralu — docs vs kanoniczne
  line("--- Weryfikacja adresów collateralu (symbol/decimals z łańcucha) ---");
  for (const name of ["USDC", "DAI", "WETH"]) {
    const docs = await tokenInfo(provider, ARBITRUM.collateralDocs[name]);
    const canon = await tokenInfo(provider, ARBITRUM.collateralCanonical[name]);
    line(`\n[${name}]`);
    line(`  docs      ${short(docs.address)}  -> symbol=${docs.symbol} decimals=${docs.decimals}` + (docs.ok ? "" : `  (BŁĄD: ${docs.err})`));
    line(`  kanoniczny ${short(canon.address)}  -> symbol=${canon.symbol} decimals=${canon.decimals}` + (canon.ok ? "" : `  (BŁĄD: ${canon.err})`));
    if (docs.ok) {
      const looksWrapped = /^g|vault|gToken/i.test(docs.symbol) || (docs.symbol !== name);
      line(looksWrapped
        ? `  ⚠️  adres z docs NIE jest surowym ${name} (symbol=${docs.symbol}) — collateral do wpłaty to prawdopodobnie adres kanoniczny.`
        : `  ✅ adres z docs wygląda na surowy ${name}.`);
    }
  }

  // 3) Portfel (opcjonalnie)
  const pk = process.env.GTRADE_PRIVATE_KEY;
  line("\n--- Portfel ---");
  if (!pk) {
    line("Brak GTRADE_PRIVATE_KEY — pomijam salda. (To normalne na tym etapie.)");
    line("Gdy założysz burner wallet: GTRADE_PRIVATE_KEY=0x... node preflight.js");
  } else {
    let wallet;
    try {
      wallet = new ethers.Wallet(pk, provider);
    } catch {
      line("❌ GTRADE_PRIVATE_KEY nie jest poprawnym kluczem prywatnym.");
      process.exit(1);
    }
    const eth = await provider.getBalance(wallet.address);
    line(`Adres: ${wallet.address}`);
    line(`ETH (gas): ${ethers.formatEther(eth)}` + (eth === 0n ? "  ⚠️ brak ETH na gas — nie wyślesz transakcji" : ""));
    for (const name of ["USDC", "DAI"]) {
      const info = await tokenInfo(provider, ARBITRUM.collateralCanonical[name]);
      if (!info.ok) continue;
      const c = new ethers.Contract(info.address, ERC20_ABI, provider);
      const [bal, allow] = await Promise.all([
        c.balanceOf(wallet.address),
        c.allowance(wallet.address, ARBITRUM.diamond),
      ]);
      line(`${name}: saldo=${ethers.formatUnits(bal, info.decimals)}  allowance(diamond)=${ethers.formatUnits(allow, info.decimals)}`);
    }
  }

  line("\n=== preflight OK (nic nie wysłano) ===");
}

main().catch((e) => {
  line("❌ Nieoczekiwany błąd: " + (e.stack || e.message));
  process.exit(1);
});
