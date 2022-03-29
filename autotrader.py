# Copyright 2021 Optiver Asia Pacific Pty. Ltd.
#
# This file is part of Ready Trader Go.
#
#     Ready Trader Go is free software: you can redistribute it and/or
#     modify it under the terms of the GNU Affero General Public License
#     as published by the Free Software Foundation, either version 3 of
#     the License, or (at your option) any later version.
#
#     Ready Trader Go is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU Affero General Public License for more details.
#
#     You should have received a copy of the GNU Affero General Public
#     License along with Ready Trader Go.  If not, see
#     <https://www.gnu.org/licenses/>.
import asyncio
from cmath import exp
import itertools

from typing import List
from time import sleep
from ready_trader_go import BaseAutoTrader, Instrument, Lifespan, MAXIMUM_ASK, MINIMUM_BID, Side


LOT_SIZE = 10
POSITION_LIMIT = 100
TICK_SIZE_IN_CENTS = 100


class AutoTrader(BaseAutoTrader):

    """Example Auto-trader.

    When it starts this auto-trader places ten-lot bid and ask orders at the
    current best-bid and best-ask prices respectively. Thereafter, if it has
    a long position (it has bought more lots than it has sold) it reduces its
    bid and ask prices. Conversely, if it has a short position (it has sold
    more lots than it has bought) then it increases its bid and ask prices.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, team_name: str, secret: str):
        """Initialise a new instance of the AutoTrader class."""
        super().__init__(loop, team_name, secret)
        self.order_ids = itertools.count(1)
        self.bids = set()
        self.asks = set()
        self.ask_id = self.ask_price = self.bid_id = self.bid_price = self.position = 0
        self.theo = 0
        self.ask_offset = 1
        self.bid_offset = 1
        self.ask_volume = 0
        self.bid_volume = 0
    

    def on_error_message(self, client_order_id: int, error_message: bytes) -> None:
        """Called when the exchange detects an error.

        If the error pertains to a particular order, then the client_order_id
        will identify that order, otherwise the client_order_id will be zero.
        """
        self.logger.warning("error with order %d: %s", client_order_id, error_message.decode())
        if client_order_id != 0:
            self.on_order_status_message(client_order_id, 0, 0, 0)

    def on_hedge_filled_message(self, client_order_id: int, price: int, volume: int) -> None:
        """Called when one of your hedge orders is filled, partially or fully.

        The price is the average price at which the order was (partially) filled,
        which may be better than the order's limit price. The volume is
        the number of lots filled at that price.

        If the order was unsuccessful, both the price and volume will be zero.
        """
        self.logger.info("received hedge filled for order %d with average price %d and volume %d", client_order_id,
                         price, volume)

    def round100(self, value):
        return 100 * round(value / 100)

    def mid_price(self, bid, ask):
        return self.round100(0.5 * (bid + ask))

    def weight(self, distance):
        return exp(-1 * distance).real
    
    
        

    def rwp(self, ask_prices, ask_volumes, bid_prices, bid_volumes):

        if(ask_prices[0] == 0):
            return 0

        weight_sum = 0
        sum = 0

        bid = bid_prices[0]
        ask = ask_prices[0]
        for i in range(1):
            
            bid_volume = bid_volumes[i]
            ask_volume = ask_volumes[i]

            bid_depth = i #bid - bid_prices[i]
            ask_depth = i #ask_prices[i] - ask

            inverted_bid = ask + bid_depth
            inverted_ask = bid - ask_depth

            bid_weight = self.weight(bid_depth)
            ask_weight = self.weight(ask_depth)

            weight_sum += bid_volume * bid_weight + ask_volume * ask_weight
            sum += bid_volume * bid_weight * inverted_bid + \
                ask_volume * ask_weight * inverted_ask
 
        return self.round100(sum / weight_sum)

    # returns a tuple containing 
    #    1. the total value traded
    #    2. the total volume traded
    def total_trade(self, prices, volumes, volume):
        total_value = 0
        total_volume = 0
        for i in range(5):
            if(volumes[i] <= volume):
                total_value += volumes[i] * prices[i]
                total_volume += volumes[i]
                volume -= volumes[i]
            else:
                total_value += volume * prices[i]
                total_volume += volume
                break        

            if(volume == 0):
                break

        return (total_value, total_volume)

    def explode_market(self, ticks):

        # first, cancel our orders
        self.send_cancel_order(self.bid_id)
        self.bid_id = 0
        self.send_cancel_order(self.ask_id)
        self.ask_id = 0

        # now, every 0.05 seconds, send a market order on each side of the book
        for i in range(ticks):

            self.send_insert_order(next(self.order_ids), Side.ASK, MINIMUM_BID, 1)
            self.send_insert_order(next(self.order_ids), Side.BID,
                                  MAXIMUM_ASK//TICK_SIZE_IN_CENTS*TICK_SIZE_IN_CENTS, 1)
            sleep(0.05)
            

        
    def on_order_book_update_message(self, instrument: int, sequence_number: int, ask_prices: List[int],
                                     ask_volumes: List[int], bid_prices: List[int], bid_volumes: List[int]) -> None:
        """Called periodically to report the status of an order book.

        The sequence number can be used to detect missed or out-of-order
        messages. The five best available ask (i.e. sell) and bid (i.e. buy)
        prices are reported along with the volume available at each of those
        price levels.
        """
        self.logger.info("received order book for instrument %d with sequence number %d", instrument,
                         sequence_number)

        if(ask_volumes[0] == 0 or bid_volumes[0] == 0):
            return 
        if instrument == Instrument.FUTURE:
            self.theo = self.rwp(ask_prices, ask_volumes, bid_prices, bid_volumes)
            #self.theo = self.mid_price(bid_prices[0], ask_prices[0])        
            
            self.logger.info("Current position: %d", self.position)
            new_bid_volume = 40
            if(self.position > 60):
                diff = (self.position - 60)
                new_bid_volume = 40 - diff
                new_ask_volume = 40 + diff
            new_ask_volume = 40
            if(self.position < -60):
                diff = (-self.position - 60)
                new_ask_volume = 40 - diff
                new_bid_volume = 40 + diff

            self.bid_volume = new_bid_volume
            self.ask_volume = new_ask_volume

            hit_volume = ( self.position + (POSITION_LIMIT - new_ask_volume))
            if(hit_volume > 0 and self.theo != 0):
                client_id = next(self.order_ids)
                self.logger.info("Hitting (SELL): volume %d", hit_volume)
                self.send_insert_order(client_id, Side.SELL, self.theo+4*(TICK_SIZE_IN_CENTS), hit_volume, Lifespan.GOOD_FOR_DAY)
                self.send_cancel_order(client_id)
                self.asks.add(client_id)

            
            hit_volume = ( (POSITION_LIMIT - new_bid_volume) - self.position)
            if(hit_volume > 0 and self.theo != 0):
                client_id = next(self.order_ids)
                self.logger.info("Hitting (BUY): volume %d", hit_volume)
                self.send_insert_order(client_id, Side.BUY, self.theo-4*(TICK_SIZE_IN_CENTS), hit_volume, Lifespan.GOOD_FOR_DAY)
                self.send_cancel_order(client_id)
                self.bids.add(client_id)

            
            bid_adjustement = self.round100(max(1, 3  + self.position / 50) * TICK_SIZE_IN_CENTS)
            ask_adjustement = self.round100(max(1, 3  - self.position / 50) * TICK_SIZE_IN_CENTS)
            new_bid_price = self.theo - bid_adjustement if bid_prices[0] != 0 else 0
            new_ask_price = self.theo + ask_adjustement if ask_prices[0] != 0 else 0


            if (self.bid_id != 0 and new_bid_price not in (self.bid_price, 0)) or self.position > (POSITION_LIMIT - 2*LOT_SIZE):
                self.send_cancel_order(self.bid_id)
                self.bid_id = 0
            if (self.ask_id != 0 and new_ask_price not in (self.ask_price, 0)) or self.position < -(POSITION_LIMIT - 2*LOT_SIZE):
                self.send_cancel_order(self.ask_id)
                self.ask_id = 0

            if self.bid_id == 0 and new_bid_price != 0 and self.position < (POSITION_LIMIT):
                self.bid_id = next(self.order_ids)
                self.bid_price = new_bid_price
                self.logger.info("Quoting (BUY): volume %d", new_bid_volume)
                self.send_insert_order(self.bid_id, Side.BUY, new_bid_price, new_bid_volume, Lifespan.GOOD_FOR_DAY)
                self.bids.add(self.bid_id)

            if self.ask_id == 0 and new_ask_price != 0 and self.position > -(POSITION_LIMIT):
                self.ask_id = next(self.order_ids)
                self.ask_price = new_ask_price
                self.logger.info("Quoting (SELL): volume %d", new_ask_volume)
                self.send_insert_order(self.ask_id, Side.SELL, new_ask_price, new_ask_volume, Lifespan.GOOD_FOR_DAY)
                self.asks.add(self.ask_id)
        else:
            # first, 
            # hit anything that is mispriced
            '''
            if(bid_prices[0] > self.theo + 4*(TICK_SIZE_IN_CENTS)):
                hit_volume = self.position + (POSITION_LIMIT - 40)
                if(hit_volume > 0):
                    client_id = next(self.order_ids)
                    self.send_insert_order(client_id, Side.SELL, self.theo, hit_volume, Lifespan.FILL_AND_KILL)
                    self.asks.add(client_id)

            if(ask_prices[0] < self.theo - 4*(TICK_SIZE_IN_CENTS)):
                hit_volume = (POSITION_LIMIT - 40) - self.position
                if(hit_volume > 0):
                    client_id = next(self.order_ids)
                    self.send_insert_order(client_id, Side.BUY, self.theo, hit_volume, Lifespan.FILL_AND_KILL)
                    self.bids.add(client_id)

            '''

    def on_order_filled_message(self, client_order_id: int, price: int, volume: int) -> None:
        """Called when when of your orders is filled, partially or fully.

        The price is the price at which the order was (partially) filled,
        which may be better than the order's limit price. The volume is
        the number of lots filled at that price.
        """
        self.logger.info("received order filled for order %d with price %d and volume %d", client_order_id,
                         price, volume)
        if client_order_id in self.bids:
            self.position += volume
            self.send_hedge_order(next(self.order_ids), Side.ASK, MINIMUM_BID, volume)
        elif client_order_id in self.asks:
            self.position -= volume
            self.send_hedge_order(next(self.order_ids), Side.BID,
                                  MAXIMUM_ASK//TICK_SIZE_IN_CENTS*TICK_SIZE_IN_CENTS, volume)

    def on_order_status_message(self, client_order_id: int, fill_volume: int, remaining_volume: int,
                                fees: int) -> None:
        """Called when the status of one of your orders changes.

        The fill_volume is the number of lots already traded, remaining_volume
        is the number of lots yet to be traded and fees is the total fees for
        this order. Remember that you pay fees for being a market taker, but
        you receive fees for being a market maker, so fees can be negative.

        If an order is cancelled its remaining volume will be zero.
        """
        self.logger.info("received order status for order %d with fill volume %d remaining %d and fees %d",
                         client_order_id, fill_volume, remaining_volume, fees)
        if remaining_volume == 0:
            if client_order_id == self.bid_id:
                self.bid_id = 0
            elif client_order_id == self.ask_id:
                self.ask_id = 0

            # It could be either a bid or an ask
            self.bids.discard(client_order_id)
            self.asks.discard(client_order_id)

    def on_trade_ticks_message(self, instrument: int, sequence_number: int, ask_prices: List[int],
                               ask_volumes: List[int], bid_prices: List[int], bid_volumes: List[int]) -> None:
        """Called periodically when there is trading activity on the market.

        The five best ask (i.e. sell) and bid (i.e. buy) prices at which there
        has been trading activity are reported along with the aggregated volume
        traded at each of those price levels.

        If there are less than five prices on a side, then zeros will appear at
        the end of both the prices and volumes arrays.
        """
        self.logger.info("received trade ticks for instrument %d with sequence number %d", instrument,
                         sequence_number)

        
        if(instrument == Instrument.FUTURE):
 
            if(bid_prices[0] or ask_prices[0]):
                return
            self.theo = self.mid_price(bid_prices[0], ask_prices[0])

            # delete any of our quotes if not priced well
            if(self.theo - self.bid_price < -1*(TICK_SIZE_IN_CENTS) and self.bid_id!=0):
                self.send_cancel_order(self.bid_id)
                self.bid_id = 0
            if(self.ask_price - self.theo < -1*(TICK_SIZE_IN_CENTS) and self.ask_id!=0):
                self.send_cancel_order(self.ask_id)
                self.ask_id = 0


            hit_volume = min(10, self.position + (POSITION_LIMIT - self.ask_volume))
            if(hit_volume > 0 and self.theo != 0):
                client_id = next(self.order_ids)
                self.send_insert_order(client_id, Side.SELL, self.theo+2*(TICK_SIZE_IN_CENTS), hit_volume, Lifespan.FILL_AND_KILL)
                
                self.asks.add(client_id)

            
            hit_volume = min(10, POSITION_LIMIT - (self.bid_volume - self.position))
            if(hit_volume > 0 and self.theo != 0):
                client_id = next(self.order_ids)
                self.send_insert_order(client_id, Side.BUY, self.theo-2*(TICK_SIZE_IN_CENTS), hit_volume, Lifespan.FILL_AND_KILL)
              
                self.bids.add(client_id)


            '''
            bid_adjustement = self.round100(max(1, 3  + self.position / 50) * TICK_SIZE_IN_CENTS)
            ask_adjustement = self.round100(max(1, 3  - self.position / 50) * TICK_SIZE_IN_CENTS)
            new_bid_price = self.theo - bid_adjustement if bid_prices[0] != 0 else 0
            new_ask_price = self.theo + ask_adjustement if ask_prices[0] != 0 else 0

            new_bid_volume = 40
            if(self.position > 60):
                diff = (self.position - 60)
                new_bid_volume = 40 - diff
                new_ask_volume = 40 + diff
            new_ask_volume = 40
            if(self.position < -60):
                diff = (-self.position - 60)
                new_ask_volume = 40 - diff
                new_bid_volume = 40 + diff

            if self.bid_id == 0 and new_bid_price != 0 and self.position < (POSITION_LIMIT - hit_volume):
                self.bid_id = next(self.order_ids)
                self.bid_price = new_bid_price
                self.send_insert_order(self.bid_id, Side.BUY, new_bid_price, new_bid_volume, Lifespan.GOOD_FOR_DAY)
                self.bids.add(self.bid_id)

            if self.ask_id == 0 and new_ask_price != 0 and self.position > -(POSITION_LIMIT - hit_volume):
                self.ask_id = next(self.order_ids)
                self.ask_price = new_ask_price
                self.send_insert_order(self.ask_id, Side.SELL, new_ask_price, new_ask_volume, Lifespan.GOOD_FOR_DAY)
                self.asks.add(self.ask_id)
            '''