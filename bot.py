"""
Polymarket Arbitrage Bot Main Code
Detects and executes arbitrage opportunities when Yes/No ticket price sum is less than 1.0

Author: apemoonspin
Telegram: @apemoonspin
GitHub: apemoonspin
Twitter: @apemoonspin
"""
import time
import requests
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from web3 import Web3
from eth_account import Account

from config import (
    GAMMA_API_URL,
    CLOB_API_URL,
    MIN_PROFIT_MARGIN,
    SCAN_INTERVAL,
    MAX_MARKETS_TO_MONITOR,
    PRIVATE_KEY,
    POLYGON_RPC_URL,
    ENABLE_DATA_LOGGING,
    CSV_LOG_FILE,
    DB_LOG_FILE,
    MIN_TRADE_SIZE,
    MAX_SLIPPAGE,
    ENABLE_STRATEGY_5,
    STRATEGY_5_MAX_PRICE,
    STRATEGY_5_BET_SIZE,
    STRATEGY_5_MAX_MARKETS,
    STRATEGY_5_MIN_PROBABILITY
)
from data_logger import DataLogger


class PolyArbitrageBot:
    """Polymarket Arbitrage Bot"""
    
    def __init__(self, market_ids: Optional[List[str]] = None):
        """
        Args:
            market_ids: List of market IDs to monitor. If None, automatically discovers active markets
        """
        self.market_ids = market_ids or []
        self.min_profit_margin = MIN_PROFIT_MARGIN
        self.scan_interval = SCAN_INTERVAL
        
        # Initialize data logger
        self.logger = None
        if ENABLE_DATA_LOGGING:
            self.logger = DataLogger(CSV_LOG_FILE, DB_LOG_FILE)
        
        # Initialize Web3 (for actual trading)
        self.web3 = None
        self.account = None
        if PRIVATE_KEY:
            try:
                self.web3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))
                self.account = Account.from_key(PRIVATE_KEY)
                print(f"[✓] Wallet connected: {self.account.address}")
            except Exception as e:
                print(f"[!] Web3 initialization failed: {e}")
                print("[!] Running in data logging mode only.")
        
        # Strategy 5: Long-Shot Floor Buying tracking
        self.strategy_5_enabled = ENABLE_STRATEGY_5
        self.strategy_5_max_price = STRATEGY_5_MAX_PRICE
        self.strategy_5_bet_size = STRATEGY_5_BET_SIZE
        self.strategy_5_max_markets = STRATEGY_5_MAX_MARKETS
        self.strategy_5_min_probability = STRATEGY_5_MIN_PROBABILITY
        self.strategy_5_active_positions = {}  # Track active Strategy 5 positions
    
    def get_active_markets(self, limit: int = MAX_MARKETS_TO_MONITOR) -> List[Dict[str, Any]]:
        """Query active market list"""
        try:
            # Query active markets via Gamma API
            params = {
                'active': 'true',
                'closed': 'false',
                'limit': limit
            }
            response = requests.get(f"{GAMMA_API_URL}/markets", params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # API response may be returned directly as a list
            if isinstance(data, dict):
                market_list = data.get('data', [])
            else:
                market_list = data
            
            markets = []
            for market in market_list:
                # Handle default values if active and closed fields are missing
                is_active = market.get('active', True)
                is_closed = market.get('closed', False)
                
                if is_active and not is_closed:
                    markets.append({
                        'id': str(market.get('id', '')),
                        'question': market.get('question', ''),
                        'slug': market.get('slug', '')
                    })
            
            print(f"[✓] Found {len(markets)} active markets")
            return markets[:limit]
        
        except Exception as e:
            print(f"[✗] Failed to query market list: {e}")
            return []
    
    def get_market_orderbook(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Query market orderbook data (CLOB API)"""
        try:
            # Query orderbook via CLOB API
            response = requests.get(
                f"{CLOB_API_URL}/book",
                params={'market': market_id},
                timeout=5
            )
            response.raise_for_status()
            return response.json()
        
        except Exception as e:
            print(f"[✗] Failed to query orderbook ({market_id}): {e}")
            return None
    
    def get_market_prices(self, market_id: str) -> Optional[Dict[str, float]]:
        """Query Yes/No ticket prices for a market"""
        try:
            # Query market information via Gamma API
            response = requests.get(
                f"{GAMMA_API_URL}/markets/{market_id}",
                timeout=5
            )
            response.raise_for_status()
            market_data = response.json()
            
            # Also query orderbook data
            orderbook = self.get_market_orderbook(market_id)
            
            # Extract Yes/No ticket prices
            # May need adjustment based on actual API response structure
            yes_price = None
            no_price = None
            yes_ask = None
            no_ask = None
            yes_bid = None
            no_bid = None
            
            # Try extracting prices from Gamma API
            if 'outcomePrices' in market_data and 'outcomes' in market_data:
                import json
                # Parse if outcomePrices and outcomes are JSON strings
                prices_raw = market_data['outcomePrices']
                outcomes_raw = market_data['outcomes']
                
                if isinstance(prices_raw, str):
                    prices = json.loads(prices_raw)
                else:
                    prices = prices_raw
                
                if isinstance(outcomes_raw, str):
                    outcomes = json.loads(outcomes_raw)
                else:
                    outcomes = outcomes_raw
                
                if len(prices) >= 2 and len(outcomes) >= 2:
                    # Find Yes/No indices in outcomes list
                    for i, outcome in enumerate(outcomes):
                        if outcome == 'Yes' and i < len(prices):
                            yes_price = float(prices[i])
                        elif outcome == 'No' and i < len(prices):
                            no_price = float(prices[i])
            
            # Try extracting orderbook from CLOB API
            if orderbook:
                # Parsing needed based on actual CLOB API response structure
                # Example structure written here
                pass
            
            # Use default values if prices are missing (error handling needed in production)
            if yes_price is None or no_price is None:
                # Alternative: calculate directly from market data
                if 'tokens' in market_data:
                    tokens = market_data['tokens']
                    for token in tokens:
                        if token.get('outcome') == 'Yes':
                            yes_price = float(token.get('price', 0.5))
                        elif token.get('outcome') == 'No':
                            no_price = float(token.get('price', 0.5))
            
            if yes_price is None or no_price is None:
                return None
            
            return {
                'yes_price': yes_price,
                'no_price': no_price,
                'yes_ask': yes_ask or yes_price,
                'no_ask': no_ask or no_price,
                'yes_bid': yes_bid or yes_price,
                'no_bid': no_bid or no_price
            }
        
        except Exception as e:
            print(f"[✗] Failed to query prices ({market_id}): {e}")
            return None
    
    def check_arbitrage(self, yes_price: float, no_price: float) -> tuple[bool, float]:
        """
        Check for arbitrage opportunity
        
        Returns:
            (opportunity_exists, expected_profit_rate)
        """
        total_cost = yes_price + no_price
        if total_cost < (1.0 - self.min_profit_margin):
            profit = 1.0 - total_cost
            return True, profit
        return False, 0.0
    
    def check_strategy_5_opportunity(self, yes_price: float, no_price: float, market_id: str) -> tuple[bool, float]:
        """
        Strategy 5: Long-Shot Floor Buying
        Check if YES price is at floor level (very low) for long-shot betting
        
        Returns:
            (opportunity_exists, potential_upside_multiplier)
        """
        if not self.strategy_5_enabled:
            return False, 0.0
        
        # Check if YES price is below threshold (e.g., $0.001 = 0.1¢)
        if yes_price <= self.strategy_5_max_price and yes_price >= self.strategy_5_min_probability:
            # Calculate potential upside: if YES resolves, payout is $1, so multiplier is 1/yes_price
            upside_multiplier = 1.0 / yes_price if yes_price > 0 else 0.0
            
            # Only proceed if we haven't exceeded max markets limit
            if len(self.strategy_5_active_positions) < self.strategy_5_max_markets:
                return True, upside_multiplier
        
        return False, 0.0
    
    def execute_strategy_5_trade(self, market_id: str, yes_price: float, market_question: str = "") -> bool:
        """
        Strategy 5: Execute long-shot floor buying trade
        Places tiny bet on extremely low probability YES outcome
        """
        if not self.account or not self.web3:
            print("[!] Wallet not connected. Cannot execute Strategy 5 trades.")
            return False
        
        # Check if we already have a position in this market
        if market_id in self.strategy_5_active_positions:
            return False
        
        try:
            # Calculate bet size and potential payout
            bet_size = self.strategy_5_bet_size
            potential_payout = 1.0  # If YES resolves, payout is $1 per share
            shares_to_buy = bet_size / yes_price if yes_price > 0 else 0
            upside_multiplier = 1.0 / yes_price if yes_price > 0 else 0
            
            print(f"\n{'='*60}")
            print(f"[🎯 Strategy 5] Long-Shot Floor Buying Opportunity!")
            print(f"    Market: {market_question or market_id}")
            print(f"    YES price: ${yes_price:.6f} ({yes_price*100:.4f}¢)")
            print(f"    Bet size: ${bet_size:.4f}")
            print(f"    Shares to buy: {shares_to_buy:.2f}")
            print(f"    Potential payout if YES: ${potential_payout:.2f}")
            print(f"    Upside multiplier: {upside_multiplier:.1f}x")
            print(f"    Active positions: {len(self.strategy_5_active_positions)}/{self.strategy_5_max_markets}")
            print(f"{'='*60}\n")
            
            # Track position
            self.strategy_5_active_positions[market_id] = {
                'market_id': market_id,
                'market_question': market_question,
                'yes_price': yes_price,
                'bet_size': bet_size,
                'shares': shares_to_buy,
                'entry_time': datetime.now().isoformat(),
                'potential_payout': potential_payout
            }
            
            # Actual implementation: Place order via CLOB API
            # from py_clob_client.client import ClobClient
            # client = ClobClient(...)
            # order = client.create_order(
            #     market=market_id,
            #     side='BUY',
            #     size=shares_to_buy,
            #     price=yes_price,
            #     order_type='LIMIT'
            # )
            
            return True
        
        except Exception as e:
            print(f"[✗] Strategy 5 trade execution failed: {e}")
            return False
    
    def get_strategy_5_statistics(self) -> Dict[str, Any]:
        """
        Get Strategy 5 statistics
        Returns summary of active positions and performance
        """
        if not self.strategy_5_enabled:
            return {}
        
        total_positions = len(self.strategy_5_active_positions)
        total_invested = sum(pos['bet_size'] for pos in self.strategy_5_active_positions.values())
        avg_yes_price = sum(pos['yes_price'] for pos in self.strategy_5_active_positions.values()) / total_positions if total_positions > 0 else 0
        avg_upside_multiplier = sum(1.0 / pos['yes_price'] for pos in self.strategy_5_active_positions.values()) / total_positions if total_positions > 0 else 0
        
        return {
            'total_positions': total_positions,
            'max_positions': self.strategy_5_max_markets,
            'total_invested': total_invested,
            'avg_yes_price': avg_yes_price,
            'avg_upside_multiplier': avg_upside_multiplier,
            'bet_size': self.strategy_5_bet_size
        }
    
    def execute_trade(self, market_id: str, yes_price: float, no_price: float) -> bool:
        """
        Execute arbitrage trade
        
        For actual implementation:
        1. Sign and send orders via CLOB API
        2. Send transactions via Web3
        3. Check order status and slippage
        
        Currently in simulation mode
        """
        if not self.account or not self.web3:
            print("[!] Wallet not connected. Cannot execute trades.")
            return False
        
        try:
            # Actual implementation example:
            # 1. Create Yes ticket buy order
            # 2. Create No ticket buy order
            # 3. Send both orders simultaneously (Atomic Arbitrage)
            # 4. Check order status
            
            print(f"[*] Trade execution simulation:")
            print(f"    Market ID: {market_id}")
            print(f"    Yes ticket buy: ${yes_price:.4f}")
            print(f"    No ticket buy: ${no_price:.4f}")
            print(f"    Total cost: ${yes_price + no_price:.4f}")
            print(f"    Expected profit: ${1.0 - (yes_price + no_price):.4f}")
            
            # Add CLOB API call code here for actual implementation
            # from py_clob_client.client import ClobClient
            # client = ClobClient(...)
            # client.create_order(...)
            
            return True
        
        except Exception as e:
            print(f"[✗] Trade execution failed: {e}")
            return False
    
    def monitor_market(self, market_id: str, market_question: str = ""):
        """Monitor single market"""
        prices = self.get_market_prices(market_id)
        
        if not prices:
            return False
        
        yes_price = prices['yes_price']
        no_price = prices['no_price']
        
        # Data logging
        if self.logger:
            self.logger.log_price_data(
                market_id=market_id,
                market_question=market_question,
                yes_price=yes_price,
                no_price=no_price,
                yes_ask=prices.get('yes_ask'),
                no_ask=prices.get('no_ask'),
                yes_bid=prices.get('yes_bid'),
                no_bid=prices.get('no_bid'),
                min_profit_margin=self.min_profit_margin
            )
        
        # Check for arbitrage opportunity (Strategy 2)
        has_opportunity, profit = self.check_arbitrage(yes_price, no_price)
        
        if has_opportunity:
            print(f"\n{'='*60}")
            print(f"[🎯] Arbitrage opportunity found!")
            print(f"    Market: {market_question or market_id}")
            print(f"    Yes price: ${yes_price:.4f}")
            print(f"    No price: ${no_price:.4f}")
            print(f"    Total cost: ${yes_price + no_price:.4f}")
            print(f"    Expected profit: ${profit:.4f} ({profit*100:.2f}%)")
            print(f"{'='*60}\n")
            
            # Execute trade
            if self.account:
                self.execute_trade(market_id, yes_price, no_price)
        
        # Check for Strategy 5: Long-Shot Floor Buying opportunity
        if self.strategy_5_enabled:
            has_strategy_5, upside_multiplier = self.check_strategy_5_opportunity(yes_price, no_price, market_id)
            
            if has_strategy_5:
                # Execute Strategy 5 trade
                if self.account:
                    self.execute_strategy_5_trade(market_id, yes_price, market_question)
        
        return has_opportunity
    
    def run(self):
        """Bot execution main loop"""
        print("="*60)
        print("Polymarket Arbitrage Bot Starting")
        print("="*60)
        
        # Get market list
        if not self.market_ids:
            print("[*] Searching for active markets...")
            markets = self.get_active_markets()
            self.market_ids = [m['id'] for m in markets]
            market_questions = {m['id']: m['question'] for m in markets}
        else:
            market_questions = {mid: "" for mid in self.market_ids}
        
        if not self.market_ids:
            print("[✗] No markets to monitor.")
            return
        
        print(f"[✓] Starting to monitor {len(self.market_ids)} markets")
        print(f"[*] Minimum profit rate: {self.min_profit_margin*100:.1f}%")
        print(f"[*] Scan interval: {self.scan_interval} seconds")
        print(f"[*] Data logging: {'Enabled' if ENABLE_DATA_LOGGING else 'Disabled'}")
        if self.strategy_5_enabled:
            print(f"[*] Strategy 5 (Long-Shot Floor Buying): Enabled")
            print(f"    Max YES price: ${self.strategy_5_max_price:.6f}")
            print(f"    Bet size: ${self.strategy_5_bet_size:.4f}")
            print(f"    Max markets: {self.strategy_5_max_markets}")
        print("-"*60)
        
        try:
            while True:
                opportunities_found = 0
                
                for market_id in self.market_ids:
                    try:
                        if self.monitor_market(market_id, market_questions.get(market_id, "")):
                            opportunities_found += 1
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        print(f"[✗] Market monitoring error ({market_id}): {e}")
                        continue
                
                # Output statistics (periodically)
                if self.logger and opportunities_found == 0:
                    # Output statistics every 10 minutes
                    if int(time.time()) % 600 == 0:
                        stats = self.logger.get_arbitrage_statistics(hours=24)
                        if stats['total_opportunities'] > 0:
                            print(f"\n[📊] Last 24 hours statistics:")
                            print(f"    Arbitrage opportunities: {stats['total_opportunities']}")
                            print(f"    Average profit rate: {stats['avg_profit']*100:.2f}%")
                            print(f"    Maximum profit rate: {stats['max_profit']*100:.2f}%")
                            print(f"    Unique markets: {stats['unique_markets']}\n")
                        
                        # Strategy 5 statistics
                        if self.strategy_5_enabled:
                            strategy_5_stats = self.get_strategy_5_statistics()
                            if strategy_5_stats.get('total_positions', 0) > 0:
                                print(f"[📊] Strategy 5 (Long-Shot Floor Buying) statistics:")
                                print(f"    Active positions: {strategy_5_stats['total_positions']}/{strategy_5_stats['max_positions']}")
                                print(f"    Total invested: ${strategy_5_stats['total_invested']:.2f}")
                                print(f"    Average YES price: ${strategy_5_stats['avg_yes_price']:.6f}")
                                print(f"    Average upside multiplier: {strategy_5_stats['avg_upside_multiplier']:.1f}x\n")
                
                time.sleep(self.scan_interval)
        
        except KeyboardInterrupt:
            print("\n\n[*] Shutting down bot...")
            if self.logger:
                stats = self.logger.get_arbitrage_statistics(hours=24)
                print(f"\n[📊] Final statistics:")
                print(f"    Arbitrage opportunities: {stats['total_opportunities']}")
                print(f"    Average profit rate: {stats['avg_profit']*100:.2f}%")
            if self.strategy_5_enabled and self.strategy_5_active_positions:
                print(f"\n[📊] Strategy 5 positions:")
                print(f"    Active positions: {len(self.strategy_5_active_positions)}")
                total_invested = sum(pos['bet_size'] for pos in self.strategy_5_active_positions.values())
                print(f"    Total invested: ${total_invested:.2f}")
            print("[✓] Bot shutdown complete")


if __name__ == "__main__":
    # Usage example
    # To monitor specific markets only:
    # bot = PolyArbitrageBot(market_ids=["market-id-1", "market-id-2"])
    
    # Monitor all active markets:
    bot = PolyArbitrageBot()
    bot.run()
