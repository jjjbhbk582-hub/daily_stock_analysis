"""Regression fixtures are synthetic except explicitly labeled issuer events."""
import unittest
from datetime import datetime,timedelta,timezone
from listing_lifecycle import StageEvidence,entry_decision,known_retirement
T=timezone(timedelta(hours=8))
def ts(s):return datetime.fromisoformat(s).replace(tzinfo=T)

def ordinary(symbol='SH600001',date='2021-04-15'):
    return StageEvidence(symbol,ts(date+'T00:00:00'),ts(date+'T00:00:00'),
        ts(date+'T23:59:59'),'ordinary_listed','synthetic official snapshot')

class LifecycleTests(unittest.TestCase):
    def test_isst_zero_alone_is_not_enough(self):
        self.assertFalse(entry_decision('SH600001',ts('2021-04-15T09:25:00'),0,1,[]).allowed)
    def test_confirmed_ordinary_is_allowed(self):
        self.assertTrue(entry_decision('SH600001',ts('2021-04-15T09:25:00'),0,1,[ordinary()]).allowed)
    def test_st_never_allowed(self):
        self.assertFalse(entry_decision('SH600001',ts('2021-04-15T09:25:00'),1,1,[ordinary()]).allowed)
    def test_unknown_vendor_state_never_allowed(self):
        self.assertFalse(entry_decision('SH600001',ts('2021-04-15T09:25:00'),-1,1,[ordinary()]).allowed)
    def test_halted_never_allowed(self):
        self.assertFalse(entry_decision('SH600001',ts('2021-04-15T09:25:00'),0,0,[ordinary()]).allowed)
    def test_excluded_boards(self):
        for s in ('SH688001','SZ300001','SZ301001','BJ920001','SH900901','SZ200001','SH000001'):
            with self.subTest(s=s):self.assertFalse(entry_decision(s,ts('2021-04-15T09:25:00'),0,1,[ordinary(s)]).allowed)
    def test_kangde_retirement_known_before_buy(self):
        e=known_retirement('SZ002450','2021-04-06','2021-04-14','SZSE announcement')
        self.assertFalse(entry_decision('SZ002450',ts('2021-04-15T09:25:00'),0,1,e).allowed)
    def test_pengqi_retirement_known_before_buy(self):
        e=known_retirement('SH600614','2021-05-26','2021-06-02','issuer announcement')
        self.assertFalse(entry_decision('SH600614',ts('2021-06-03T09:25:00'),0,1,e).allowed)
    def test_delisting_overrides_stale_positive_snapshot(self):
        e=[ordinary('SZ002450')]+known_retirement('SZ002450','2021-04-06','2021-04-14','SZSE')
        d=entry_decision('SZ002450',ts('2021-04-15T09:25:00'),0,1,e)
        self.assertFalse(d.allowed);self.assertTrue('retirement' in d.reason)
    def test_future_announcement_does_not_backfill(self):
        e=[ordinary()]+[StageEvidence('SH600001',ts('2021-04-16T00:00:00'),ts('2021-04-14T00:00:00'),None,'delisting_final','synthetic late retrieval')]
        self.assertTrue(entry_decision('SH600001',ts('2021-04-15T09:25:00'),0,1,e).allowed)
    def test_expired_snapshot_is_not_forward_filled(self):
        self.assertFalse(entry_decision('SH600001',ts('2021-04-16T09:25:00'),0,1,[ordinary()]).allowed)
    def test_other_security_evidence_cannot_admit(self):
        self.assertFalse(entry_decision('SH600002',ts('2021-04-15T09:25:00'),0,1,[ordinary()]).allowed)
    def test_date_only_announcement_is_available_next_day(self):
        e=known_retirement('SH600001','2021-04-15','2021-04-20','synthetic')
        self.assertEqual(e[0].known_from,ts('2021-04-16T00:00:00'))
        self.assertTrue(entry_decision('SH600001',ts('2021-04-15T09:25:00'),0,1,[ordinary()]+e).allowed)
    def test_pending_delisting_also_blocks_before_final_period(self):
        e=known_retirement('SZ002450','2021-04-06','2021-04-14','SZSE')
        self.assertFalse(entry_decision('SZ002450',ts('2021-04-09T09:25:00'),0,1,e).allowed)
    def test_naive_time_is_rejected(self):
        with self.assertRaises(ValueError):entry_decision('SH600001',datetime(2021,4,15),0,1,[])
    def test_invalid_stage_and_date_are_rejected(self):
        with self.assertRaises(ValueError):StageEvidence('SH600001',ts('2021-04-15T00:00:00'),ts('2021-04-15T00:00:00'),None,'assumed_good','synthetic')
        with self.assertRaises(ValueError):known_retirement('SZ002450','2021-04-06','2021-04-01','synthetic')
    def test_ordinary_snapshot_needs_end(self):
        with self.assertRaises(ValueError):StageEvidence('SH600001',ts('2021-04-15T00:00:00'),ts('2021-04-15T00:00:00'),None,'ordinary_listed','synthetic')
    def test_snapshot_not_yet_effective(self):
        self.assertFalse(entry_decision('SH600001',ts('2021-04-14T09:25:00'),0,1,[ordinary()]).allowed)

if __name__=='__main__':unittest.main()
