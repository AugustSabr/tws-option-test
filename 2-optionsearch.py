from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
import threading
import time
from datetime import datetime

class TradingApp(EWrapper, EClient):
  """Hovedklassen som arver fra både EWrapper og EClient for IB API kommunikasjon"""
  
  def __init__(self):
    EClient.__init__(self, self)
    # Dictionary for å lagre markedsdata med request ID som nøkkel
    self.data = {}
    # Event for å signalisere når tilkoblingen er etablert
    self.connected_event = threading.Event()
    # Neste gyldige ordre-ID fra IB
    self.next_valid_id = None
    # Liste for å lagre opsjonskjeder
    self.opt_params_list = []
    # Event for å signalisere når contract details er mottatt
    self.contract_details_event = threading.Event()
    # Resultatet fra contract details forespørsel
    self.contract_details_result = None

  def error(self, reqId, errorCode, errorString):
    """Håndterer feilmeldinger fra IB"""
    # Ignorerer visse informasjonsmeldinger
    if errorCode not in [2104, 2106, 2158]:
      print(f"Error: {reqId} | {errorCode} | {errorString}")
      # Hvis det er en contract details feil, signaliser at forespørselen er ferdig
      if reqId == 10:  # Contract details request
        self.contract_details_event.set()

  def connectAck(self):
    """Bekrefter at tilkoblingen til IB er etablert"""
    print("Tilkobling bekreftet")

  def nextValidId(self, orderId):
    """Mottar neste gyldige ordre-ID fra IB og signaliserer at tilkoblingen er klar"""
    self.next_valid_id = orderId
    self.connected_event.set()  # Signaliser at tilkoblingen er fullført
    print(f"Neste gyldige ID: {orderId}")

  def tickPrice(self, reqId, tickType, price, attrib):
    """Håndterer prisoppdateringer fra IB"""
    if tickType == 4:  # Siste pris (LAST)
      self.data[reqId] = price  # Lagrer prisen med request ID som nøkkel

  def securityDefinitionOptionParameter(self, reqId, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes):
    """Mottar opsjonsparametre (kjeder) for et underlying instrument"""
    # FILTRER: Bare lagre kjeder med tilstrekkelig mange strikes og expirations
    if expirations and strikes and len(expirations) > 5 and len(strikes) > 10:
      params = {
        "exchange": exchange,
        "expirations": sorted(expirations),  # Sorterte utløpsdatoer
        "strikes": sorted(strikes)  # Sorterte strike-priser
      }
      self.opt_params_list.append(params)
      print(f"Opsjonskjede mottatt: {exchange} - {len(expirations)} exp, {len(strikes)} strikes")
    else:
      # print(f"Filtrert bort: {exchange} - {len(expirations)} exp, {len(strikes)} strikes (for få)")
      pass # trenger ikke logge de med for få strikes/expirations

  def contractDetails(self, reqId, contractDetails):
    """Mottar detaljerte kontraktinformasjon"""
    if reqId == 10:
      self.contract_details_result = contractDetails
      self.contract_details_event.set()  # Signaliser at data er mottatt

  def contractDetailsEnd(self, reqId):
    """Signaliserer slutten på en contract details forespørsel"""
    if reqId == 10 and not self.contract_details_event.is_set():
      self.contract_details_event.set()  # Signaliser hvis ingen detaljer ble mottatt

def create_contract(symbol, sec_type="STK", exchange="SMART", currency="USD"):
  """Hjelpefunksjon for å opprette en aksjekontrakt"""
  contract = Contract()
  contract.symbol = symbol  # Aksjesymbol (f.eks. AAPL)
  contract.secType = sec_type  # Verditype (STK for aksjer)
  contract.exchange = exchange  # Børs (SMART for automatisk ruting)
  contract.currency = currency  # Valuta
  return contract

