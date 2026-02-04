"""
🐋 Aave Whale Watch - Data Fetcher (Alchemy Version)
Alchemy RPC를 통해 Aave V3 포지션 데이터 수집

Health Factor <= 1.5 & 담보 >= $200K 필터링
"""

import json
import os
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ===== Configuration =====
ALCHEMY_API_KEY = os.environ.get('ALCHEMY_API_KEY', '')

# Alchemy RPC URLs
RPC_URLS = {
    "ethereum": f"https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}",
    "arbitrum": f"https://arb-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}",
    "polygon": f"https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}",
    "base": f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
}

# Aave V3 Pool Contract Addresses
AAVE_POOL_ADDRESSES = {
    "ethereum": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
    "arbitrum": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
    "polygon": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
    "base": "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5"
}

# Thresholds
MAX_HEALTH_FACTOR = 1.5
MIN_COLLATERAL_USD = 200000  # $200K

OUTPUT_DIR = "data"


def rpc_call(url: str, method: str, params: list) -> dict:
    """Execute JSON-RPC call"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }
    
    data = json.dumps(payload).encode('utf-8')
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    req = Request(url, data=data, headers=headers, method='POST')
    
    try:
        with urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('result')
    except Exception as e:
        print(f"RPC Error: {e}")
        return None


def get_logs(rpc_url: str, contract_address: str, topics: list, from_block: str, to_block: str = "latest") -> list:
    """Get event logs from contract"""
    params = [{
        "address": contract_address,
        "topics": topics,
        "fromBlock": from_block,
        "toBlock": to_block
    }]
    
    result = rpc_call(rpc_url, "eth_getLogs", params)
    return result if result else []


def get_recent_block(rpc_url: str, blocks_ago: int = 10000) -> str:
    """Get a recent block number - reduced range for Alchemy limits"""
    current = rpc_call(rpc_url, "eth_blockNumber", [])
    if current:
        block_num = int(current, 16) - blocks_ago
        return hex(max(block_num, 0))
    return "0x0"


def decode_address_from_topic(topic: str) -> str:
    """Extract address from 32-byte topic"""
    if topic and len(topic) >= 66:
        return "0x" + topic[26:66]
    return None


def get_user_account_data(rpc_url: str, pool_address: str, user_address: str) -> dict:
    """
    Call getUserAccountData on Aave Pool
    Returns: totalCollateralBase, totalDebtBase, availableBorrowsBase, 
             currentLiquidationThreshold, ltv, healthFactor
    """
    # Function selector for getUserAccountData(address)
    func_selector = "0xbf92857c"
    # Pad address to 32 bytes
    padded_address = user_address[2:].lower().zfill(64)
    call_data = func_selector + padded_address
    
    params = [
        {"to": pool_address, "data": call_data},
        "latest"
    ]
    
    result = rpc_call(rpc_url, "eth_call", params)
    
    if result and len(result) >= 386:  # 0x + 6 * 64 chars
        try:
            # Each value is 32 bytes (64 hex chars)
            total_collateral = int(result[2:66], 16) / 1e8  # in USD (8 decimals)
            total_debt = int(result[66:130], 16) / 1e8
            available_borrows = int(result[130:194], 16) / 1e8
            liquidation_threshold = int(result[194:258], 16) / 10000
            ltv = int(result[258:322], 16) / 10000
            health_factor = int(result[322:386], 16) / 1e18
            
            return {
                "totalCollateralUSD": total_collateral,
                "totalDebtUSD": total_debt,
                "availableBorrowsUSD": available_borrows,
                "liquidationThreshold": liquidation_threshold,
                "ltv": ltv,
                "healthFactor": health_factor if health_factor < 1e10 else float('inf')
            }
        except Exception as e:
            pass
    
    return None


def fetch_borrowers_from_events(rpc_url: str, pool_address: str, limit: int = 300) -> set:
    """Fetch unique borrower addresses from Borrow events"""
    # Borrow event topic (Aave V3)
    borrow_topic = "0xb3d084820fb1a9decffb176436bd02558d15fac9b0ddfed8c465bc7359d7dce0"
    
    borrowers = set()
    
    # Get current block
    current_block = rpc_call(rpc_url, "eth_blockNumber", [])
    if not current_block:
        print("    Failed to get current block")
        return borrowers
    
    current = int(current_block, 16)
    
    # Query in smaller chunks (2000 blocks each) to avoid Alchemy limits
    chunk_size = 2000
    chunks_to_query = 5  # 5 chunks = 10,000 blocks total
    
    for i in range(chunks_to_query):
        from_block = current - (i + 1) * chunk_size
        to_block = current - i * chunk_size
        
        if from_block < 0:
            break
            
        print(f"    Fetching events: blocks {from_block} to {to_block}...")
        
        try:
            logs = get_logs(rpc_url, pool_address, [borrow_topic], hex(from_block), hex(to_block))
            
            if logs:
                for log in logs:
                    if len(log.get('topics', [])) >= 3:
                        user = decode_address_from_topic(log['topics'][2])
                        if user:
                            borrowers.add(user.lower())
                
                print(f"    Found {len(logs)} events, {len(borrowers)} unique borrowers so far")
            
            if len(borrowers) >= limit:
                break
                
        except Exception as e:
            print(f"    Error fetching chunk: {e}")
            continue
    
    print(f"    Total unique borrowers: {len(borrowers)}")
    return borrowers


def fetch_eth_price() -> float:
    """Fetch current ETH price from CoinGecko"""
    url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('ethereum', {}).get('usd', 2500)
    except:
        return 2500


def process_chain(chain: str, rpc_url: str, pool_address: str) -> dict:
    """Process positions for a single chain"""
    print(f"\n{'='*50}")
    print(f"Processing {chain.upper()}...")
    print(f"Pool: {pool_address}")
    
    positions = []
    
    # Get borrowers from events
    borrowers = fetch_borrowers_from_events(rpc_url, pool_address)
    
    if not borrowers:
        print(f"    No borrowers found")
        return {
            "positions": [],
            "meta": {
                "chain": chain,
                "timestamp": datetime.utcnow().isoformat(),
                "error": "No borrowers found"
            }
        }
    
    print(f"    Checking {len(borrowers)} addresses for qualifying positions...")
    
    checked = 0
    for user in borrowers:
        account_data = get_user_account_data(rpc_url, pool_address, user)
        
        if account_data:
            hf = account_data['healthFactor']
            collateral = account_data['totalCollateralUSD']
            debt = account_data['totalDebtUSD']
            liq_threshold = account_data['liquidationThreshold']
            
            # Apply filters
            if hf <= MAX_HEALTH_FACTOR and collateral >= MIN_COLLATERAL_USD and debt > 0:
                positions.append({
                    "address": user,
                    "healthFactor": round(hf, 4),
                    "collateralValue": round(collateral, 2),
                    "borrowValue": round(debt, 2),
                    "liquidationThreshold": round(liq_threshold, 4),
                    "collateralAsset": "Mixed",
                    "borrowAsset": "Mixed",
                    "collateralAmount": 1  # Placeholder for calculation
                })
        
        checked += 1
        if checked % 100 == 0:
            print(f"    Checked {checked}/{len(borrowers)}, found {len(positions)} qualifying")
    
    # Sort by health factor (lowest first = most risky)
    positions.sort(key=lambda x: x['healthFactor'])
    
    print(f"✅ {chain}: {len(positions)} positions (HF <= {MAX_HEALTH_FACTOR}, >= ${MIN_COLLATERAL_USD:,})")
    
    return {
        "positions": positions[:100],  # Top 100 most risky
        "meta": {
            "chain": chain,
            "timestamp": datetime.utcnow().isoformat(),
            "filters": {
                "maxHealthFactor": MAX_HEALTH_FACTOR,
                "minCollateralUsd": MIN_COLLATERAL_USD
            },
            "totalPositions": len(positions),
            "totalCollateralUsd": sum(p['collateralValue'] for p in positions),
            "totalBorrowUsd": sum(p['borrowValue'] for p in positions)
        }
    }


def main():
    print("🐋 Aave Whale Watch - Data Fetcher (Alchemy)")
    print("="*50)
    print(f"Timestamp: {datetime.utcnow().isoformat()}")
    
    # Check API Key
    if not ALCHEMY_API_KEY:
        print("⚠️  WARNING: ALCHEMY_API_KEY not set!")
        print("Please add ALCHEMY_API_KEY to GitHub Secrets")
        return
    
    print(f"✅ API Key configured: {ALCHEMY_API_KEY[:8]}...")
    
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Fetch ETH price
    eth_price = fetch_eth_price()
    print(f"\n💰 ETH Price: ${eth_price:,.2f}")
    
    # Process each chain
    summary = {
        'total_positions': 0,
        'total_collateral': 0,
        'total_borrow': 0,
        'chains': {}
    }
    
    for chain in RPC_URLS.keys():
        rpc_url = RPC_URLS[chain]
        pool_address = AAVE_POOL_ADDRESSES[chain]
        
        try:
            data = process_chain(chain, rpc_url, pool_address)
        except Exception as e:
            print(f"❌ Error processing {chain}: {e}")
            data = {
                "positions": [],
                "meta": {"chain": chain, "error": str(e)}
            }
        
        # Save to file
        output_path = os.path.join(OUTPUT_DIR, f"{chain}.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"💾 Saved to {output_path}")
        
        # Update summary
        summary['total_positions'] += len(data.get('positions', []))
        summary['total_collateral'] += data.get('meta', {}).get('totalCollateralUsd', 0)
        summary['total_borrow'] += data.get('meta', {}).get('totalBorrowUsd', 0)
        summary['chains'][chain] = {
            'positions': len(data.get('positions', [])),
            'collateral': data.get('meta', {}).get('totalCollateralUsd', 0),
            'borrow': data.get('meta', {}).get('totalBorrowUsd', 0)
        }
    
    # Print summary
    print("\n" + "="*50)
    print("📋 SUMMARY")
    print("="*50)
    print(f"Total Positions: {summary['total_positions']}")
    print(f"Total Collateral: ${summary['total_collateral']:,.2f}")
    print(f"Total Borrow: ${summary['total_borrow']:,.2f}")
    
    for chain, stats in summary['chains'].items():
        print(f"\n{chain.upper()}:")
        print(f"  Positions: {stats['positions']}")
        print(f"  Collateral: ${stats['collateral']:,.2f}")
        print(f"  Borrow: ${stats['borrow']:,.2f}")
    
    print("\n✅ Data fetch complete!")


if __name__ == "__main__":
    main()
