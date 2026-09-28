import copy
import unittest
from inferno_research_identity import contract_key, input_key, novel_fast_entries, entry_features
from inferno_shadow_evidence import merge_shadow_entries


def row(**values):
    return {'ticketId':'a','ticker':'TEST','strategy':'CALL_DEBIT_SPREAD','expiration':'2026-12-18',
            'tradeDate':'2026-09-28','status':'shadow-open','entryLimit':1.2,'underlyingPrice':20,
            'legs':[{'symbol':'TEST_CALL','instruction':'BUY_TO_OPEN','quantity':1,'bid':1.1,'ask':1.3}],
            'outcome':{'status':'open'}, **values}


class ResearchDedupeTests(unittest.TestCase):
    def test_shadow_next_day_same_contract_is_not_another_experiment(self):
        original=row(entryFeatureSnapshot={'ivRank':42}); ledger={'items':[original]};before=copy.deepcopy(ledger)
        result,inserted=merge_shadow_entries(ledger,[row(ticketId='b',tradeDate='2026-09-29',entryLimit=2)])
        self.assertEqual(inserted,0);self.assertEqual(result['items'],before['items'])
        self.assertEqual(result['duplicateExperimentsSuppressed'],1);self.assertEqual(ledger,before)

    def test_closed_and_legacy_duplicate_rows_remain_untouched(self):
        old=row(outcome={'status':'closed','estimatedPnl':50}); duplicate=row(ticketId='old-copy')
        result,n=merge_shadow_entries({'items':[old,duplicate]},[row(ticketId='c',tradeDate='2026-09-30')])
        self.assertEqual(n,0);self.assertEqual(result['items'],[old,duplicate])

    def test_distinct_contract_is_new_and_repeated_batch_is_idempotent(self):
        other=row(ticketId='b',expiration='2027-01-15')
        result,n=merge_shadow_entries({'items':[row()]},[other,other])
        self.assertEqual(n,1);self.assertEqual(len(result['items']),2)

    def test_missing_identity_never_collapses_unrelated_days(self):
        self.assertIsNone(contract_key(row(legs=[])))
        result,n=merge_shadow_entries({'items':[row(legs=[])]},[row(legs=[],ticketId='b',tradeDate='2026-09-29')])
        self.assertEqual(n,1)

    def test_fast_same_input_new_report_day_is_suppressed(self):
        first=row();later=row(ticketId='b',tradeDate='2026-09-29',sourceStrikePlanGeneratedAt='new-report')
        self.assertEqual(input_key(first),input_key(later))
        accepted,count=novel_fast_entries([first],[later]);self.assertEqual(accepted,[]);self.assertEqual(count,1)

    def test_fast_new_quote_or_economics_is_a_new_observation(self):
        for later in [row(ticketId='b',entryLimit=1.25),row(ticketId='b',entryFeatureSnapshot={'optionContext':{'quoteAsOf':'2026-09-29'}})]:
            accepted,count=novel_fast_entries([row()],[later]);self.assertEqual(len(accepted),1);self.assertEqual(count,0)

    def test_snapshot_preserves_missing_features_without_backfill(self):
        snapshot=entry_features({'ivRank':0,'schwabOptions':{'quoteAsOf':'observed'}})
        self.assertEqual(snapshot['features']['ivRank'],0)
        self.assertIsNone(snapshot['features']['readiness'])
        self.assertEqual(snapshot['optionContext']['quoteAsOf'],'observed')
