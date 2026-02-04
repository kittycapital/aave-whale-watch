"""
🐋 Aave Whale Watch - Data Fetcher
The Graph를 통해 Aave V3 포지션 데이터 수집

Health Factor <= 1.5 & 담보 >= $200K 필터링
"""

import json
import os
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ===== Configuration =====
# The Graph Decentralized Network (requires API key)
API_KEY = os.environ.get('GRAPH_API_KEY', '')

# Subgraph IDs for Aave V3
SUBGRAPH_IDS = {
    "ethereum": "JCNWRypm7FYwV8fx5HhzZPSFaMxgkPuw4TnR3Gpi81zk",
    "arbitrum": "4xyasjQeREe7PxnF6wVdobZvCw5mhoHZq3T7guRpuNPf",
    "polygon": "6yuf1C49aWEscgk5n9D1DekeG1BCk5Z9imJYJT3sVmAT",
    "base": "GQFbb95cE6d8mV989mL5figjaGaKCQB3xqYrr1bRyXqF"
}

BASE_URL = "https://gateway.thegraph.com/api/subgraphs/id"

# Thresholds
MAX_HEALTH_FACTOR = 1.5
MIN_COLLATERAL_USD = 200000  # $200K

OUTPUT_DIR = "data"


# ===== GraphQL Query =====
POSITIONS_QUERY = """
query GetRiskyPositions($minCollateral: BigDecimal!, $maxHF: BigDecimal!, $skip: Int!) {
  users(
    first: 1000
    skip: $skip
    where: {
      borrowedReservesCount_gt: 0
    }
    orderBy: id
    orderDirection: asc
  ) {
    id
    reserves(where: { currentATokenBalance_gt: "0" }) {
      currentATokenBalance
      currentTotalDebt
      reserve {
        symbol
        decimals
        price {
          priceInEth
        }
        reserveLiquidationThreshold
      }
    }
  }
  _meta {
    block {
      number
      timestamp
    }
  }
}
"""

# Simplified query for positions
SIMPLE_QUERY = """
{
  users(
    first: 500
    where: { borrowedReservesCount_gt: 0 }
    orderBy: id
  ) {
    id
    reserves {
      currentATokenBalance
      currentTotalDebt
      reserve {
        symbol
        decimals
        price {
          priceInEth
        }
        reserveLiquidationThreshold
      }
    }
  }
  _meta {
    block {
      number
    }
  }
}
"""


def fetch_graphql(url: str, query: str, variables: dict = None) -> dict:
    """Execute GraphQL query"""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    data = json.dumps(payload).encode('utf-8')
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    
    req = Request(url, data=data, headers=headers, method='POST')
    
    try:
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        return None
    except URLError as e:
        print(f"URL Error: {e.reason}")
        return None
    except Exception as e:
        print(f"Error: {str(e)}")
        return None


def calculate_health_factor(collateral_eth: float, debt_eth: float, liq_threshold: float) -> float:
    """
    Calculate Health Factor
    HF = (Collateral * Liquidation Threshold) / Debt
    """
    if debt_eth == 0:
        return float('inf')
    return (collateral_eth * liq_threshold) / debt_eth


def process_user_data(users: list, eth_price_usd: float = 3000) -> list:
    """Process raw user data into position format"""
    positions = []
    
    for user in users:
        try:
            # Calculate totals
            total_collateral_eth = 0
            total_debt_eth = 0
            weighted_liq_threshold = 0
            
            collateral_assets = []
            borrow_assets = []
            
            for reserve in user.get('reserves', []):
                res_info = reserve.get('reserve', {})
                symbol = res_info.get('symbol', 'Unknown')
                decimals = int(res_info.get('decimals', 18))
                price_in_eth = float(res_info.get('price', {}).get('priceInEth', 0)) / 1e18
                liq_threshold = float(res_info.get('reserveLiquidationThreshold', 0)) / 10000
                
                # Collateral
                atoken_balance = float(reserve.get('currentATokenBalance', 0)) / (10 ** decimals)
                collateral_eth = atoken_balance * price_in_eth
                
                if collateral_eth > 0:
                    collateral_assets.append({
                        'symbol': symbol,
                        'amount': atoken_balance,
                        'valueEth': collateral_eth,
                        'valueUsd': collateral_eth * eth_price_usd,
                        'liqThreshold': liq_threshold
                    })
                    total_collateral_eth += collateral_eth
                    weighted_liq_threshold += collateral_eth * liq_threshold
                
                # Debt
                total_debt = float(reserve.get('currentTotalDebt', 0)) / (10 ** decimals)
                debt_eth = total_debt * price_in_eth
                
                if debt_eth > 0:
                    borrow_assets.append({
                        'symbol': symbol,
                        'amount': total_debt,
                        'valueEth': debt_eth,
                        'valueUsd': debt_eth * eth_price_usd
                    })
                    total_debt_eth += debt_eth
            
            # Skip if no debt
            if total_debt_eth == 0:
                continue
            
            # Calculate average liquidation threshold
            avg_liq_threshold = weighted_liq_threshold / total_collateral_eth if total_collateral_eth > 0 else 0.8
            
            # Calculate health factor
            health_factor = calculate_health_factor(total_collateral_eth, total_debt_eth, avg_liq_threshold)
            
            # Convert to USD
            collateral_usd = total_collateral_eth * eth_price_usd
            debt_usd = total_debt_eth * eth_price_usd
            
            # Apply filters
            if health_factor > MAX_HEALTH_FACTOR:
                continue
            if collateral_usd < MIN_COLLATERAL_USD:
                continue
            
            # Get primary assets
            primary_collateral = max(collateral_assets, key=lambda x: x['valueUsd'])['symbol'] if collateral_assets else 'Unknown'
            primary_borrow = max(borrow_assets, key=lambda x: x['valueUsd'])['symbol'] if borrow_assets else 'Unknown'
            
            # Get primary collateral details for liquidation price calculation
            primary_collateral_data = max(collateral_assets, key=lambda x: x['valueUsd']) if collateral_assets else {}
            collateral_amount = primary_collateral_data.get('amount', 0)
            liq_threshold = primary_collateral_data.get('liqThreshold', 0.8)
            
            positions.append({
                'address': user['id'],
                'healthFactor': round(health_factor, 4),
                'collateralValue': round(collateral_usd, 2),
                'collateralAmount': round(collateral_amount, 6),
                'collateralAsset': primary_collateral,
                'borrowValue': round(debt_usd, 2),
                'borrowAsset': primary_borrow,
                'liquidationThreshold': round(liq_threshold, 4),
                'collateralAssets': collateral_assets,
                'borrowAssets': borrow_assets
            })
            
        except Exception as e:
            print(f"Error processing user {user.get('id', 'unknown')}: {e}")
            continue
    
    return positions