def create_option_contract(symbol, strike, expiry, right="C", exchange="SMART", currency="USD"):
  """Hjelpefunksjon for å opprette en opsjonskontrakt"""
  contract = Contract()
  contract.symbol = symbol  # Underliggende symbol
  contract.secType = "OPT"  # Verditype (OPT for opsjoner)
  contract.exchange = exchange  # Børs
  contract.currency = currency  # Valuta
  contract.strike = strike  # Strike-pris
  contract.lastTradeDateOrContractMonth = expiry  # Utløpsdato (YYYYMMDD format)
  contract.right = right  # Opsjonstype (C for call, P for put)
  contract.multiplier = "100"  # Kontraktstørrelse (standard 100 aksjer per opsjon)
  return contract

def connect_to_ib(app, host="127.0.0.1", port=7497, client_id=100):
  """Etablerer tilkobling til IB Gateway/TWS"""
  try:
    # Initier tilkobling
    app.connect(host, port, client_id)
    # Start kommunikasjons-tråd i bakgrunnen
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    
    # Vent på at tilkoblingen blir etablert (maks 15 sekunder)
    if not app.connected_event.wait(timeout=15):
      raise ConnectionError("Timeout: Kunne ikke etablere tilkobling til IB")
      
    print("Tilkobling vellykket og klar for handel")
    return True
    
  except Exception as e:
    print(f"Tilkoblingsfeil: {e}")
    return False

def get_market_data(app, contract, req_id, timeout=10):
  """Henter markedsdata for en gitt kontrakt"""
  try:
    # Forespør markedsdata fra IB
    app.reqMktData(req_id, contract, "", False, False, [])
    print(f"Forespurt markedsdata for {contract.symbol}, reqId: {req_id}")
    
    # Vent på at data blir mottatt (maks 10 sekunder)
    start_time = time.time()
    while req_id not in app.data:
      if time.time() - start_time > timeout:
        raise TimeoutError("Timeout ved henting av markedsdata")
      time.sleep(0.1)
    
    # Returner den mottatte prisen
    return app.data[req_id]
    
  finally:
    # Alltid kanseller forespørselen og rydd opp i data
    try:
      app.cancelMktData(req_id)
      if req_id in app.data:
        del app.data[req_id]
    except:
      pass

def get_contract_details(app, contract, req_id=10, timeout=10):
  """Henter detaljert kontraktinformasjon fra IB"""
  # Tilbakestill event og resultat før ny forespørsel
  app.contract_details_event.clear()
  app.contract_details_result = None
  
  # Send forespørsel om kontraktdetaljer
  app.reqContractDetails(req_id, contract)
  print(f"Forespurt contract details for {contract.symbol}, reqId: {req_id}")
  
  # Vent på svar (maks 10 sekunder)
  if not app.contract_details_event.wait(timeout=timeout):
    raise TimeoutError("Timeout ved henting av contract details")
  
  # Returner resultatet
  return app.contract_details_result

def find_best_option_chain(opt_params_list, current_price):
  """Finn den beste opsjonskjeden basert på nærhet til gjeldende pris"""
  if not opt_params_list:
    return None
    
  best_chain = None
  best_strike_diff = float('inf')  # Start med uendelig differanse
  
  # Gå gjennom alle mottatte opsjonskjeder
  for params in opt_params_list:
    strikes = params["strikes"]
    expirations = params["expirations"]
    
    # Hopp over ufullstendige kjeder
    if not strikes or not expirations:
      continue
      
    # Finn nærmeste strike-pris til gjeldende markedspris
    nearest_strike = min(strikes, key=lambda x: abs(x - current_price))
    strike_diff = abs(nearest_strike - current_price)
    
    # Finn nærmeste fremtidige utløpsdato
    now = datetime.now()
    nearest_expiry = None
    expiry_diff = float('inf')
    
    for expiry in expirations:
      try:
        # Konverter til datetime-objekt
        expiry_date = datetime.strptime(expiry, '%Y%m%d')
        # Sjekk at datoen er i fremtiden
        if expiry_date > now:
          days_diff = (expiry_date - now).days
          # Finn den nærmeste datoen
          if days_diff < expiry_diff:
            expiry_diff = days_diff
            nearest_expiry = expiry
      except ValueError:
        continue  # Hopp over ugyldige datoformater
    
    # Hopp over hvis ingen gyldig utløpsdato ble funnet
    if nearest_expiry is None:
      continue
      
    # Velg kjeden med strike nærmest gjeldende pris
    if strike_diff < best_strike_diff:
      best_strike_diff = strike_diff
      best_chain = {
        "exchange": params["exchange"],
        "strike": nearest_strike,
        "expiry": nearest_expiry,
        "strike_diff": strike_diff,
        "expiry_diff": expiry_diff
      }
  
  return best_chain

