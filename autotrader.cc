
// Copyright 2021 Optiver Asia Pacific Pty. Ltd.
//
// This file is part of Ready Trader Go.
//
//     Ready Trader Go is free software: you can redistribute it and/or
//     modify it under the terms of the GNU Affero General Public License
//     as published by the Free Software Foundation, either version 3 of
//     the License, or (at your option) any later version.
//
//     Ready Trader Go is distributed in the hope that it will be useful,
//     but WITHOUT ANY WARRANTY; without even the implied warranty of
//     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
//     GNU Affero General Public License for more details.
//
//     You should have received a copy of the GNU Affero General Public
//     License along with Ready Trader Go.  If not, see
//     <https://www.gnu.org/licenses/>.
#include <array>

#include <boost/asio/io_context.hpp>

#include <ready_trader_go/logging.h>

#include "autotrader.h"

using namespace ReadyTraderGo;

RTG_INLINE_GLOBAL_LOGGER_WITH_CHANNEL(LG_AT, "AUTO")

constexpr int TICK_SIZE_IN_CENTS = 100;
float theo = 0;
int ask_volume = 0;
int bid_volume = 0;
int tick_since_last_bid = 0;
int tick_since_last_ask = 0;
CancelMessage bidCancel;
CancelMessage askCancel;


float mid_price(unsigned long bidPrice, unsigned long askPrice) {
    return 0.5 * (bidPrice + askPrice);
}

AutoTrader::AutoTrader(boost::asio::io_context& context) : BaseAutoTrader(context)
{
}

void AutoTrader::DisconnectHandler()
{
    BaseAutoTrader::DisconnectHandler();
    RLOG(LG_AT, LogLevel::LL_INFO) << "execution connection lost";
}

void AutoTrader::ErrorMessageHandler(unsigned long clientOrderId,
                                     const std::string& errorMessage)
{
    RLOG(LG_AT, LogLevel::LL_INFO) << "error with order " << clientOrderId << ": " << errorMessage;
    if (clientOrderId != 0)
    {
        OrderStatusMessageHandler(clientOrderId, 0, 0, 0);
    }
}

void AutoTrader::HedgeFilledMessageHandler(unsigned long clientOrderId,
                                           unsigned long price,
                                           unsigned long volume)
{
    RLOG(LG_AT, LogLevel::LL_INFO) << "hedge order " << clientOrderId << " filled for " << volume
                                   << " lots at $" << price << " average price in cents";
}

void AutoTrader::OrderBookMessageHandler(Instrument instrument,
                                         unsigned long sequenceNumber,
                                         const std::array<unsigned long, TOP_LEVEL_COUNT>& askPrices,
                                         const std::array<unsigned long, TOP_LEVEL_COUNT>& askVolumes,
                                         const std::array<unsigned long, TOP_LEVEL_COUNT>& bidPrices,
                                         const std::array<unsigned long, TOP_LEVEL_COUNT>& bidVolumes)
{

    if (instrument == Instrument::FUTURE)
    {
        theo = (((bidPrices[0])* askVolumes[0] + (askPrices[0])*bidVolumes[0])/(bidVolumes[0]+askVolumes[0])+50)/100 * 100;
        unsigned long bidAdjustment = (3  + (mPosition / 50))* TICK_SIZE_IN_CENTS;
        unsigned long askAdjustment = (3 - (mPosition / 50))* TICK_SIZE_IN_CENTS;


        
        // unsigned long bidAdjustment = std::max((unsigned long)1, (unsigned long)(3  + (mPosition / 50))) * TICK_SIZE_IN_CENTS;
        // unsigned long askAdjustment = std::max((unsigned long)1, (unsigned long)(3 - (mPosition / 50))) * TICK_SIZE_IN_CENTS;
        unsigned long newAskPrice = (askPrices[0] != 0) ? theo + askAdjustment : 0;
        unsigned long newBidPrice = (bidPrices[0] != 0) ? theo - bidAdjustment : 0;

        int new_bid_volume = 50;
        int new_ask_volume = 50; 
        if(mPosition > 50) {
            int diff = (mPosition - 50);
            new_bid_volume = 50 - diff;
            new_ask_volume = 50 + diff;
            
        }
        if(mPosition < -50) {
            int diff = (-mPosition - 50);
            new_ask_volume = 50 - diff;
            new_bid_volume = 50 + diff;
        }

        bid_volume = new_bid_volume;
        ask_volume = new_ask_volume;

        if (mAskId != 0 && newAskPrice != 0 && newAskPrice != mAskPrice)
        {
          //  SendCancelOrder(mAskId);
            mExecutionConnection->SendMessage(MessageType::CANCEL_ORDER, askCancel);
            mAskId = 0;
        }
        if (mBidId != 0 && newBidPrice != 0 && newBidPrice != mBidPrice)
        {
           // SendCancelOrder(mBidId);
            mExecutionConnection->SendMessage(MessageType::CANCEL_ORDER, bidCancel);
            mBidId = 0;
        }

        if (mAskId == 0 && newAskPrice != 0)
        {
            mAskId = mNextMessageId++;
            mAskPrice = newAskPrice;
            SendInsertOrder(mAskId, Side::SELL, newAskPrice, ask_volume, Lifespan::GOOD_FOR_DAY);
            mAsks.emplace(mAskId);
        }
        if (mBidId == 0 && newBidPrice != 0)
        {
            mBidId = mNextMessageId++;
            mBidPrice = newBidPrice;
            SendInsertOrder(mBidId, Side::BUY, newBidPrice, bid_volume, Lifespan::GOOD_FOR_DAY);
            mBids.emplace(mBidId);
        }
        bidCancel = CancelMessage{mBidId};
        askCancel = CancelMessage{mAskId};
    } 
    

        RLOG(LG_AT, LogLevel::LL_INFO) << "order book received for " << instrument << " instrument"
                                   << ": ask prices: " << askPrices[0]
                                   << "; ask volumes: " << askVolumes[0]
                                   << "; bid prices: " << bidPrices[0]
                                   << "; bid volumes: " << bidVolumes[0];

}

