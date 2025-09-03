from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
import threading
import time

class TradingApp(EWrapper, EClient):
  def __init__(self):
    EClient.__init__(self, self)
    self.data = {} # Lagringsplass for mottatte data
    self.connected = False
    self.connection_error = None
    self.next_valid_id = None
    
  def error(self, reqId, errorCode, errorString):
    if errorCode in [2104, 2106, 2158]: # Disse er informasjonsmeldinger som alltid kommer
      pass
    else:
      print(f"Error*: {reqId} | {errorCode} | {errorString}")
      self.connection_error = errorString

  def connectAck(self):
    self.connected = True
    print("Tilkobling bekreftet")

  def nextValidId(self, orderId): # IB krever at vi bruker deres tildelte ID-nummer for forespørsler
    self.next_valid_id = orderId
    print(f"Neste gyldige ID: {orderId}")

  def tickPrice(self, reqId, tickType, price, attrib):
    if tickType == 4:  # siste pris
      self.data[reqId] = price
      print(f"Pris for reqId {reqId}: {price}")

def create_contract(symbol, sec_type="STK", exchange="SMART", currency="USD"):
  contract = Contract()
  contract.symbol = symbol
  contract.secType = sec_type # Type instrument (STK = aksje)
  contract.exchange = exchange
  contract.currency = currency
  return contract

def connect_to_ib(app, host="127.0.0.1", port=7497, client_id=100):
  # Kobler til IB TWS/Gateway
  try:
    app.connect(host, port, client_id)
    app.connection_error = None
    
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    
    # Vent på tilkobling og neste gyldige ID
    timeout = 15
    start_time = time.time()
    while (not app.connected or app.next_valid_id is None) and time.time() - start_time < timeout:
      if app.connection_error:
        raise ConnectionError(f"Kunne ikke koble til: {app.connection_error}")
      time.sleep(0.5)
      
    if not app.connected or app.next_valid_id is None:
      raise ConnectionError("Timeout: Kunne ikke etablere full tilkobling til IB")
      
    print("Tilkobling vellykket og klar for handel")
    return True
    
  except Exception as e:
    print(f"Tilkoblingsfeil: {e}")
    return False

def get_market_data(app, contract, req_id=1, timeout=10):
  try:
    # Be om markedsdata
    app.reqMktData(req_id, contract, "", False, False, [])
    print(f"Forespurt markedsdata for {contract.symbol}, reqId: {req_id}")
    
    # Vent på data
    start_time = time.time()
    while req_id not in app.data:
      if time.time() - start_time > timeout:
        raise TimeoutError("Timeout ved henting av markedsdata")
      time.sleep(0.5)
    
    price = app.data[req_id]
    return price
    
  except Exception as e:
    print(f"Feil ved henting av markedsdata: {e}")
    return None
    
  finally:
    try:
      app.cancelMktData(req_id) # Avbryt forespørselen
      if req_id in app.data:
        del app.data[req_id] # Fjern data for denne forespørselen
    except:
      pass

def main():
  app = TradingApp()
  
  if not connect_to_ib(app):
    return
  
  try:
    # Vent litt ekstra for å sikre at tilkoblingen er stabil
    time.sleep(2)
    
    symbol = "AAPL"  # Ønsket symbol
    contract = create_contract(symbol)
    
    price = get_market_data(app, contract)
    
    if price is not None:
      print(f"Gjeldende pris for {symbol}: {price}")
    else:
      print(f"Kunne ikke hente pris for {symbol}")

  except Exception as e:
    print(f"Feil under kjøring: {e}")
  
  finally:
    try:
      app.disconnect()
      print("Koblet fra IB")
    except:
      print("Kunne ikke koble fra ren")

if __name__ == "__main__":
  main()