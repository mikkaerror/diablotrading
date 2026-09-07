"""Explicit recorded-fill sources for tests; never copied from runtime data."""
from inferno_tos_fill_ingest import row_fingerprint


def source_for(tickets):
    rows = [dict(ticket['_sourceFixture']) for ticket in tickets if '_sourceFixture' in ticket]
    return {'status': 'ok', 'path': 'fixture.csv', 'sha256': 'fixture-only', 'rows': rows}


def add_recorded_fill(ticket, *, risk=100.0):
    pnl = ticket['outcome'].get('estimatedPnl')
    entry = risk / 100.0
    exit_price = entry + (pnl or 0.0) / 100.0
    ticket.update(entryLimit=entry, entryCostType='debit', expiration='2026-07-17', estimatedMaxLoss=risk)
    row = {'ticketId': ticket['ticketId'], 'ticker': ticket['ticker'], 'strategy': ticket['strategy'],
           'expiration': '2026-07-17', 'environment': 'thinkorswim-paperMoney',
           'contracts': '1', 'entryPrice': str(entry), 'exitPrice': str(exit_price),
           'openedAt': '2026-04-26T09:00:00-06:00', 'closedAt': '2026-04-27T09:00:00-06:00',
           'status': 'closed', 'realizedPnl': str(pnl) if pnl is not None else '', 'notes': ''}
    ticket['paperExecution'] = {**row, 'source': 'paper-fill-log', 'contracts': 1,
                               'entryPrice': entry, 'exitPrice': exit_price, 'realizedPnl': pnl}
    ticket['importedFillKeys'] = [row_fingerprint(row)]
    ticket['_sourceFixture'] = row
    return ticket