def fetch_eth_price() -> float:
    """Fetch current ETH price from CoinGecko (free API)"""
    url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
    
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('ethereum', {}).get('usd', 3000)
    except Exception as e:
        print(f"Failed to fetch ETH price, using default: {e}")
        return 3000  # Default fallback


def fetch_chain_data(chain: str, url: str, eth_price: float) -> dict:
    """Fetch and process data for a single chain"""
    print(f"\n{'='*50}")
    print(f"Fetching {chain.upper()} data...")
    print(f"URL: {url}")
    
    result = fetch_graphql(url, SIMPLE_QUERY)
    
    if not result or 'data' not in result:
        print(f"❌ Failed to fetch {chain} data")
        if result and 'errors' in result:
            print(f"Errors: {result['errors']}")
        return {
            'positions': [],
            'meta': {
                'chain': chain,
                'error': 'Failed to fetch data',
                'timestamp': datetime.utcnow().isoformat()
            }
        }
    
    users = result['data'].get('users', [])
    block_info = result['data'].get('_meta', {}).get('block', {})
    
    print(f"📊 Raw users fetched: {len(users)}")
    
    positions = process_user_data(users, eth_price)
    
    print(f"✅ Filtered positions (HF <= {MAX_HEALTH_FACTOR}, >= ${MIN_COLLATERAL_USD:,}): {len(positions)}")
    
    return {
        'positions': positions,
        'meta': {
            'chain': chain,
            'blockNumber': block_info.get('number'),
            'timestamp': datetime.utcnow().isoformat(),
            'ethPriceUsd': eth_price,
            'filters': {
                'maxHealthFactor': MAX_HEALTH_FACTOR,
                'minCollateralUsd': MIN_COLLATERAL_USD
            },
            'totalPositions': len(positions),
            'totalCollateralUsd': sum(p['collateralValue'] for p in positions),
            'totalBorrowUsd': sum(p['borrowValue'] for p in positions)
        }
    }


def main():
    print("🐋 Aave Whale Watch - Data Fetcher")
    print("="*50)
    print(f"Timestamp: {datetime.utcnow().isoformat()}")
    
    # Check API Key
    if not API_KEY:
        print("⚠️  WARNING: GRAPH_API_KEY not set!")
        print("Please set the environment variable GRAPH_API_KEY")
        return
    
    print(f"✅ API Key configured: {API_KEY[:8]}...")
    
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Fetch ETH price
    eth_price = fetch_eth_price()
    print(f"\n💰 ETH Price: ${eth_price:,.2f}")
    
    # Fetch data for each chain
    summary = {
        'total_positions': 0,
        'total_collateral': 0,
        'total_borrow': 0,
        'chains': {}
    }
    
    for chain, subgraph_id in SUBGRAPH_IDS.items():
        url = f"{BASE_URL}/{subgraph_id}"
        data = fetch_chain_data(chain, url, eth_price)
        
        # Save to file
        output_path = os.path.join(OUTPUT_DIR, f"{chain}.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"💾 Saved to {output_path}")
        
        # Update summary
        summary['total_positions'] += len(data['positions'])
        summary['total_collateral'] += data['meta'].get('totalCollateralUsd', 0)
        summary['total_borrow'] += data['meta'].get('totalBorrowUsd', 0)
        summary['chains'][chain] = {
            'positions': len(data['positions']),
            'collateral': data['meta'].get('totalCollateralUsd', 0),
            'borrow': data['meta'].get('totalBorrowUsd', 0)
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