def main():
  """Hovedfunksjon som kjører hele prosessen"""
  # Opprett trading app-instans
  app = TradingApp()
  
  # Koble til IB
  if not connect_to_ib(app):
    return  # Avslutt hvis tilkobling feiler
  
  try:
    # Vent litt for at tilkoblingen skal stabilisere
    time.sleep(1)
    
    # Definer aksjen vi er interessert i
    symbol = "AAPL"
    # Opprett kontrakt for aksjen
    contract = create_contract(symbol)
    
    # Hent gjeldende markedspris for aksjen
    price = get_market_data(app, contract, 1)
    if price is None:
      print(f"Kunne ikke hente pris for {symbol}")
      return
    print(f"Gjeldende pris for {symbol}: {price}")

    # Hent kontraktdetaljer for å få conId (kontrakt-ID)
    details = get_contract_details(app, contract)
    # Bruk conId hvis tilgjengelig, ellers bruk 0 (vil søke med symbol)
    conId = details.contract.conId if details else 0
    print(f"Contract ID: {conId}")

    # Tøm liste med opsjonskjeder fra tidligere forespørsler
    app.opt_params_list = []
    # Forespør opsjonsparametre (kjeder) for aksjen
    app.reqSecDefOptParams(2, symbol, "", "STK", conId)
    print("Venter på opsjonskjeder...")
    
    # Vent tilstrekkelig lenge for å motta alle opsjonskjedene
    time.sleep(3)
    
    # Sjekk om noen opsjonskjeder ble mottatt
    if not app.opt_params_list:
      print("Ingen opsjonskjeder mottatt")
      return
      
    print(f"Mottatt {len(app.opt_params_list)} opsjonskjeder")
    
    # Finn den beste opsjonskjeden basert på gjeldende pris
    best_option = find_best_option_chain(app.opt_params_list, price)
    
    if not best_option:
      print("Kunne ikke finne passende opsjon")
      return
      
    # Skriv ut informasjon om den beste opsjonen
    print(f"Beste opsjon funnet:")
    print(f"  Børs: {best_option['exchange']}")
    print(f"  Strike: {best_option['strike']} (diff: {best_option['strike_diff']:.2f})")
    print(f"  Utløp: {best_option['expiry']} (om {best_option['expiry_diff']} dager)")

    # Hent priser for både call og put opsjoner
    for right, req_id in [("C", 3), ("P", 4)]:
      # Opprett opsjonskontrakt
      option_contract = create_option_contract(
        symbol, 
        best_option["strike"], 
        best_option["expiry"], 
        right, 
        exchange=best_option["exchange"]
      )
      
      # Hent markedspris for opsjonen
      option_price = get_market_data(app, option_contract, req_id)
      if option_price is not None:
        print(f"{right} opsjonspris: {option_price}")
      else:
        print(f"Kunne ikke hente {right} opsjonspris")

  except Exception as e:
    # Håndter eventuelle feil under kjøring
    print(f"Feil under kjøring: {e}")
  finally:
    # Alltid koble fra IB til slutt
    app.disconnect()
    print("Koblet fra IB")

if __name__ == "__main__":
  # Kjør hovedfunksjonen når scriptet kjøres direkte
  main()