void AutoTrader::OrderFilledMessageHandler(unsigned long clientOrderId,
                                           unsigned long price,
                                           unsigned long volume)
{
  
    if (mAsks.count(clientOrderId) == 1)
    {
        mPosition -= (long)volume;
        SendHedgeOrder(mNextMessageId++, Side::BUY, MAXIMUM_ASK/TICK_SIZE_IN_CENTS*TICK_SIZE_IN_CENTS, volume);
        tick_since_last_ask = 0;
    }
    else if (mBids.count(clientOrderId) == 1)
    {
        mPosition += (long)volume;
        SendHedgeOrder(mNextMessageId++, Side::SELL, MINIMUM_BID, volume);
        tick_since_last_bid = 0;
    }

      RLOG(LG_AT, LogLevel::LL_INFO) << "order " << clientOrderId << " filled for " << volume
                                   << " lots at $" << price << " cents";
}

void AutoTrader::OrderStatusMessageHandler(unsigned long clientOrderId,
                                           unsigned long fillVolume,
                                           unsigned long remainingVolume,
                                           signed long fees)
{
    if (remainingVolume == 0)
    {
        if (clientOrderId == mAskId)
        {
            mAskId = 0;
        }
        else if (clientOrderId == mBidId)
        {
            mBidId = 0;
        }

        mAsks.erase(clientOrderId);
        mBids.erase(clientOrderId);
    }
}

void AutoTrader::TradeTicksMessageHandler(Instrument instrument,
                                          unsigned long sequenceNumber,
                                          const std::array<unsigned long, TOP_LEVEL_COUNT>& askPrices,
                                          const std::array<unsigned long, TOP_LEVEL_COUNT>& askVolumes,
                                          const std::array<unsigned long, TOP_LEVEL_COUNT>& bidPrices,
                                          const std::array<unsigned long, TOP_LEVEL_COUNT>& bidVolumes)
{
  
     
     if (instrument == Instrument::FUTURE) {
 /*
    
            if(bidPrices[0] == 0 || askPrices[0] == 0) {
                return;
            }

            theo = mid_price(bidPrices[0], askPrices[0]);




            if(theo - mBidPrice < -1*(TICK_SIZE_IN_CENTS) && mBidId!=0)
            {
                SendCancelOrder(mBidId);
                mBidId = 0;
            }
            if(mAskPrice - theo < -1*(TICK_SIZE_IN_CENTS) && mAskId!=0){
                SendCancelOrder(mAskId);
                mAskId = 0;
            }

        
            int hit_volume = std::min(200-bid_volume-ask_volume, (int)(mPosition + (POSITION_LIMIT - ask_volume)));
            if(hit_volume > 0) {
                int client_id = mNextMessageId++;
                SendInsertOrder(client_id, Side::SELL, theo+2*(TICK_SIZE_IN_CENTS), hit_volume, Lifespan::FILL_AND_KILL);
                mAsks.emplace(client_id);
            }

            hit_volume = std::min(200-bid_volume-ask_volume, (int)((POSITION_LIMIT - bid_volume) - mPosition));
            if(hit_volume > 0) {
                int client_id = mNextMessageId++;
                SendInsertOrder(client_id, Side::BUY, theo-2*(TICK_SIZE_IN_CENTS), hit_volume, Lifespan::FILL_AND_KILL);
                mBids.emplace(client_id);
            }
            
            */
     }

       RLOG(LG_AT, LogLevel::LL_INFO) << "trade ticks received for " << instrument << " instrument"
                                   << ": ask prices: " << askPrices[0]
                                   << "; ask volumes: " << askVolumes[0]
                                   << "; bid prices: " << bidPrices[0]
                                   << "; bid volumes: " << bidVolumes[0];


}